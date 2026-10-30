from datetime import datetime, timezone
import pytest
from fastapi.testclient import TestClient
from app.main import create_app
from app.core.config import Settings
from app.core.clock import FakeClock
from app.seed import framework_seed

@pytest.fixture
def env(tmp_path):
    clock = FakeClock(datetime(2026,10,30,4,0,tzinfo=timezone.utc))
    app = create_app(Settings(data_dir=tmp_path / 'db', scanner_enabled=False, database_url=None), clock=clock)
    with TestClient(app, raise_server_exceptions=False) as client:
        seed = framework_seed(app.state.sessions, clock)
        yield app, client, clock, seed

@pytest.fixture
def tokens(env):
    app, client, clock, seed = env
    result = {}
    for label, account in seed.items():
        body = {k:account[k] for k in ['phone','role']}
        challenge = client.post('/api/v1/auth/code', json=body)
        assert challenge.status_code == 200, challenge.text
        response = client.post('/api/v1/auth/login', json={**body, 'challenge_id':challenge.json()['data']['challenge_id'], 'code':'123456'})
        assert response.status_code == 200, response.text
        result[label] = {'Authorization':'Bearer '+response.json()['data']['access_token'], 'Idempotency-Key':'test-key'}
    return result
