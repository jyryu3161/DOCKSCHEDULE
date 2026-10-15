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
