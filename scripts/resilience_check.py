"""Verify real worker restart, checkpoints, and cancellation on the local deployment."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import httpx
from dotenv import dotenv_values

p=argparse.ArgumentParser();p.add_argument('--url',default='http://127.0.0.1:8890');args=p.parse_args()
client=httpx.Client(base_url=args.url,headers={'X-DS-Request':'1'},timeout=60)
def call(method,path,**kw):
    r=client.request(method,'/api'+path,**kw);r.raise_for_status();return r.json()
password=os.environ.get('ADMIN_PASSWORD') or dotenv_values('.env')['ADMIN_PASSWORD']
call('POST','/auth/login',json={'username':'admin','password':password})
receptor=next(r for r in call('GET','/receptors') if r['status']=='ready')
settings=call('GET','/settings')['values']
call('PUT','/admin/settings',json={**settings,'default_cpus':2})
slow='S(SC1=NC2=CC=CC=C2S1)C3=NC4=C(S3)C=CC=C4'
def submit(name):
    text='CID,SMILES\nfirst,c1ccccc1\n'+''.join(f'{n},{slow}\n' for n in range(4))
    lib=call('POST','/uploads?kind=library',files={'file':('resume.csv',text.encode())})
    return call('POST','/jobs',json=dict(name=name,receptor_id=receptor['id'],library_id=lib['id'],
                library=dict(delimiter=',',encoding='utf-8-sig',header=True,cid_column='CID',smiles_column='SMILES'),
                center=[26.929,6.158,4.216],size=[20,20,20],exhaustiveness=8,conformers=1,seed=42))
def poll(task_id,predicate,timeout=180):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        j=call('GET','/jobs/'+task_id)
        if predicate(j):return j
        time.sleep(.5)
    raise AssertionError('Timed out waiting for '+task_id)
report={}
try:
    task=submit('Checkpoint 및 재시작 검증')
    before=poll(task['id'],lambda t:t['completed']>=1 and t['status']=='running')
    first=next(r for r in call('GET',f'/jobs/{task["id"]}/results?sort=row')['rows'] if r['row_number']==2)
    pose_url=f'/api/jobs/{task["id"]}/compounds/{first["id"]}/pdbqt'
    checksum=hashlib.sha256(client.get(pose_url).content).hexdigest()
    subprocess.run(['docker','compose','restart','scheduler'],check=True,capture_output=True)
    after=poll(task['id'],lambda t:t['status'] in ('completed','partial','failed'))
    assert after['status']=='completed' and after['completed']==5,after
    assert hashlib.sha256(client.get(pose_url).content).hexdigest()==checksum
    code="""from dockschedule.db import Session
from dockschedule.models import Compound
import sys
with Session() as db:
 c=db.get(Compound,int(sys.argv[1]));assert c.attempts==1,c.attempts
print('checkpoint preserved without re-running completed compound')"""
    subprocess.run(['docker','compose','exec','-T','scheduler','python','-c',code,str(first['id'])],capture_output=True,check=True)
    report['restart']={'task':task['id'],'completed':after['completed'],'first_pose_sha256':checksum}
    task=submit('계산 프로세스 취소 검증')
    poll(task['id'],lambda t:t['status']=='running' and t['completed']>=1)
    call('POST',f'/jobs/{task["id"]}/cancel')
    cancelled=poll(task['id'],lambda t:t['status']=='cancelled' and not t['cpu_ids'],30)
    assert cancelled['completed']>=1
    report['cancellation']={'task':task['id'],'preserved':cancelled['completed'],'released_cpus':not cancelled['cpu_ids']}
    path=Path('test-results/resilience.json');path.parent.mkdir(exist_ok=True);path.write_text(json.dumps(report,indent=2))
    print(json.dumps(report,indent=2))
finally:
    call('PUT','/admin/settings',json=settings)
