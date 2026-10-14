"""Real CPU chemistry. Import only inside CPU-constrained calculation workers."""
import hashlib
import io
import json
import math
import shutil
import subprocess
from pathlib import Path
from .structure import inspect_pdb, selected_pdb, residue_key

QVINA_SHA256 = 'bc1f908869181d17b48c9a9b4c2a28cce5264ccf3053e15bce32bb5baf83b43d'
QVINA_TYPES = set('H HD HS C A N NA NS O OA OS F Mg MG P SA S Cl CL Ca CA Mn MN Fe FE Zn ZN Br BR I'.split())


def check_pdbqt(text):
    atoms = [l for l in text.splitlines() if l.startswith(('ATOM  ', 'HETATM'))]
    if not atoms:
        raise ValueError('PDBQT에 원자가 없습니다.')
    unknown = set()
    for line in atoms:
        t = line.split()[-1]
        if t not in QVINA_TYPES:
            unknown.add(t)
        charge = float(line[70:76])
        if not math.isfinite(charge):
            raise ValueError('PDBQT에 유효하지 않은 전하가 있습니다.')
    if unknown:
        raise ValueError('QuickVina 2.1이 지원하지 않는 원자형: ' + ', '.join(sorted(unknown)))


def prepare_receptor(source: Path, out: Path, options: dict):
    from pdbfixer import PDBFixer
    from openmm import Platform, unit
    from openmm.app import PDBFile
    from openbabel import openbabel as ob
    import numpy as np
    from scipy.spatial import cKDTree

    out.mkdir(parents=True, exist_ok=True)
    text = source.read_text()
    original = inspect_pdb(text, options['model'])
    protein, hetero = selected_pdb(text, options['model'], options['chains'], options.get('keep_heterogens', []))
    fixer = PDBFixer(pdbfile=io.StringIO(protein), platform=Platform.getPlatformByName('CPU'))
    if fixer.topology.getNumAtoms() == 0:
        raise ValueError('선택한 chain에 지원하는 단백질 잔기가 없습니다.')
    fixer.findNonstandardResidues()
    replacements = [dict(chain=r.chain.id, number=r.id, original=r.name, replacement=n) for r, n in fixer.nonstandardResidues]
    fixer.replaceNonstandardResidues()
    fixer.findMissingResidues()
    original_chains = [[dict(number=r.id, insertion=r.insertionCode, name=r.name) for r in c.residues()] for c in fixer.topology.chains()]
    missing = fixer.missingResidues.copy()
    fixer.findMissingAtoms()
    atom_repairs = sum(len(v) for v in fixer.missingAtoms.values())
    fixer.addMissingAtoms(seed=options.get('seed', 42))

    # Restore observed residue identifiers, and assign unambiguous IDs to modeled residues.
    added = []
    for chain_index, chain in enumerate(fixer.topology.chains()):
        old = original_chains[chain_index]
        sequence = []
        used = {(int(r['number']), r['insertion']) for r in old}
        for i in range(len(old)+1):
            block = missing.get((chain_index, i), [])
            for offset, name in enumerate(block):
                if i == 0:
                    number = int(old[0]['number']) - len(block) + offset
                else:
                    number = int(old[i-1]['number']) + offset + 1
                insertion = ''
                if (number, insertion) in used or (i < len(old) and number >= int(old[i]['number'])):
                    number = int(old[i-1]['number']) if i else int(old[0]['number'])-1
                    insertion = next((x for x in 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789' if (number, x) not in used), None)
                    if insertion is None:
                        raise ValueError('복구 잔기에 고유 PDB 번호를 배정할 수 없습니다.')
                used.add((number, insertion))
                sequence.append((str(number), insertion, True))
            if i < len(old):
                sequence.append((old[i]['number'], old[i]['insertion'], False))
        residues = list(chain.residues())
        if len(sequence) != len(residues):
            raise ValueError('복구 전후 잔기 대응 관계가 일치하지 않습니다.')
        for res, (number, insertion, modeled) in zip(residues, sequence):
            res.id, res.insertionCode = number, insertion
            if modeled:
                added.append(residue_key(chain.id.strip(), int(number), insertion))
    fixer.addMissingHydrogens(pH=options.get('ph', 7.4))
    pos = np.asarray(fixer.positions.value_in_unit(unit.angstrom))
    if not np.isfinite(pos).all():
        raise ValueError('복구 구조의 좌표가 유효하지 않습니다.')
    heavy = [a.index for a in fixer.topology.atoms() if a.element is not None and a.element.symbol != 'H']
    if cKDTree(pos[heavy]).query_pairs(0.45):
        raise ValueError('복구 구조에 심한 원자 겹침이 있습니다. 해당 PDB를 확인하세요.')
    for a, b in fixer.topology.bonds():
        distance = float(np.linalg.norm(pos[a.index]-pos[b.index]))
        if not 0.5 < distance < 2.8:
            raise ValueError(f'전처리 구조의 결합 길이가 비정상입니다: {a.residue.chain.id}:{a.residue.id} {a.name}–{b.name}, {distance:.2f} Å. PDB 서열과 결손 구간을 확인하세요.')
    buf = io.StringIO()
    PDBFile.writeFile(fixer.topology, fixer.positions, buf, keepIds=True)
    fixed = '\n'.join(l for l in buf.getvalue().splitlines() if not l.startswith('END'))
    if hetero:
        # Serial IDs must remain unique after hydrogen / residue additions.
        serial = max(int(l[6:11]) for l in fixed.splitlines() if l.startswith(('ATOM  ', 'HETATM')))
        renumbered = []
        for line in hetero:
            serial += 1
            if serial > 99999:
                raise ValueError('PDB 원자 수 한도를 초과했습니다.')
            renumbered.append(line[:6] + f'{serial:5d}' + line[11:])
        fixed += '\n' + '\n'.join(renumbered)
    fixed += '\nEND\n'
    (out/'receptor.pdb').write_text(fixed)
    conv = ob.OBConversion()
    conv.SetInAndOutFormats('pdb', 'pdbqt')
    conv.AddOption('r', ob.OBConversion.OUTOPTIONS)  # rigid receptor, no torsion tree
    molecule = ob.OBMol()
    if not conv.ReadString(molecule, fixed):
        raise ValueError('전처리 PDB를 읽지 못했습니다.')
    if not ob.OBChargeModel.FindType('gasteiger').ComputeCharges(molecule):
        raise ValueError('유지한 성분의 Gasteiger 전하를 계산할 수 없습니다.')
    pdbqt = conv.WriteString(molecule)
    check_pdbqt(pdbqt)
    in_heavy = sum(a.GetAtomicNum() > 1 for a in ob.OBMolAtomIter(molecule))
    out_heavy = sum(l.split()[-1] not in ('H', 'HD', 'HS') for l in pdbqt.splitlines() if l.startswith(('ATOM  ', 'HETATM')))
    if in_heavy != out_heavy:
        raise ValueError('PDBQT 변환 중 원자가 손실되었습니다.')
    (out/'receptor.pdbqt').write_text(pdbqt)
    structure = inspect_pdb(fixed)
    for residue in structure['residues']:
        residue['modeled'] = residue['key'] in added
    report = dict(modeled_residues=added, repaired_atoms=atom_repairs, replacements=replacements,
                  ph=options.get('ph', 7.4), kept_heterogens=options.get('keep_heterogens', []),
                  sequence_source='SEQRES' if original['seqres'] else 'ATOM',
                  warnings=[] if original['seqres'] else ['SEQRES가 없어 잔기 전체의 결손 여부와 서열은 확정할 수 없습니다. 존재하는 잔기의 누락 원자를 보완했습니다.'])
    if added:
        report['warnings'].append('표시된 복구 잔기는 계산으로 생성한 좌표입니다. 결합 부위에 포함되면 결과 해석에 주의하세요.')
    (out/'preparation.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    return dict(report=report, structure=structure)


def normalize_smiles(smiles, strip_salts=True):
    from rdkit import Chem
    mol = Chem.MolFromSmiles(smiles)
    if mol is None or mol.GetNumAtoms() == 0:
        raise ValueError('유효하지 않은 SMILES입니다.')
    fragments = list(Chem.GetMolFrags(mol, asMols=True, sanitizeFrags=True))
    removed = []
    if len(fragments) > 1:
        if not strip_salts:
            raise ValueError('분리된 여러 성분이 있습니다. Salt 제거를 선택하거나 단일 분자 SMILES를 사용하세요.')
        organic = sorted([m for m in fragments if any(a.GetAtomicNum() == 6 for a in m.GetAtoms())], key=lambda m: m.GetNumHeavyAtoms(), reverse=True)
        if not organic or (len(organic) > 1 and organic[0].GetNumHeavyAtoms() == organic[1].GetNumHeavyAtoms()):
            raise ValueError('혼합물의 주성분을 명확히 선택할 수 없습니다.')
        mol = organic[0]
        removed = [Chem.MolToSmiles(m) for m in fragments if m is not mol]
    if mol.GetNumHeavyAtoms() > 200:
        raise ValueError('작은 분자 docking은 heavy atom 200개 이하를 지원합니다.')
    return mol, Chem.MolToSmiles(mol, isomericSmiles=True), removed


def dock_compound(smiles, receptor, out, parameters, cpus, binary):
    from rdkit import Chem, rdBase
    from rdkit.Chem import AllChem
    from meeko import MoleculePreparation, PDBQTWriterLegacy, PDBQTMolecule, RDKitMolCreate
    import meeko

    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    mol, normalized, removed = normalize_smiles(smiles, parameters.get('strip_salts', True))
    mol = Chem.AddHs(mol)
    opts = AllChem.ETKDGv3()
    opts.randomSeed = parameters['seed']
    opts.numThreads = 1
    opts.pruneRmsThresh = 0.5
    ids = list(AllChem.EmbedMultipleConfs(mol, numConfs=parameters['conformers'], params=opts))
    if not ids:
        raise ValueError('3D conformer 생성에 실패했습니다.')
    if AllChem.MMFFHasAllMoleculeParams(mol):
        ff = 'MMFF94'
        optimize = lambda cid: AllChem.MMFFOptimizeMolecule(mol, confId=cid, maxIters=2000)
        energy = lambda cid: AllChem.MMFFGetMoleculeForceField(mol, AllChem.MMFFGetMoleculeProperties(mol), confId=cid).CalcEnergy()
    elif AllChem.UFFHasAllMoleculeParams(mol):
        ff = 'UFF'
        optimize = lambda cid: AllChem.UFFOptimizeMolecule(mol, confId=cid, maxIters=2000)
        energy = lambda cid: AllChem.UFFGetMoleculeForceField(mol, confId=cid).CalcEnergy()
    else:
        raise ValueError('MMFF와 UFF가 이 분자의 모든 원자를 지원하지 않습니다.')
    records, best, best_text = [], None, None
    for cid in ids:
        record = dict(conformer=cid, force_field=ff)
        try:
            if optimize(cid) != 0:
                raise ValueError('에너지 최소화가 수렴하지 않았습니다.')
            record['minimization_energy'] = energy(cid)
            if not math.isfinite(record['minimization_energy']):
                raise ValueError('최소화 에너지가 유효하지 않습니다.')
            one = Chem.Mol(mol)
            one.RemoveAllConformers()
            one.AddConformer(Chem.Conformer(mol.GetConformer(cid)), assignId=True)
            prep = MoleculePreparation(rigid_macrocycles=True)
            setup = prep.prepare(one)[0]
            ligand, ok, error = PDBQTWriterLegacy.write_string(setup)
            if not ok:
                raise ValueError(error)
            check_pdbqt(ligand)
            ligand_file, pose_file = out/'input.pdbqt', out/'candidate.pdbqt'
            ligand_file.write_text(ligand)
            args = [str(binary), '--receptor', str(receptor), '--ligand', str(ligand_file),
                    '--out', str(pose_file), '--cpu', str(cpus), '--seed', str(parameters['seed']),
                    '--exhaustiveness', str(parameters['exhaustiveness']), '--num_modes', '1']
            for axis, value in zip('xyz', parameters['center']):
                args.extend([f'--center_{axis}', str(value)])
            for axis, value in zip('xyz', parameters['size']):
                args.extend([f'--size_{axis}', str(value)])
            proc = subprocess.run(args, capture_output=True, text=True, timeout=parameters.get('timeout', 600))
            if proc.returncode:
                raise ValueError('QuickVina: ' + (proc.stderr or proc.stdout)[-1500:])
            pose = pose_file.read_text()
            scores = [float(l.split()[3]) for l in pose.splitlines() if l.startswith('REMARK VINA RESULT:')]
            if len(scores) != 1 or not math.isfinite(scores[0]):
                raise ValueError('유효한 docking pose가 생성되지 않았습니다.')
            record.update(affinity=scores[0], status='succeeded')
            if best is None or scores[0] < best['affinity']:
                best, best_text = record, pose
                with Chem.SDWriter(str(out/'input-best.sdf')) as writer:
                    writer.write(one)
        except (ValueError, RuntimeError, subprocess.TimeoutExpired) as e:
            record.update(status='failed', error=str(e))
        records.append(record)
    if best is None:
        raise ValueError('; '.join(r.get('error', '') for r in records))
    (out/'best.pdbqt').write_text(best_text)
    parsed = PDBQTMolecule.from_file(str(out/'best.pdbqt'), skip_typing=True)
    sdf, failures = RDKitMolCreate.write_sd_string(parsed)
    if failures or not sdf:
        raise ValueError('결합 차수를 보존한 SDF 생성에 실패했습니다.')
    (out/'best.sdf').write_text(sdf)
    for path in (out/'input.pdbqt', out/'candidate.pdbqt'):
        path.unlink(missing_ok=True)
    details = dict(conformers=records, requested=parameters['conformers'], generated=len(ids),
                   best_conformer=best['conformer'], removed_fragments=removed,
                   rdkit_version=rdBase.rdkitVersion, meeko_version=meeko.__version__,
                   qvina_sha256=QVINA_SHA256, cpu=cpus, parameters=parameters)
    return dict(normalized_smiles=normalized, affinity=best['affinity'], details=details,
                status='partial' if len(ids) < parameters['conformers'] or any(r['status'] == 'failed' for r in records) else 'succeeded')
