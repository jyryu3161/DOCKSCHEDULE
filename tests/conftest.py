import os
import tempfile
from pathlib import Path
import pytest

TEST_ROOT = Path(tempfile.mkdtemp(prefix='dockschedule-tests-'))
os.environ['DATABASE_URL'] = 'sqlite:///'+str(TEST_ROOT/'test.db')
os.environ['STORAGE_ROOT'] = str(TEST_ROOT/'storage')
os.environ['ADMIN_PASSWORD'] = 'TestAdmin123!'

from dockschedule.db import Base, engine, transaction
from dockschedule.api import app
from dockschedule.security import bootstrap
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with TestClient(app, headers={'X-DS-Request':'1'}) as c:
        yield c


@pytest.fixture
def admin_client(client):
    r = client.post('/api/auth/login', json={'username':'admin','password':'TestAdmin123!'})
    assert r.status_code == 200
    return client
