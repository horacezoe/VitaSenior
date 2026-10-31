from dataclasses import dataclass, replace
from datetime import datetime, timezone, date
from types import SimpleNamespace
import pytest
from fastapi.testclient import TestClient
from app.main import create_app
from app.core.config import Settings
from app.core.clock import FakeClock
from app.models.health import Notification as NotificationRow
from app.models.identity import ElderProfile
from app.schemas.health import MedicationPlan, ReminderSettings
from app.seed import framework_seed
from app.services.change_service import ChangeService

@pytest.fixture
def env(tmp_path):
    clock = FakeClock(datetime(2026, 10, 30, 4, 0, tzinfo=timezone.utc))
    app = create_app(Settings(data_dir=tmp_path / 'db', scanner_enabled=False, database_url=None), clock=clock)
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

    def bind_child(self) -> str:
        """Bind the demo pair through the real BIND01/BIND03 endpoints."""
        code = self.client.post(f'/api/v1/elders/{self.elder_id}/binding-codes', headers=hdr(self.elder, 'bind-code')).json()['data']['code']
        bound = self.client.post('/api/v1/family-bindings', headers=hdr(self.child, 'bind-consume'),
                                 json={'code': code, 'relationship': '女儿'})
        assert bound.status_code == 201, bound.text
        return code

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
    """Test double for B's ports only; normal operation never swallows a real 501."""
    def __init__(self):
        self.calls = []
        self.settings_calls = []
        self.imports = []
        self.plans: dict[str, dict] = {}

    def seed_plan(self, plan_id: str, elder_id: str, *, version: int = 1) -> None:
        self.plans[plan_id] = {
            'plan_id': plan_id, 'elder_id': elder_id, 'name': '演示药品A', 'dose_display': '既定用量',
            'schedule': {'mode': 'fixed', 'slots': [{'slot_id': 'morning', 'local_time': '08:00'}]},
            'start_date': date(2026, 10, 30), 'end_date': None, 'medicine_asset_id': None,
            'notes': '', 'active': True, 'version': version,
            'updated_at': datetime(2026, 10, 30, 4, 0, tzinfo=timezone.utc),
        }

    def get_plan(self, tx, actor, plan_id):
        return MedicationPlan.model_validate(self.plans[plan_id])

    def import_draft(self, tx, actor, elder_id, plans):
        self.imports.append({'elder_id': elder_id, 'plans': [p.name for p in plans]})
        return []

    def apply_change(self, tx, actor, elder_id, operation, target_id, patch, expected_version):
        self.calls.append({'elder_id': elder_id, 'operation': operation, 'target_id': target_id,
                           'patch': patch, 'expected_version': expected_version})
        raw = dict(self.plans[target_id])
        raw['version'] += 1
        raw['notes'] = getattr(patch, 'notes', None) or raw['notes']
        self.plans[target_id] = raw
        return MedicationPlan.model_validate(raw)

    def update_settings(self, tx, actor, elder_id, expected_version, patch):
        """Mirror B's port: bump the profile version and persist the merged settings."""
        from app.core.errors import AppError
        self.settings_calls.append({'elder_id': elder_id, 'expected_version': expected_version, 'patch': patch})
        elder = tx.get(ElderProfile, elder_id)
        if elder.version != expected_version:
            raise AppError(409, 'VERSION_CONFLICT', 'Profile/settings version changed')
        raw = dict(elder.reminder_settings_json or {})
        raw.update(patch.model_dump(exclude_unset=True, mode='json'))
        elder.reminder_settings_json = raw
        elder.version += 1
        return ReminderSettings(version=elder.version, **raw)

class FakeHistory:
    def __init__(self):
        self.calls = []

    def import_demo_history(self, tx, actor, elder_id, *, demo_id, days, seed=None):
        self.calls.append({'elder_id': elder_id, 'demo_id': demo_id, 'days': days})

class FakeNotifications:
    """Persists notification rows so A's FK and task_state assertions stay real."""
    def __init__(self):
        self.enqueued = []
        self.handled = []

    def enqueue(self, tx, actor, source_key, payload):
        row = NotificationRow(elder_id=payload.elder_id, source_key=source_key,
                              kind=str(payload.kind), title=payload.title, text=payload.text,
                              repeat_count=payload.repeat_count, due_at=payload.due_at,
                              audio_asset_id=payload.audio_asset_id, proposal_id=payload.proposal_id)
        tx.add(row)
        tx.flush()
        self.enqueued.append(row)
        return SimpleNamespace(notification_id=row.id)

    def mark_proposal_handled(self, tx, notification_id):
        row = tx.get(NotificationRow, notification_id)
        row.task_state = 'handled'
        self.handled.append(notification_id)

    def handle_event(self, *args, **kwargs):
        raise AssertionError('A2 does not process notification receipts itself')

class FakeMemory:
    def __init__(self):
        self.invalidations = []

    def on_source_changed(self, tx, actor, elder_id, source_ref):
        self.invalidations.append({'elder_id': elder_id, 'source': source_ref})

    def context(self, *args, **kwargs):
        raise AssertionError('A2 does not read memory')

@dataclass
class Fakes:
    medication: FakeMedication
    history: FakeHistory
    notifications: FakeNotifications
    memory: FakeMemory

@pytest.fixture
def fakes(env):
    app, client, clock, seed = env
    original = app.state.services
    bundle = Fakes(FakeMedication(), FakeHistory(), FakeNotifications(), FakeMemory())
    changes = ChangeService(clock, app.state.settings).bind(
        medication=bundle.medication, notifications=bundle.notifications,
        memory=bundle.memory, media=original.media)
    app.state.services = replace(original, medication=bundle.medication, history=bundle.history,
                                 notifications=bundle.notifications, memory=bundle.memory, changes=changes)
    yield bundle
    app.state.services = original
