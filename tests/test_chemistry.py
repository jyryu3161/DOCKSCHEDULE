from pathlib import Path
import pytest
from dockschedule.chemistry import normalize_smiles, check_pdbqt


def test_salt_normalization_preserves_charge_and_stereochemistry():
    from rdkit import Chem
    _, normalized, removed = normalize_smiles('C[C@H](O)C(=O)[O-].[Na+]')
    assert '@' in normalized and '[O-]' in normalized
    assert removed == ['[Na+]']
    assert Chem.GetFormalCharge(Chem.MolFromSmiles(normalized)) == -1


def test_ambiguous_mixture_and_invalid_smiles_rejected():
    with pytest.raises(ValueError):
        normalize_smiles('CCO.COC')
    with pytest.raises(ValueError):
        normalize_smiles('not-a-smiles')
    with pytest.raises(ValueError):
        normalize_smiles('CCO.[Na+]',False)


@pytest.mark.integration
def test_real_pdb_repair_qvina_and_stereochemical_sdf(tmp_path,monkeypatch):
    monkeypatch.setenv('OPENMM_CPU_THREADS','2')
    from dockschedule.chemistry import prepare_receptor,dock_compound
    from rdkit import Chem
    from rdkit.Chem import rdMolDescriptors
    report=prepare_receptor(Path('tests/fixtures/1L83.pdb'),tmp_path/'receptor',dict(model=1,chains=['A'],keep_heterogens=[],ph=7.4))
    assert {'A:163:','A:164:'} <= set(report['report']['modeled_residues'])
    assert sum(r.get('modeled',False) for r in report['structure']['residues']) == 2
    receptor=tmp_path/'receptor/receptor.pdbqt'
    assert 'ROOT' not in receptor.read_text()
    params=dict(seed=42,conformers=2,exhaustiveness=2,center=[26.929,6.158,4.216],size=[20,20,20],timeout=120)
    smiles='C[C@H](O)c1ccccc1'
    result=dock_compound(smiles,receptor,tmp_path/'ligand',params,2,Path('tools/qvina2.1').resolve())
    assert result['affinity'] < 0
    pose=(tmp_path/'ligand/best.pdbqt').read_text()
    assert pose.count('REMARK VINA RESULT:') == 1
    output=next(Chem.SDMolSupplier(str(tmp_path/'ligand/best.sdf')))
    assert output is not None
    assert Chem.MolToSmiles(Chem.RemoveHs(output),isomericSmiles=True) == Chem.MolToSmiles(Chem.MolFromSmiles(smiles),isomericSmiles=True)
    assert len(result['details']['conformers']) >= 1
    assert result['affinity'] == min(c['affinity'] for c in result['details']['conformers'] if c['status']=='succeeded')


@pytest.mark.integration
def test_modres_polymer_is_repaired_using_pdb_mapping(tmp_path,monkeypatch):
    monkeypatch.setenv('OPENMM_CPU_THREADS','2')
    from dockschedule.chemistry import prepare_receptor
    lines=Path('tests/fixtures/1L83.pdb').read_text().splitlines()
    first=next(l for l in lines if l.startswith('ATOM  '))
    modified=[]
    for line in lines:
        if line.startswith('ATOM  ') and line[21:27]==first[21:27]:
            line='HETATM'+line[6:17]+'ZZZ'+line[20:]
        modified.append(line)
    header=list(' '*80)
    header[:6]='MODRES';header[12:15]='ZZZ';header[16]='A';header[18:22]=first[22:26];header[24:27]=first[17:20]
    source=tmp_path/'modified.pdb'
    source.write_text(''.join(header)+'\n'+'\n'.join(modified))
    result=prepare_receptor(source,tmp_path/'prepared',dict(model=1,chains=['A'],keep_heterogens=[],ph=7.4))
    assert any(r['original']=='ZZZ' and r['replacement']==first[17:20] for r in result['report']['replacements'])
    assert result['structure']['residues'][0]['name']==first[17:20]
