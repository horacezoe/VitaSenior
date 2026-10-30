from datetime import datetime, timezone, date
import pytest
from fastapi.testclient import TestClient
from app.main import create_app
from app.core.config import Settings
from app.core.clock import FakeClock
from app.core.uow import UnitOfWork
from app.models.identity import MediaAsset, ChangeProposal
from app.models.health import MedicationPlan, Checkin, Notification
from app.models.agent import AgentTurn, AgentAction
from app.seed import framework_seed

@pytest.fixture
def env(tmp_path):
    clock = FakeClock(datetime(2026, 10, 30, 4, 0, tzinfo=timezone.utc))
    app = create_app(Settings(data_dir=tmp_path / 'db', scanner_enabled=False, database_url=None), clock=clock)
    with TestClient(app, raise_server_exceptions=False) as client:
        seed = framework_seed(app.state.sessions, clock)
        yield app, client, clock, seed

@pytest.fixture
def tokens(env):
    app, client, clock, seed = env
    result = {}
    for label, account in seed.items():
        body = {k: account[k] for k in ['phone', 'role']}
        challenge = client.post('/api/v1/auth/code', json=body)
        assert challenge.status_code == 200, challenge.text
        response = client.post('/api/v1/auth/login', json={**body, 'challenge_id': challenge.json()['data']['challenge_id'], 'code': '123456'})
        assert response.status_code == 200, response.text
        result[label] = {'Authorization': 'Bearer ' + response.json()['data']['access_token'], 'Idempotency-Key': 'test-key'}
    return result

@pytest.fixture
def resources(env):
    """Minimal authorized rows so every P0 request reaches business logic, not 404."""
    app, client, clock, seed = env
    elder = seed['elder']['elder_id']
    with UnitOfWork(app.state.sessions) as u:
        tx = u.session
        tx.add(MediaAsset(id='asset', owner_user_id=seed['elder']['user_id'], elder_id=elder, purpose='agent_audio', mime_type='audio/wav', size_bytes=10, relative_path='test.wav', created_at=clock.now()))
        tx.add(MedicationPlan(id='plan', elder_id=elder, name='demo', dose_display='provided', schedule={'mode': 'fixed', 'slots': []}, start_date=date(2026, 10, 30), updated_at=clock.now()))
        tx.add(Checkin(id='checkin', elder_id=elder, type='exercise', local_date=date(2026, 10, 30), occurred_at=clock.now(), payload_json={'activity': 'walk', 'duration_minutes': 20}, created_at=clock.now(), updated_at=clock.now()))
        tx.add(ChangeProposal(id='proposal', elder_id=elder, created_by=seed['bound_child']['user_id'], target_type='profile', target_id=elder, operation='update', base_version=1, patch={'medical_notes': 'note'}))
        tx.add(AgentTurn(id='turn', elder_id=elder, actor_user_id=seed['elder']['user_id'], conversation_id='conv', client_turn_id='ct', request_json={}, response_json={}, created_at=clock.now()))
        tx.flush()
        tx.add(Notification(id='notice', elder_id=elder, source_key='fixture-notice', kind='profile_change', title='fixture', text='fixture', due_at=clock.now(), proposal_id='proposal'))
        tx.add(AgentAction(id='action', elder_id=elder, turn_id='turn', type='record_diet', payload_json={}, expires_at=clock.now()))
        tx.flush()
        u.commit()
    return elder
