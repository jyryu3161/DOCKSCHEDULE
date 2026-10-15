import json
import math
from types import SimpleNamespace

import pytest
from rdkit import Chem
import prolif as plf

from dockschedule.interactions import _load_ligand, interaction_records
from dockschedule import interaction_service, storage
from dockschedule.db import transaction
from dockschedule.models import Compound, Receptor, Task, Upload, User
from dockschedule.security import password_hash


def molecule(smiles, positions, name='LIG'):
    mol = Chem.AddHs(Chem.MolFromSmiles(smiles))
    assert mol.GetNumAtoms() == len(positions)
    conf = Chem.Conformer(len(positions))
    for i, point in enumerate(positions):
        conf.SetAtomPosition(i, point)
    mol.AddConformer(conf)
    return plf.Molecule.from_rdkit(mol, resname=name, resnumber=42, chain='B')


def atom_records(mol):
    return [dict(index=i, number=i+1, label=f'{a.GetSymbol()}{i+1}', element=a.GetSymbol(),
                 position=list(mol.GetConformer().GetAtomPosition(i))) for i, a in enumerate(mol.GetAtoms())]


def detect(ligand, protein):
    residues = [dict(key='B:42:A', name='ASN', chain='B', number=42, insertion='A',
                     atom_indices=list(range(protein.GetNumAtoms())))] * protein.GetNumAtoms()
    return interaction_records(ligand, protein, atom_records(ligand), atom_records(protein), residues)


DONOR = [(0, 0, 0), (1, 0, 0), (-0.5, 0.8, 0), (-0.5, -0.8, 0)]
ACCEPTOR = [(4.2, 0, 0), (3, 0, 0), (4.8, 0.9, 0), (4.8, -0.9, 0)]


@pytest.mark.parametrize('reverse', [False, True])
def test_hbond_uses_donor_acceptor_endpoints_and_original_atom_indices(reverse):
    donor = molecule('N', DONOR)
    acceptor = molecule('C=O', ACCEPTOR, 'ASN')
    ligand, protein = (acceptor, donor) if reverse else (donor, acceptor)
    rows = [r for r in detect(ligand, protein) if r['kind'] == 'hydrogen_bond']
    assert len(rows) == 1
    row = rows[0]
    assert row['type'] == ('HBAcceptor' if reverse else 'HBDonor')
    assert row['distance'] == 3.0 and row['angles']['DHA_angle'] == 180.0
    assert math.dist(row['ligand_position'], row['protein_position']) == 3.0
    assert row['ligand_atoms'][0]['number'] == (2 if reverse else 1)
    assert row['residue']['key'] == 'B:42:A'


@pytest.mark.parametrize('bad_geometry', ['distance', 'angle'])
def test_hbond_rejects_distance_or_angle_only_contacts(bad_geometry):
    positions = list(DONOR)
    acceptor = list(ACCEPTOR)
    if bad_geometry == 'distance':
        acceptor = [(x + 1, y, z) for x, y, z in acceptor]
    else:
        positions[1] = (0, 1, 0)
    assert not [r for r in detect(molecule('N', positions), molecule('C=O', acceptor, 'ASN'))
                if r['kind'] == 'hydrogen_bond']


def test_all_atom_pairs_are_retained_for_one_residue():
    # Two acceptors in the same residue; the default bit fingerprint loses one.
    positions = [(3, -0.6, 0), (4.2, -0.6, 0), (4.2, 0.6, 0), (3, 0.6, 0), (4.8, -1.5, 0), (4.8, 1.5, 0)]
    rows = detect(molecule('N', DONOR), molecule('O=CC=O', positions, 'ASN'))
    hbonds = [r for r in rows if r['kind'] == 'hydrogen_bond']
    assert len(hbonds) == 2
    assert {r['protein_atoms'][0]['number'] for r in hbonds} == {1, 4}


def test_pi_stacking_uses_ring_centroids_and_lists_all_ring_atoms():
    ring = [(1.4 * math.cos(i * math.pi / 3), 1.4 * math.sin(i * math.pi / 3), 0) for i in range(6)]
    hydrogens = [(x*1.7, y*1.7, z) for x, y, z in ring]
    ligand = molecule('c1ccccc1', ring + hydrogens)
    protein = molecule('c1ccccc1', [(x, y, z+3.5) for x, y, z in ring + hydrogens], 'PHE')
    rows = [r for r in detect(ligand, protein) if r['kind'] == 'pi_stacking']
    assert rows
    for row in rows:
        assert len(row['ligand_atoms']) == len(row['protein_atoms']) == 6
        assert row['ligand_position'] == pytest.approx([0, 0, 0], abs=1e-6)
        assert row['protein_position'] == pytest.approx([0, 0, 3.5], abs=1e-6)
        assert row['distance'] == 3.5


@pytest.mark.parametrize('reverse', [False, True])
def test_halogen_bond_uses_halogen_acceptor_distance(reverse):
    donor = molecule('CCl', [(-1.7, 0, 0), (0, 0, 0), (-2, 1, 0), (-2, -0.5, 0.8), (-2, -0.5, -0.8)])
    acceptor = molecule('C=O', [(3.6, 1.04, 0), (3, 0, 0), (4.7, 1.04, 0), (3, 1.94, 0)], 'ASN')
    ligand, protein = (acceptor, donor) if reverse else (donor, acceptor)
    rows = [r for r in detect(ligand, protein) if r['kind'] == 'halogen_bond']
    assert len(rows) == 1
    assert rows[0]['distance'] == 3.0
    assert math.dist(rows[0]['ligand_position'], rows[0]['protein_position']) == 3.0
    assert rows[0]['angles']['AXD_angle'] == 180.0


def test_salt_bridge_depends_on_formal_charge():
    donor = molecule('[NH4+]', DONOR + [(0, 0, 1)])
    acceptor = molecule('CC(=O)[O-]', [(5.7, 0, 0), (4.2, 0, 0), (4.2, 1.2, 0), (3, 0, 0),
                                     (6, 1, 0), (6, -0.5, 0.8), (6, -0.5, -0.8)], 'ASP')
    rows = [r for r in detect(donor, acceptor) if r['kind'] == 'salt_bridge']
    # Both resonance-equivalent carboxylate oxygens are ionic interaction sites.
    assert len(rows) == 2 and all(row['type'] == 'Cationic' for row in rows)
    assert min(row['distance'] for row in rows) == 3.0
    assert {row['protein_atoms'][0]['number'] for row in rows} == {3, 4}
    assert not [r for r in detect(molecule('N', DONOR), acceptor) if r['kind'] == 'salt_bridge']


def test_sdf_atom_order_survives_hydrogen_addition(tmp_path):
    mol = Chem.RemoveHs(molecule('C=O', ACCEPTOR))
    path = tmp_path/'pose.sdf'
    with Chem.SDWriter(str(path)) as writer:
        writer.write(mol)
    _, atoms, added = _load_ligand(path)
    assert added == 2
    assert [a['label'] for a in atoms[:2]] == ['C1', 'O2']
    assert atoms[1]['position'] == [3, 0, 0]
    assert all(a['index'] is None and a['number'] is None for a in atoms[2:])
    path.write_text('not an SDF')
    with pytest.raises((ValueError, OSError)):
        _load_ligand(path)


def test_preview_cache_invalidates_on_replacement_and_does_not_cache_failures(tmp_path, monkeypatch):
    receptor, pose = tmp_path/'receptor.pdb', tmp_path/'best.sdf'
    receptor.write_text('protein')
    pose.write_text('pose')
    calls = []
    def run(*args, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(returncode=0, stdout=json.dumps({'interactions': []}), stderr='')
    monkeypatch.setattr(interaction_service.subprocess, 'run', run)
    interaction_service.pose_interactions(receptor, pose)
    interaction_service.pose_interactions(receptor, pose)
    assert len(calls) == 1
    pose.write_text('new docking pose')
    interaction_service.pose_interactions(receptor, pose)
    assert len(calls) == 2 and calls[0]['env']['OMP_NUM_THREADS'] == '1'
    pose.unlink()
    with pytest.raises(FileNotFoundError):
        interaction_service.pose_interactions(receptor, pose)
    pose.write_text('failed')
    monkeypatch.setattr(interaction_service.subprocess, 'run', lambda *a, **kw: SimpleNamespace(returncode=1, stderr='bad molecule'))
    with pytest.raises(ValueError, match='분석하지 못했습니다'):
        interaction_service.pose_interactions(receptor, pose)
    monkeypatch.setattr(interaction_service.subprocess, 'run', run)
    interaction_service.pose_interactions(receptor, pose)
    assert len(calls) == 3


def test_interaction_api_authorization_pose_states_and_error_status(admin_client, monkeypatch):
    with transaction() as db:
        upload = Upload(owner_id=1, kind='pdb', filename='test.pdb', path='/unused', size=0, sha256='a'*64)
        db.add(upload); db.flush()
        receptor = Receptor(owner_id=1, upload_id=upload.id, name='test', status='ready')
        db.add(receptor); db.flush()
        task = Task(owner_id=1, receptor_id=receptor.id, kind='screen', name='test', status='completed')
        db.add(task); db.flush()
        compound = Compound(task_id=task.id, row_number=1, cid='one', smiles='N', status='succeeded', affinity=-4)
        db.add(compound); db.flush()
        task_id, compound_id = task.id, compound.id
    path = f'/api/jobs/{task_id}/compounds/{compound_id}/interactions'
    calls = []
    def analyze(receptor, pose):
        calls.append((receptor, pose))
        return dict(engine='ProLIF', interactions=[], warnings=[])
    monkeypatch.setattr(interaction_service, 'pose_interactions', analyze)
    response = admin_client.get(path)
    assert response.status_code == 200 and response.json()['engine'] == 'ProLIF'
    assert calls[0][1] == storage.compound_dir(1, task_id, compound_id)/'best.sdf'
    for status in ('pending', 'running', 'failed'):
        with transaction() as db:
            db.get(Compound, compound_id).status = status
        assert admin_client.get(path).status_code == 404
    with transaction() as db:
        db.get(Compound, compound_id).status = 'partial'
    assert admin_client.get(path).status_code == 200
    def missing(*args):
        raise FileNotFoundError()
    monkeypatch.setattr(interaction_service, 'pose_interactions', missing)
    assert admin_client.get(path).status_code == 404
    def busy(*args):
        raise interaction_service.AnalysisBusy('busy')
    monkeypatch.setattr(interaction_service, 'pose_interactions', busy)
    response = admin_client.get(path)
    assert response.status_code == 503 and response.headers['Retry-After'] == '3'
    with transaction() as db:
        db.add(User(username='other', name='other', password_hash=password_hash('OtherPass123!'), status='approved'))
    admin_client.post('/api/auth/login', json={'username': 'other', 'password': 'OtherPass123!'})
    assert admin_client.get(path).status_code == 404
    admin_client.post('/api/auth/logout')
    assert admin_client.get(path).status_code == 401


def test_pose_replaced_during_analysis_cannot_return_stale_contacts(tmp_path, monkeypatch):
    receptor, pose = tmp_path/'receptor.pdb', tmp_path/'pose.sdf'
    receptor.write_text('protein')
    pose.write_text('old pose')
    def run(*args, **kwargs):
        pose.write_text('new pose after retry')
        return SimpleNamespace(returncode=0, stdout=json.dumps({'interactions': []}), stderr='')
    monkeypatch.setattr(interaction_service.subprocess, 'run', run)
    with pytest.raises(interaction_service.AnalysisBusy, match='변경'):
        interaction_service.pose_interactions(receptor, pose)
