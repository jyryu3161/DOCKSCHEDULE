"""Measure the real preparation/docking path on 50 diverse NCI example molecules.

The NCI sample ships with RDKit. This is a throughput probe, not affinity validation.
Run: uv run python scripts/benchmark.py --count 50 --output test-results/benchmark
"""
import argparse
import json
import os
import shutil
import time
from pathlib import Path
os.environ.setdefault('OPENMM_CPU_THREADS','2')
os.environ.setdefault('OPENBLAS_NUM_THREADS','1')
os.environ.setdefault('OMP_NUM_THREADS','1')
from rdkit import Chem, RDConfig
from rdkit.Chem import Descriptors
from dockschedule.chemistry import prepare_receptor, dock_compound

parser=argparse.ArgumentParser()
parser.add_argument('--count',type=int,default=50)
parser.add_argument('--output',type=Path,default=Path('test-results/benchmark'))
args=parser.parse_args()
root=args.output.resolve();root.mkdir(parents=True,exist_ok=True)
available=sorted(os.sched_getaffinity(0))
os.sched_setaffinity(0,available[:8])
prep_start=time.monotonic()
prepare_receptor(Path('tests/fixtures/1L83.pdb'),root/'receptor',dict(model=1,chains=['A'],keep_heterogens=[],ph=7.4))
preparation_seconds=time.monotonic()-prep_start
library=[]
for line in (Path(RDConfig.RDDataDir)/'NCI/first_5K.smi').read_text().splitlines():
    fields=line.split()
    if not fields:continue
    mol=Chem.MolFromSmiles(fields[0])
    if mol is None or '.' in fields[0] or not 8<=mol.GetNumHeavyAtoms()<=35 or Descriptors.NumRotatableBonds(mol)>8:
        continue
    if any(a.GetAtomicNum() not in (1,6,7,8,9,15,16,17,35,53) for a in mol.GetAtoms()):continue
    library.append((fields[1] if len(fields)>1 else str(len(library)),fields[0]))
    if len(library)==args.count:break
report=dict(source='RDKit bundled NCI first_5K.smi; 8–35 heavy atoms, <=8 rotatable bonds',
            receptor='1L83',preparation_seconds=preparation_seconds,compounds=len(library),runs=[])
for cpu in [1,2,4,8]:
    os.sched_setaffinity(0,available[:cpu])
    runs=[]
    for cid,smiles in library:
        start=time.monotonic()
        directory=root/f'cpu-{cpu}'/cid
        parameters=dict(seed=42,conformers=1,exhaustiveness=8,center=[26.929,6.158,4.216],size=[20,20,20],timeout=120)
        try:
            result=dock_compound(smiles,root/'receptor/receptor.pdbqt',directory,parameters,cpu,Path('tools/qvina2.1').resolve())
            row=dict(cid=cid,smiles=smiles,status=result['status'],affinity=result['affinity'])
        except Exception as e:
            row=dict(cid=cid,smiles=smiles,status='failed',error=str(e))
        row['seconds']=time.monotonic()-start
        row['artifact_bytes']=sum(p.stat().st_size for p in directory.rglob('*') if p.is_file())
        runs.append(row)
        print(json.dumps(dict(cpu=cpu,finished=len(runs),total=len(library),**row)),flush=True)
    report['runs'].append(dict(cpu=cpu,results=runs,total_seconds=sum(r['seconds'] for r in runs)))
    (root/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
os.sched_setaffinity(0,available)
print('Report:',root/'report.json')
