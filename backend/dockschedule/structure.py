import math
from collections import OrderedDict

AA = dict(zip('ALA ARG ASN ASP CYS GLN GLU GLY HIS ILE LEU LYS MET PHE PRO SER THR TRP TYR VAL'.split(), 'ARNDCQEGHILKMFPSTWYV'))
AA.update(MSE='M', HID='H', HIE='H', HIP='H', CYX='C')
WATER = {'HOH', 'WAT', 'DOD'}
METALS = {'ZN', 'MG', 'MN', 'CA', 'FE', 'CU', 'NA', 'K', 'CO', 'NI', 'CD'}
COFACTORS = {'HEM', 'HEC', 'FAD', 'FMN', 'NAD', 'NAP', 'NDP', 'SAM', 'SAH', 'PLP', 'COA', 'ATP', 'ADP'}


def residue_key(chain, number, insertion=''):
    return f'{chain}:{number}:{insertion}'


def inspect_pdb(text, model=None):
    residues = OrderedDict()
    current, models = 1, set()
    seqres, modified_names = {}, {}
    for line in text.splitlines():
        if line.startswith('SEQRES'):
            seqres.setdefault(line[11:12].strip(), []).extend(line[19:70].split())
        elif line.startswith('MODRES') and line[24:27].strip() in AA:
            modified_names.setdefault(line[16:17].strip(), set()).add(line[12:15].strip())
    count = 0
    selected_model = model
    for line in text.splitlines():
        if line.startswith('MODEL '):
            try:
                current = int(line[10:14])
            except ValueError:
                raise ValueError('PDB MODEL 번호가 올바르지 않습니다.')
        if not line.startswith(('ATOM  ', 'HETATM')):
            continue
        models.add(current)
        if selected_model is None:
            selected_model = current
        if current != selected_model:
            continue
        if len(line) < 54:
            raise ValueError('좌표가 잘린 PDB 원자 기록이 있습니다.')
        try:
            number, coord = int(line[22:26]), [float(line[i:i+8]) for i in (30, 38, 46)]
        except ValueError:
            raise ValueError('PDB 잔기 번호 또는 좌표가 올바르지 않습니다.')
        if not all(math.isfinite(v) for v in coord):
            raise ValueError('PDB 좌표에 NaN 또는 무한대가 있습니다.')
        chain, ins, name = line[21:22].strip(), line[26:27].strip(), line[17:20].strip()
        key = residue_key(chain, number, ins)
        if key not in residues:
            polymer = (line.startswith('ATOM  ') or name in AA or name in seqres.get(chain, []) or name in modified_names.get(chain, set()))
            category = 'water' if name in WATER else 'metal' if name in METALS else 'cofactor' if name in COFACTORS else 'protein' if polymer else 'other'
            residues[key] = dict(key=key, chain=chain, number=number, insertion=ins, name=name,
                                  letter=AA.get(name, 'X'), category=category, heavy_atoms=0, center=[0., 0., 0.])
        element = line[76:78].strip() or line[12:16].strip().lstrip('0123456789')[:1]
        if element not in ('H', 'D') and line[16:17] in (' ', 'A'):
            r = residues[key]
            r['heavy_atoms'] += 1
            r['center'] = [a+b for a, b in zip(r['center'], coord)]
        count += 1
    if count == 0:
        raise ValueError('선택한 model에 PDB 원자 기록이 없습니다.')
    for r in residues.values():
        if r['heavy_atoms']:
            r['center'] = [v/r['heavy_atoms'] for v in r['center']]
    return dict(models=sorted(models), model=selected_model, residues=list(residues.values()),
                chains=sorted({r['chain'] for r in residues.values() if r['category'] == 'protein'}),
                seqres=seqres, atom_count=count)


def selected_pdb(text, model, chains, keep_heterogens):
    """Keep SEQRES; select one model and explicit chains/heterogens."""
    current = 1
    protein, hetero = [], []
    polymer_keys = {r['key'] for r in inspect_pdb(text, model)['residues'] if r['category'] == 'protein'}
    for line in text.splitlines():
        if line.startswith('MODEL '):
            current = int(line[10:14])
        if line.startswith('SEQRES') and line[11:12].strip() in chains:
            protein.append(line)
        if line.startswith('MODRES') and line[16:17].strip() in chains:
            protein.append(line)
        if not line.startswith(('ATOM  ', 'HETATM')) or current != model:
            continue
        chain = line[21:22].strip()
        if chain not in chains:
            continue
        key = residue_key(chain, int(line[22:26]), line[26:27].strip())
        if key in polymer_keys:
            protein.append(line)
        elif key in keep_heterogens:
            hetero.append(line)
    # Preserve one coherent alternate location per retained heterogen, preferring
    # greatest occupancy and then A. Blank-location atoms belong to every conformer.
    occupancy = {}
    for line in hetero:
        alt = line[16:17].strip()
        if alt:
            key = residue_key(line[21:22].strip(), int(line[22:26]), line[26:27].strip())
            weights = occupancy.setdefault(key, {})
            weights[alt] = weights.get(alt, 0) + float(line[54:60].strip() or 0)
    chosen = {key: min(weights, key=lambda alt: (-weights[alt], alt != 'A', alt)) for key, weights in occupancy.items()}
    retained = []
    for line in hetero:
        key = residue_key(line[21:22].strip(), int(line[22:26]), line[26:27].strip())
        alt = line[16:17].strip()
        if not alt or alt == chosen.get(key):
            retained.append(line[:16]+' '+line[17:])
    return '\n'.join(protein) + '\nEND\n', retained
