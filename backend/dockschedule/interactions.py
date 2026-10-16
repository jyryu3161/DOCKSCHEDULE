"""Atom-resolved ProLIF analysis of the prepared receptor and Meeko pose SDF.

Run in the bounded preview subprocess, never import chemistry in the API.
All public atom indices refer to the original viewer files, not ProLIF residues.
"""
import io
import json
import math
from pathlib import Path

from .structure import AA, residue_key


TYPES = {
    'HBDonor': ('hydrogen_bond', 'donor (수소 제공)'),
    'HBAcceptor': ('hydrogen_bond', 'acceptor (수소 수용)'),
    'Hydrophobic': ('hydrophobic', ''),
    'Cationic': ('salt_bridge', '양이온'),
    'Anionic': ('salt_bridge', '음이온'),
    'PiStacking': ('pi_stacking', '방향족 고리'),
    'CationPi': ('cation_pi', '양이온'),
    'PiCation': ('cation_pi', '방향족 고리'),
    'XBDonor': ('halogen_bond', 'donor (할로젠 제공)'),
    'XBAcceptor': ('halogen_bond', 'acceptor (할로젠 수용)'),
}


def _position(point):
    values = [float(v) for v in point]
    if not all(math.isfinite(v) for v in values):
        raise ValueError('유효하지 않은 원자 좌표입니다.')
    return values


def _load_protein(path):
    import MDAnalysis as mda
    import numpy as np
    import prolif as plf
    from openmm.app import PDBFile

    text = path.read_text()
    universe = mda.Universe(io.StringIO(text), format='PDB')
    selected = universe.atoms[np.isin(universe.atoms.resnames, list(AA))]
    if not len(selected) or 'H' not in selected.elements:
        raise ValueError('수소가 포함된 전처리 단백질이 필요합니다.')
    if len(set(selected.ids)) != len(selected):
        raise ValueError('단백질 원자 serial 번호가 중복됩니다.')

    # Use OpenMM's residue-template connectivity, including disulfides. Distance
    # guessing can create false covalent bonds between nearby side chains.
    pdb = PDBFile(io.StringIO(text))
    by_serial = {int(atom.id): i for i, atom in enumerate(selected)}
    bonds = [(by_serial[int(a.id)], by_serial[int(b.id)]) for a, b in pdb.topology.bonds()
             if int(a.id) in by_serial and int(b.id) in by_serial]
    protein = mda.Merge(selected)
    protein.add_TopologyAttr('bonds', bonds)
    # ProLIF ResidueId omits insertion codes. Give every residue a unique internal
    # number, keeping original chain/number/insertion in the separate output map.
    protein.residues.resids = np.arange(1, len(protein.residues) + 1)
    mol = protein.atoms.convert_to.rdkit()

    residues = {}
    for residue in selected.residues:
        first = residue.atoms[0]
        chain = str(first.chainID).strip()
        insertion = str(residue.icode).strip()
        key = residue_key(chain, int(residue.resid), insertion)
        residues[residue.ix] = dict(key=key, chain=chain, number=int(residue.resid),
                                    insertion=insertion, name=str(residue.resname),
                                    atom_indices=[int(i) for i in residue.atoms.indices])
    atoms, atom_residues = [], []
    for atom in mol.GetAtoms():
        source = selected[atom.GetIntProp('_MDAnalysis_index')]
        atoms.append(dict(index=int(source.index), number=int(source.id), label=str(source.name),
                          element=atom.GetSymbol(), position=_position(source.position)))
        atom_residues.append(residues[source.resindex])
    excluded = len(universe.residues) - len(selected.residues)
    return plf.Molecule(mol), atoms, atom_residues, excluded


def _load_ligand(path):
    import prolif as plf
    from rdkit import Chem

    supplier = Chem.SDMolSupplier(str(path), removeHs=False)
    if len(supplier) != 1 or (mol := supplier[0]) is None or not mol.GetNumConformers():
        raise ValueError('하나의 유효한 3D pose SDF가 필요합니다.')
    original_count = mol.GetNumAtoms()
    # Meeko writes explicit H. For older SDFs, append missing H without moving or
    # reordering existing atoms; never claim appended H has an original SDF index.
    mol = Chem.AddHs(mol, addCoords=True)
    positions = mol.GetConformer().GetPositions()
    atoms = [dict(index=i if i < original_count else None,
                  number=i+1 if i < original_count else None,
                  label=f'{atom.GetSymbol()}{i+1}' if i < original_count else f'H(추가 {i-original_count+1})',
                  element=atom.GetSymbol(), position=_position(positions[i]))
             for i, atom in enumerate(mol.GetAtoms())]
    return plf.Molecule.from_rdkit(mol), atoms, mol.GetNumAtoms() - original_count


def _anchor(atoms, interaction, side):
    # Metadata also includes angle-defining neighbours. Endpoints must match the
    # measured distance: D...A for H-bonds, X...A for halogen bonds, ring centroid
    # for pi interactions. A centroid of D and H would be scientifically wrong.
    ring = interaction == 'PiStacking' or (interaction == 'CationPi' and side == 'protein') or (interaction == 'PiCation' and side == 'ligand')
    if ring:
        return [sum(a['position'][axis] for a in atoms)/len(atoms) for axis in range(3)]
    index = 1 if (interaction == 'XBDonor' and side == 'ligand') or (interaction == 'XBAcceptor' and side == 'protein') else 0
    return atoms[index]['position']


def interaction_records(ligand, protein, ligand_atoms, protein_atoms, atom_residues):
    import prolif as plf

    fp = plf.Fingerprint(list(TYPES), count=True)
    fingerprint = fp.generate(ligand, protein, metadata=True)
    rows = []
    seen = set()
    for interactions in fingerprint.values():
        for name, matches in interactions.items():
            for match in matches:
                li = tuple(int(i) for i in match['parent_indices']['ligand'])
                pi = tuple(int(i) for i in match['parent_indices']['protein'])
                key = name, li, pi
                if key in seen:
                    continue
                seen.add(key)
                la, pa = [ligand_atoms[i] for i in li], [protein_atoms[i] for i in pi]
                rows.append(dict(kind=TYPES[name][0], type=name, role=TYPES[name][1],
                                 residue=atom_residues[pi[0]], ligand_atoms=la, protein_atoms=pa,
                                 ligand_position=_anchor(la, name, 'ligand'),
                                 protein_position=_anchor(pa, name, 'protein'),
                                 distance=round(float(match['distance']), 3),
                                 angles={key: round(float(value), 2) for key, value in match.items() if 'angle' in key}))
    order = list(TYPES)
    rows.sort(key=lambda r: (order.index(r['type']), r['residue']['chain'], r['residue']['number'],
                             r['residue']['insertion'], r['distance'], tuple(a['label'] for a in r['ligand_atoms'])))
    for index, row in enumerate(rows):
        row['id'] = f'interaction-{index+1}'
    return rows


def analyze_pose(receptor: Path, pose: Path, prepared=None):
    import prolif as plf

    protein, protein_atoms, residues, excluded = prepared if prepared is not None else _load_protein(receptor)
    ligand, ligand_atoms, added = _load_ligand(pose)
    warnings = ['전처리된 단백질의 아미노산 잔기와 선택한 pose만 분석합니다. 물 매개 결합, 금속 배위 및 보조인자 상호작용은 포함하지 않습니다.']
    if excluded:
        warnings.append(f'물·이온·보조인자 등 비단백질 잔기 {excluded}개를 분석에서 제외했습니다.')
    if added:
        warnings.append(f'SDF에서 누락된 수소 {added}개의 좌표를 생성했습니다. 추가 수소는 원본 SDF 번호가 없으며 수소결합 판정에 영향을 줄 수 있습니다.')
    return dict(engine='ProLIF', engine_version=plf.__version__, schema_version=1,
                interactions=interaction_records(ligand, protein, ligand_atoms, protein_atoms, residues),
                warnings=warnings)


if __name__ == '__main__':
    import os
    import sys

    if hasattr(os, 'sched_setaffinity'):
        os.sched_setaffinity(0, {max(os.sched_getaffinity(0))})
    if hasattr(os, 'nice'):
        os.nice(10)
    print(json.dumps(analyze_pose(Path(sys.argv[1]), Path(sys.argv[2])), ensure_ascii=False, allow_nan=False))
