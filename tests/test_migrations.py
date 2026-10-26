import json
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


def test_gnina_migration_keeps_data_and_fills_setting(tmp_path):
    database = tmp_path / 'gnina.db'
    env = {**os.environ, 'DATABASE_URL': f'sqlite:///{database}', 'STORAGE_ROOT': str(tmp_path / 'storage')}
    def migrate(*args):
        subprocess.run([sys.executable, '-m', 'alembic', *args], env=env, check=True, capture_output=True, text=True)
    previous = 'b63d14a829f0'
    migrate('upgrade', previous)
    with sqlite3.connect(database) as db:
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("INSERT INTO users VALUES (1,'user','User','','hash','student','approved',NULL,'2026-10-16')")
        db.execute("INSERT INTO uploads VALUES ('upload',1,'pdb','file.pdb','/file',0,'hash','2026-10-16')")
        db.execute("INSERT INTO receptors (id,owner_id,upload_id,name,status,options,report,structure,created_at,artifact_bytes) VALUES ('receptor',1,'upload','test','ready','{}','{}','{}','2026-10-16',0)")
        db.execute("INSERT INTO tasks (id,owner_id,receptor_id,kind,name,status,parameters,cpu_ids,total,completed,failed,cancel_requested,created_at,artifact_bytes,log_bytes) VALUES ('task',1,'receptor','screen','test','completed','{}','[]',1,1,0,0,'2026-10-16',0,0)")
        db.execute("INSERT INTO compounds (id,task_id,row_number,cid,smiles,status,affinity,details,attempts,artifact_bytes) VALUES (1,'task',1,'CID','N','succeeded',-4,'{}',1,0)")
        db.execute("""INSERT INTO settings (id,"values",available_cpus) VALUES (1,'{"max_compounds": 500}','[]')""")
    for target in [('upgrade', 'head'), ('downgrade', previous), ('upgrade', 'head')]:
        migrate(*target)
        with sqlite3.connect(database) as db:
            assert db.execute('SELECT id,status FROM tasks').fetchall() == [('task', 'completed')]
            assert db.execute('SELECT id,affinity FROM compounds').fetchall() == [(1, -4)]
            values = json.loads(db.execute('SELECT "values" FROM settings').fetchone()[0])
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if target[0] == 'upgrade':
                assert values == {'max_compounds': 500, 'gnina_top_n': 500}
                assert 'gnina_scores' in tables
                assert [r[2] for r in db.execute("PRAGMA index_info('gnina_queue')")] == ['task_id', 'status']
            else:
                assert values == {'max_compounds': 500}
                assert 'gnina_scores' not in tables


def test_gnina_top_n_setting_schema():
    from pydantic import ValidationError
    from dockschedule.config import DEFAULT_SETTINGS, Config
    from dockschedule.schemas import ResourceSettings
    assert DEFAULT_SETTINGS['gnina_top_n'] == 1000
    assert Config().gnina_binary.as_posix() == 'tools/gnina'
    body = {k: v for k, v in DEFAULT_SETTINGS.items() if k != 'gnina_top_n'}
    assert ResourceSettings(**body).gnina_top_n == 1000
    assert ResourceSettings(**body, gnina_top_n=0).gnina_top_n == 0
    for bad in (-1, body['max_compounds'] + 1):
        try:
            ResourceSettings(**body, gnina_top_n=bad)
        except ValidationError:
            continue
        raise AssertionError(bad)
    try:
        ResourceSettings(**{**body, 'max_compounds': 999})
    except ValidationError:
        pass
    else:
        raise AssertionError('max_compounds below default gnina_top_n must be rejected')
    assert ResourceSettings(**{**body, 'max_compounds': 999, 'gnina_top_n': 999}).max_compounds == 999
