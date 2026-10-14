"""Exercise 40 x 20,000 result rows in an isolated PostgreSQL database."""
import csv
import io
import json
import os
from pathlib import Path
import tempfile
import time
from uuid import uuid4

import psycopg
from psycopg import sql
from sqlalchemy.engine import make_url

source = make_url(os.environ['DATABASE_URL'])
database = 'dockschedule_scale_' + uuid4().hex[:12]
control = psycopg.connect(source.set(drivername='postgresql').render_as_string(hide_password=False), autocommit=True)
control.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(database)))
os.environ['DATABASE_URL'] = source.set(database=database).render_as_string(hide_password=False)
temporary = tempfile.TemporaryDirectory(prefix='ds-scale-')
os.environ['STORAGE_ROOT'] = temporary.name
try:
    from alembic.config import Config
    from alembic import command
    from dockschedule.db import engine, transaction
    from dockschedule.models import User, Upload, Receptor, Task, Compound
    from dockschedule.library import compounds
    from dockschedule.api import score_rows
    from sqlalchemy import insert, select, func
    import psutil
    command.upgrade(Config('alembic.ini'), 'head')
    csvfile = Path(temporary.name)/'library.csv'
    csvfile.write_text('CID,SMILES\n'+''.join(f'{n:06d},CCO\n' for n in range(20000)))
    options=dict(delimiter=',',encoding='utf-8-sig',header=True,cid_column='CID',smiles_column='SMILES')
    start=time.monotonic()
    assert sum(1 for _ in compounds(csvfile,options,20000))==20000
    parse_seconds=time.monotonic()-start
    start=time.monotonic()
    tasks=[]
    for n in range(40):
        with transaction() as db:
            user=User(username=f'scale-{n}',name='Scale test',student_number=str(n),password_hash='disabled',status='suspended')
            db.add(user);db.flush()
            upload=Upload(owner_id=user.id,kind='pdb',filename='scale',path=str(csvfile),size=csvfile.stat().st_size,sha256='0'*64)
            db.add(upload);db.flush()
            receptor=Receptor(owner_id=user.id,upload_id=upload.id,name='scale',status='ready')
            db.add(receptor);db.flush()
            task=Task(owner_id=user.id,receptor_id=receptor.id,name='scale',kind='screen',status='completed',total=20000)
            db.add(task);db.flush();tasks.append(task.id)
            for batch_start in range(0,20000,2000):
                db.execute(insert(Compound),[dict(task_id=task.id,row_number=i+2,cid=f'{i:06d}',smiles='CCO',normalized_smiles='CCO',status='succeeded',affinity=-5-(i%300)/100) for i in range(batch_start,batch_start+2000)])
    insert_seconds=time.monotonic()-start
    with transaction() as db:
        assert db.scalar(select(func.count()).select_from(Compound))==800000
        start=time.monotonic()
        rows=list(db.scalars(select(Compound).where(Compound.task_id==tasks[-1]).order_by(Compound.affinity,Compound.row_number).limit(50)))
        query_seconds=time.monotonic()-start
        assert len(rows)==50
        assert db.scalar(select(func.count()).select_from(Compound).where(Compound.task_id==tasks[-1],Compound.cid.contains('001',autoescape=True)))>0
    start=time.monotonic()
    exported=0
    for chunk in score_rows(tasks[-1]):
        exported+=chunk.count('\n')
    assert exported==20001
    result=dict(rows=800000,students=40,rows_per_job=20000,parse_seconds=parse_seconds,insert_seconds=insert_seconds,
                first_page_seconds=query_seconds,export_seconds=time.monotonic()-start,export_lines=exported,
                rss_mb=psutil.Process().memory_info().rss/1024**2)
    print(json.dumps(result,indent=2),flush=True)
finally:
    if 'engine' in locals():engine.dispose()
    control.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(database)))
    control.close()
    temporary.cleanup()
