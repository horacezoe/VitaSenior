from dataclasses import dataclass, replace
from datetime import datetime, timezone
import pytest
from fastapi.testclient import TestClient
from app.main import create_app
from app.core.config import Settings
from app.core.clock import FakeClock
from app.seed import framework_seed

@pytest.fixture
def env(tmp_path):
    clock = FakeClock(datetime(2026, 10, 30, 4, 0, tzinfo=timezone.utc))
    app = create_app(Settings(data_dir=tmp_path / 'db', scanner_enabled=False), clock=clock)
    with TestClient(app, raise_server_exceptions=False) as client:
        seed = framework_seed(app.state.sessions, clock)
        yield app, client, clock, seed

def auth_header(client, phone: str, role: str) -> dict:
    challenge = client.post('/api/v1/auth/code', json={'phone': phone, 'role': role})
    assert challenge.status_code == 200, challenge.text
    login = client.post('/api/v1/auth/login', json={'phone': phone, 'role': role,
                                                    'challenge_id': challenge.json()['data']['challenge_id'], 'code': '123456'})
    assert login.status_code == 200, login.text
    return {'Authorization': 'Bearer ' + login.json()['data']['access_token']}

def hdr(auth: dict, key: str) -> dict:
    return {**auth, 'Idempotency-Key': key}

@dataclass
class Demo:
    client: TestClient
    experience: dict
    elder: dict
    child: dict

    @property
    def elder_id(self) -> str:
        return self.experience['elder_id']

@pytest.fixture
def demo(env):
    """One real DEMO01 experience plus both bearer tokens and the live client."""
    app, client, clock, seed = env
    created = client.post('/api/v1/demo/experiences', json={'scenario': 'diabetes_daily'}, headers={'Idempotency-Key': 'demo-once'})
    assert created.status_code == 201, created.text
    experience = created.json()['data']
    elder = auth_header(client, experience['elder_account']['phone'], 'elder')
    child = auth_header(client, experience['child_account']['phone'], 'child')
    return Demo(client=client, experience=experience, elder=elder, child=child)

class FakeMedication:
    """Test double for B's port only: normal operation never swallows a real 501."""
    def __init__(self):
        self.calls = []

    def import_draft(self, tx, actor, elder_id, plans):
        self.calls.append({'elder_id': elder_id, 'plans': [p.name for p in plans]})
        return []

    def apply_change(self, *args, **kwargs):
        raise AssertionError('A must not smuggle other medication work through import_draft')

class FakeHistory:
    def __init__(self):
        self.calls = []

    def import_demo_history(self, tx, actor, elder_id, *, demo_id, days):
        self.calls.append({'elder_id': elder_id, 'demo_id': demo_id, 'days': days})

@pytest.fixture
def fakes(env):
    app, client, clock, seed = env
    original = app.state.services
    medication, history = FakeMedication(), FakeHistory()
    app.state.services = replace(original, medication=medication, history=history)
    yield medication, history
    app.state.services = original
