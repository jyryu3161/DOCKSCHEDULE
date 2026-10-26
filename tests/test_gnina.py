import os
import stat
import sys
import time
from pathlib import Path
import psutil
import pytest
from dockschedule import gnina
from dockschedule.gnina_rank import average_ranks, consensus_order, extra_ranks

FAKE = '''#!%s
import os, re, sys, time
args = sys.argv[1:]
if args == ['--version']:
    print('gnina v1.3.3 master:6fe1ce2   Built Jun 30 2026.')
    sys.exit(0)
a = dict(zip(args[::1], args[1::1]))
assert '--score_only' in args and '--no_gpu' in args and a['--cpu'] == '1' and '--cnn' not in args
assert os.environ.get('CUDA_VISIBLE_DEVICES') == '' and os.environ.get('OMP_NUM_THREADS') == '1'
blocks = [b for b in open(a['-l']).read().split('$$$$\\n') if b.strip()]
log = os.environ.get('FAKE_LOG')
if log:
    open(log, 'a').write('S %%d %%f\\n' %% (os.getpid(), time.time()))
    time.sleep(float(os.environ.get('FAKE_SLEEP', '0')))
def prop(b, n):
    m = re.search(r'> +<%%s>[^\\n]*\\n(.*)\\n' %% n, b)
    return m.group(1) if m else None
if os.environ.get('FAKE_BATCH_FAIL') and len(blocks) > 1:
    sys.exit(3)
if any(prop(b, 'fake') == 'hang' for b in blocks):
    time.sleep(600)
if any(prop(b, 'fake') == 'bad' for b in blocks):
    sys.exit(1)
if os.environ.get('FAKE_DROP') and len(blocks) > 1:
    blocks = blocks[:-1]
out = ''
for b in blocks:
    v = float(prop(b, 'val') or 1)
    nan = prop(b, 'fake') == 'nan'
    out += b if b.endswith('\\n') else b + '\\n'
    out += '> <minimizedAffinity>\\n%%s\\n\\n> <CNNscore>\\n%%s\\n\\n> <CNNaffinity>\\n%%s\\n\\n> <CNN_VS>\\n0\\n\\n> <CNNaffinity_variance>\\n0.1\\n\\n$$$$\\n' %% (-v, 'nan' if nan else v / 10, v / 2)
open(a['-o'], 'w').write(out)
if log:
    open(log, 'a').write('E %%d %%f\\n' %% (os.getpid(), time.time()))
'''


@pytest.fixture
def fake(tmp_path):
    path = tmp_path / 'gnina'
    path.write_text(FAKE % sys.executable)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return path


def make_pose(path, smiles, val, fake_flag=None, hydrogens=True):
    from rdkit import Chem
    from rdkit.Chem import AllChem
    mol = Chem.AddHs(Chem.MolFromSmiles(smiles))
    AllChem.EmbedMolecule(mol, randomSeed=7)
    if not hydrogens:
        mol = Chem.RemoveHs(mol)
    mol.SetProp('_Name', 'best')
    mol.SetProp('val', str(val))
    if fake_flag:
        mol.SetProp('fake', fake_flag)
    w = Chem.SDWriter(str(path))
    w.write(mol)
    w.close()
    return path


def poses(tmp_path, n, flags=None):
    flags = flags or {}
    return [(i, make_pose(tmp_path / f'p{i}.sdf', 'CCO', i + 1, flags.get(i))) for i in range(n)]


@pytest.fixture
def receptor(tmp_path):
    p = tmp_path / 'receptor.pdb'
    p.write_text('END\n')
    return p


def run(tmp_path, receptor, fake, items, cpus=2, **kw):
    work = tmp_path / 'work'
    work.mkdir(exist_ok=True)
    return gnina.score_batch(receptor, items, cpus, fake, work, kw.pop('compound_timeout', 20), **kw)


def test_check_binary_checksum_and_version(tmp_path, fake):
    import hashlib
    with pytest.raises(ValueError, match='체크섬'):
        gnina.check_binary(fake)
    digest = hashlib.sha256(fake.read_bytes()).hexdigest()
    assert gnina.check_binary(fake, expected_sha256=digest).startswith('gnina v1.3.3')
    assert gnina.version(fake).startswith('gnina v1.3.3')
    with pytest.raises(ValueError, match='GNINA'):
        gnina.check_binary(tmp_path / 'missing')


def test_pinned_constant():
    assert gnina.GNINA_SHA256 == '3340c1f49cd3c7c84d8699182a1c6af13c7fa2a22448d1204640446106f72172'


def test_order_mapping_and_cnn_vs_with_identical_titles(tmp_path, receptor, fake):
    items = poses(tmp_path, 5)
    res = run(tmp_path, receptor, fake, [(f'k{i}', p) for i, p in items])
    assert set(res) == {f'k{i}' for i in range(5)}
    for i in range(5):
        r = res[f'k{i}']
        v = i + 1
        assert r['status'] == 'succeeded' and r['error'] is None
        assert r['gnina_vina'] == pytest.approx(-v)
        assert r['cnn_score'] == pytest.approx(v / 10)
        assert r['cnn_affinity'] == pytest.approx(v / 2)
        assert r['cnn_vs'] == pytest.approx(v / 10 * v / 2)


def test_batch_failure_isolates_bad_compound(tmp_path, receptor, fake, monkeypatch):
    monkeypatch.setattr(gnina, 'BATCH_SIZE', 4)
    items = [(i, p) for i, p in poses(tmp_path, 4, {2: 'bad'})]
    res = run(tmp_path, receptor, fake, items, cpus=1)
    assert [res[i]['status'] for i in range(4)] == ['succeeded', 'succeeded', 'failed', 'succeeded']
    bad = res[2]
    assert bad['error'] and bad['cnn_score'] is None and bad['gnina_vina'] is None


@pytest.mark.parametrize('knob', ['FAKE_BATCH_FAIL', 'FAKE_DROP'])
def test_whole_batch_failure_and_count_mismatch_rerun_individually(tmp_path, receptor, fake, monkeypatch, knob):
    monkeypatch.setenv(knob, '1')
    res = run(tmp_path, receptor, fake, poses(tmp_path, 3), cpus=1)
    assert all(r['status'] == 'succeeded' for r in res.values())


def test_non_finite_score_rejected(tmp_path, receptor, fake):
    res = run(tmp_path, receptor, fake, poses(tmp_path, 3, {1: 'nan'}), cpus=1)
    assert [res[i]['status'] for i in range(3)] == ['succeeded', 'failed', 'succeeded']


def test_timeout_marks_only_hanging_compound_failed(tmp_path, receptor, fake):
    start = time.monotonic()
    res = run(tmp_path, receptor, fake, poses(tmp_path, 2, {1: 'hang'}), cpus=1, compound_timeout=2)
    assert time.monotonic() - start < 15
    assert res[0]['status'] == 'succeeded'
    assert res[1]['status'] == 'failed' and '시간' in res[1]['error']


def test_unreadable_pose_fails_without_blocking_others(tmp_path, receptor, fake):
    items = poses(tmp_path, 2)
    junk = tmp_path / 'junk.sdf'
    junk.write_text('not an sdf\n')
    res = run(tmp_path, receptor, fake, [*items, ('junk', junk)])
    assert res['junk']['status'] == 'failed' and res[0]['status'] == 'succeeded'


def test_never_more_than_cpus_concurrent_and_on_result(tmp_path, receptor, fake, monkeypatch):
    log = tmp_path / 'log'
    monkeypatch.setenv('FAKE_LOG', str(log))
    monkeypatch.setenv('FAKE_SLEEP', '0.4')
    monkeypatch.setattr(gnina, 'BATCH_SIZE', 1)
    seen = []
    res = run(tmp_path, receptor, fake, poses(tmp_path, 6), cpus=2, on_result=lambda k, r: seen.append(k))
    assert len(res) == 6 and sorted(seen) == list(range(6))
    events = sorted((float(l.split()[2]), 1 if l[0] == 'S' else -1) for l in log.read_text().splitlines())
    level = peak = 0
    for _, d in events:
        level += d
        peak = max(peak, level)
    assert peak == 2


def test_hydrogens_added_in_temp_input_only(tmp_path):
    from rdkit import Chem
    src = make_pose(tmp_path / 'noh.sdf', 'C[NH3+]', 1, hydrogens=False)
    before = src.read_bytes()
    original = next(Chem.SDMolSupplier(str(src), removeHs=False))
    assert not any(a.GetAtomicNum() == 1 for a in original.GetAtoms())
    dest = tmp_path / 'in.sdf'
    gnina.prepare_pose(src, dest, 'm0')
    assert src.read_bytes() == before
    mol = next(Chem.SDMolSupplier(str(dest), removeHs=False))
    assert mol.GetProp('_Name') == 'm0'
    assert sum(a.GetAtomicNum() == 1 for a in mol.GetAtoms()) == 6
    assert Chem.GetFormalCharge(mol) == 1
    c0, c1 = original.GetConformer().GetPositions(), mol.GetConformer().GetPositions()
    assert abs(c0 - c1[:len(c0)]).max() < 1e-3


def test_hydrogens_already_present_unchanged_count(tmp_path):
    from rdkit import Chem
    src = make_pose(tmp_path / 'h.sdf', 'CCO', 1)
    dest = tmp_path / 'in.sdf'
    gnina.prepare_pose(src, dest, 'm0')
    a = next(Chem.SDMolSupplier(str(src), removeHs=False))
    b = next(Chem.SDMolSupplier(str(dest), removeHs=False))
    assert a.GetNumAtoms() == b.GetNumAtoms()


def test_cancellation_kills_children_and_keeps_finished(tmp_path, receptor, fake, monkeypatch):
    log = tmp_path / 'log'
    monkeypatch.setenv('FAKE_LOG', str(log))
    monkeypatch.setattr(gnina, 'BATCH_SIZE', 1)
    items = poses(tmp_path, 3, {1: 'hang', 2: 'hang'})
    t0 = time.monotonic()
    res = run(tmp_path, receptor, fake, items, cpus=1, should_stop=lambda: time.monotonic() - t0 > 3, compound_timeout=300)
    assert time.monotonic() - t0 < 20
    assert res[0]['status'] == 'succeeded' and 1 not in res and 2 not in res
    pids = [int(l.split()[1]) for l in log.read_text().splitlines() if l[0] == 'S']
    assert pids and not any(psutil.pid_exists(p) and psutil.Process(p).status() != psutil.STATUS_ZOMBIE for p in pids)


@pytest.mark.skipif(not Path('tools/gnina').exists(), reason='tools/gnina 없음')
def test_real_binary(tmp_path):
    binary = Path('tools/gnina').resolve()
    try:
        gnina.check_binary(binary)
    except ValueError:
        pytest.skip('gnina 실행 불가')
    pose = Path('tests/fixtures/interaction-pose.sdf')
    receptor = Path('tests/fixtures/1L83.pdb')
    res = gnina.score_batch(receptor, [('a', pose)], 1, binary, tmp_path, 300)
    assert res['a']['status'] == 'succeeded'


def test_average_ranks_ties():
    assert average_ranks([3, 1, 1, 2]) == [4, 1.5, 1.5, 3]
    assert average_ranks([3, 1, 1, 2], descending=True) == [1, 3.5, 3.5, 2]
    assert average_ranks([]) == []


def rows():
    return [
        dict(id=10, row_number=1, vina=-9, cnn_affinity=5.0),
        dict(id=11, row_number=2, vina=-8, cnn_affinity=7.0),
        dict(id=12, row_number=3, vina=-7, cnn_affinity=6.0),
    ]


def test_consensus_boundaries():
    assert [r['id'] for r in consensus_order(rows(), 0)] == [10, 11, 12]
    assert [r['id'] for r in consensus_order(rows(), 1)] == [11, 12, 10]
    out = consensus_order(rows(), 0.5)
    assert [r['rank']['consensus'] for r in out] == [1, 2, 3]
    assert out[0]['id'] == 11 and out[0]['rank']['vina'] == 2 and out[0]['rank']['cnn_affinity'] == 1
    with pytest.raises(ValueError):
        consensus_order(rows(), 1.5)


def test_consensus_tie_break_by_row_number_and_ranks_over_all_rows():
    tied = [dict(id=1, row_number=5, vina=-8, cnn_affinity=1.0), dict(id=2, row_number=3, vina=-8, cnn_affinity=1.0)]
    out = consensus_order(tied, 0.5)
    assert [r['id'] for r in out] == [2, 1]
    assert [r['rank']['consensus'] for r in out] == [1, 2]
    assert out[0]['rank']['vina'] == 1.5
    assert len(consensus_order(rows(), 0.3)) == 3


def test_extra_ranks_descending():
    data = [dict(id=1, cnn_score=0.2, cnn_vs=1.0), dict(id=2, cnn_score=0.9, cnn_vs=1.0)]
    assert extra_ranks(data) == {1: {'cnn_score': 2, 'cnn_vs': 1.5}, 2: {'cnn_score': 1, 'cnn_vs': 1.5}}
