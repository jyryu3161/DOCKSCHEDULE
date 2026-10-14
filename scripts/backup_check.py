"""Validate a real backup by restoring into an isolated DB and artifact directory."""
import hashlib
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile
from uuid import uuid4

backup=Path('.backups')/('validation-'+uuid4().hex[:8])
subprocess.run(['bash','scripts/backup.sh',str(backup)],check=True)
database='dockschedule_restore_'+uuid4().hex[:12]
def db(*args,**kwargs):
    return subprocess.run(['docker','compose','exec','-T','db',*args],check=True,**kwargs)
def counts(name):
    return db('psql','-U','dockschedule','-d',name,'-Atc',
              'SELECT (SELECT count(*) FROM users),(SELECT count(*) FROM tasks),(SELECT count(*) FROM compounds)',
              capture_output=True,text=True).stdout.strip()
try:
    db('createdb','-U','dockschedule',database)
    with (backup/'database.dump').open('rb') as f:
        db('pg_restore','-U','dockschedule','-d',database,'--exit-on-error',stdin=f)
    restored_counts=counts(database)
    assert restored_counts==counts('dockschedule')
    files=0
    with tempfile.TemporaryDirectory(prefix='ds-restore-check-') as target:
        with tarfile.open(backup/'storage.tar.gz') as archive:
            archive.extractall(target,filter='data')
        for path in Path(target).rglob('*'):
            if path.is_file():
                source=Path('storage')/path.relative_to(target)
                assert source.is_file()
                assert hashlib.sha256(path.read_bytes()).digest()==hashlib.sha256(source.read_bytes()).digest(),str(path)
                files+=1
    result=dict(database_rows_users_tasks_compounds=restored_counts,verified_artifact_files=files,
                database_restored=True,artifact_hashes_matched=True,private_env_mode=oct((backup/'deployment.env').stat().st_mode&0o777))
    Path('test-results/backup.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result,indent=2))
finally:
    db('dropdb','-U','dockschedule','--if-exists',database)
