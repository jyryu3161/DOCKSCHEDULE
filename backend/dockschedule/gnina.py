"""GNINA --score_only rescoring of QuickVina poses. Import only inside CPU-constrained workers, never in api.

Runs pinned GNINA CPU processes (single thread each, at most `cpus` at once) and
kills them with processes.stop_tree. Original pose files are only read.
"""
import hashlib
import math
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import psutil
from .processes import stop_tree

GNINA_SHA256 = '3340c1f49cd3c7c84d8699182a1c6af13c7fa2a22448d1204640446106f72172'
BATCH_SIZE = 25
POLL_SECONDS = 0.5
_SCORES = dict(minimizedAffinity='gnina_vina', CNNscore='cnn_score', CNNaffinity='cnn_affinity')


def version(binary):
    try:
        done = subprocess.run([str(binary), '--version'], capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL,
                              env={**os.environ, 'CUDA_VISIBLE_DEVICES': ''})
    except (OSError, subprocess.SubprocessError):
        raise ValueError('GNINA 바이너리를 실행할 수 없습니다.')
    match = re.search(r'^gnina\s+v\S+.*$', done.stdout, re.M)
    if done.returncode != 0 or not match:
        raise ValueError('GNINA 버전을 확인할 수 없습니다.')
    return match.group(0).strip()


def check_binary(path, expected_sha256=GNINA_SHA256):
    path = Path(path)
    try:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        raise ValueError('GNINA 바이너리를 읽을 수 없습니다.')
    if digest != expected_sha256:
        raise ValueError('GNINA 바이너리 체크섬이 검증된 버전과 다릅니다.')
    return version(path)


def prepare_pose(source, dest, title):
    """Write a temp copy with hydrogens added (coordinates kept) and a unique title."""
    from rdkit import Chem
    mol = next(iter(Chem.SDMolSupplier(str(source), removeHs=False)), None)
    if mol is None or mol.GetNumConformers() == 0:
        raise ValueError('pose SDF를 읽을 수 없습니다.')
    mol = Chem.AddHs(mol, addCoords=True)
    mol.SetProp('_Name', title)
    writer = Chem.SDWriter(str(dest))
    writer.write(mol)
    writer.close()


def parse_scores(text, expected):
    """SDF properties in input order -> list of score dicts (cnn_vs computed here)."""
    blocks = [b for b in text.split('$$$$') if b.strip()]
    if len(blocks) != expected:
        raise ValueError('GNINA 출력 개수가 입력과 다릅니다.')
    out = []
    for block in blocks:
        props = dict(re.findall(r'^>\s+<(\w+)>[^\n]*\n(.*)$', block, re.M))
        try:
            row = {name: float(props[key]) for key, name in _SCORES.items()}
        except (KeyError, ValueError):
            raise ValueError('GNINA 출력을 해석할 수 없습니다.')
        row['cnn_vs'] = row['cnn_score']*row['cnn_affinity']
        if not all(math.isfinite(v) for v in row.values()):
            raise ValueError('GNINA 점수가 유한한 값이 아닙니다.')
        out.append(row)
    return out


def _ok(scores):
    return dict(status='succeeded', error=None, **scores)


def _failed(message):
    return dict(status='failed', error=message, cnn_score=None, cnn_affinity=None, cnn_vs=None, gnina_vina=None)


class _Stop:
    def __init__(self, should_stop):
        self._fn, self._lock, self._set, self._last = should_stop, threading.Lock(), False, 0.0

    def __call__(self):
        with self._lock:
            now = time.monotonic()
            if not self._set and self._fn is not None and now-self._last >= 1:
                self._last, self._set = now, bool(self._fn())
            return self._set


class _Timeout(Exception):
    pass


class _Cancelled(Exception):
    pass


def _message(exc):
    if isinstance(exc, _Timeout):
        return 'GNINA 재채점이 제한 시간을 초과했습니다.'
    return f'GNINA 재채점에 실패했습니다: {exc}'


def _run(binary, receptor, ligands, out, limit, stop):
    """One GNINA process; returns score dicts. Raises _Timeout, _Cancelled or ValueError."""
    env = {**os.environ, 'CUDA_VISIBLE_DEVICES': '', 'OMP_NUM_THREADS': '1', 'OPENBLAS_NUM_THREADS': '1', 'MKL_NUM_THREADS': '1'}
    cmd = [str(binary), '--score_only', '--no_gpu', '--cpu', '1', '-r', str(receptor), '-l', str(ligands), '-o', str(out)]
    with open(out.with_suffix('.log'), 'wb') as log:
        proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, env=env)
        try:
            created = psutil.Process(proc.pid).create_time()
        except psutil.NoSuchProcess:
            created = None
        started = time.monotonic()
        try:
            while True:
                try:
                    proc.wait(timeout=POLL_SECONDS)
                    break
                except subprocess.TimeoutExpired:
                    pass
                if stop():
                    raise _Cancelled
                if time.monotonic()-started > limit:
                    raise _Timeout
        finally:
            if proc.poll() is None:
                stop_tree(proc.pid, created)
                proc.wait()
    if proc.returncode != 0:
        raise ValueError('GNINA 실행이 실패했습니다.')
    count = len(re.findall(r'^\$\$\$\$', ligands.read_text(), re.M))
    return parse_scores(out.read_text(), count)


def score_batch(receptor_pdb, items, cpus, binary, workdir, compound_timeout, should_stop=None, on_result=None):
    """Score (key, pose_sdf) items; returns {key: result}. Unfinished (cancelled) keys are omitted."""
    results, lock, stop = {}, threading.Lock(), _Stop(should_stop)
    scratch = Path(tempfile.mkdtemp(prefix='gnina-', dir=workdir))

    def emit(key, result):
        with lock:
            results[key] = result
            if on_result is not None:
                on_result(key, result)

    try:
        ready = []
        for n, (key, pose) in enumerate(items):
            try:
                prepare_pose(pose, scratch/f'in{n}.sdf', f'm{n}')
                ready.append((n, key))
            except Exception:
                emit(key, _failed('pose를 읽거나 수소를 추가하지 못했습니다.'))
        size = max(1, min(BATCH_SIZE, math.ceil(len(ready)/max(1, cpus))))
        batches = [ready[i:i+size] for i in range(0, len(ready), size)]

        def attempt(tag, members, limit):
            ligands = scratch/f'{tag}.sdf'
            with ligands.open('w') as dest:
                for n, _ in members:
                    dest.write((scratch/f'in{n}.sdf').read_text())
            return _run(binary, receptor_pdb, ligands, scratch/f'{tag}-out.sdf', limit, stop)

        def work(index):
            members = batches[index]
            try:
                for (_, key), scores in zip(members, attempt(f'b{index}', members, compound_timeout*len(members))):
                    emit(key, _ok(scores))
                return
            except _Cancelled:
                return
            except (_Timeout, ValueError) as exc:
                first = exc
            if len(members) == 1:
                emit(members[0][1], _failed(_message(first)))
                return
            for n, key in members:
                if stop():
                    return
                try:
                    emit(key, _ok(attempt(f's{n}', [(n, key)], compound_timeout)[0]))
                except _Cancelled:
                    return
                except (_Timeout, ValueError) as exc:
                    emit(key, _failed(_message(exc)))

        with ThreadPoolExecutor(max_workers=max(1, cpus)) as pool:
            list(pool.map(work, range(len(batches))))
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    return results
