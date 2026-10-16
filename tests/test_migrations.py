import os
import sqlite3
import subprocess
import sys


def test_compound_queue_index_migration_round_trip(tmp_path):
    database = tmp_path / 'migration.db'
    env = {**os.environ, 'DATABASE_URL': f'sqlite:///{database}', 'STORAGE_ROOT': str(tmp_path / 'storage')}

    def migrate(*args):
        subprocess.run([sys.executable, '-m', 'alembic', *args], env=env, check=True, capture_output=True, text=True)

    def columns():
        with sqlite3.connect(database) as db:
            return [row[2] for row in db.execute("PRAGMA index_info('compound_status')")]

    migrate('upgrade', 'head')
    assert columns() == ['task_id', 'status', 'row_number']
    with sqlite3.connect(database) as db:
        plan = db.execute("EXPLAIN QUERY PLAN SELECT * FROM compounds WHERE task_id = 'task' AND status = 'pending' ORDER BY row_number LIMIT 1").fetchall()
        assert any('compound_status' in row[3] for row in plan)
        assert all('TEMP B-TREE' not in row[3] for row in plan)
    migrate('downgrade', '742e1d0bc899')
    assert columns() == ['task_id', 'status']
    migrate('upgrade', 'head')
    assert columns() == ['task_id', 'status', 'row_number']


def test_interaction_migration_keeps_existing_tasks_and_poses(tmp_path):
    database = tmp_path / 'existing.db'
    env = {**os.environ, 'DATABASE_URL': f'sqlite:///{database}', 'STORAGE_ROOT': str(tmp_path / 'storage')}
    def migrate(*args):
        subprocess.run([sys.executable, '-m', 'alembic', *args], env=env, check=True, capture_output=True, text=True)
    migrate('upgrade', '9b7c31e2a640')
    with sqlite3.connect(database) as db:
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("INSERT INTO users VALUES (1,'user','User','','hash','student','approved',NULL,'2026-10-16')")
        db.execute("INSERT INTO uploads VALUES ('upload',1,'pdb','file.pdb','/file',0,'hash','2026-10-16')")
        db.execute("INSERT INTO receptors (id,owner_id,upload_id,name,status,options,report,structure,created_at,artifact_bytes) VALUES ('receptor',1,'upload','test','ready','{}','{}','{}','2026-10-16',0)")
        db.execute("INSERT INTO tasks (id,owner_id,receptor_id,kind,name,status,parameters,cpu_ids,total,completed,failed,cancel_requested,created_at,artifact_bytes,log_bytes) VALUES ('task',1,'receptor','screen','test','completed','{}','[]',1,1,0,0,'2026-10-16',0,0)")
        db.execute("INSERT INTO compounds (id,task_id,row_number,cid,smiles,status,affinity,details,attempts,artifact_bytes) VALUES (1,'task',1,'CID','N','succeeded',-4,'{}',1,0)")
    for target in [('upgrade', 'head'), ('downgrade', '9b7c31e2a640'), ('upgrade', 'head')]:
        migrate(*target)
        with sqlite3.connect(database) as db:
            assert db.execute('SELECT id,status FROM tasks').fetchall() == [('task', 'completed')]
            assert db.execute('SELECT id,affinity FROM compounds').fetchall() == [(1, -4)]
