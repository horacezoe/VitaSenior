from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.composition import compose
from app.contracts.context import Actor
from app.core.clock import FakeClock, local_date
from app.core.db import build_engine, create_tables, sessions
from app.core.errors import AppError
from app.core.uow import UnitOfWork
from app.models.health import Checkin as CheckinRow, DailyTask as TaskRow
from app.providers.mock_chat import MockUnderstanding
from app.schemas.enums import Role
from app.schemas.health import Checkin
from app.schemas.identity import BindingCode
from app.seed import framework_seed
from app.services.agent_service import AgentService
from app.services.memory_service import MemoryService


class TestCheckins:
    """Explicit B test double; performs real writes in the provided transaction."""
    __test__ = False

    def __init__(self, clock):
        self.clock, self.calls, self.fail_after_write = clock, 0, False

    def create_or_update(self, tx, actor, elder_id, payload, checkin_id=None):
        if payload.type == 'medication':
            task = tx.get(TaskRow, payload.task_id)
            if task is None or task.elder_id != elder_id or task.plan_id != payload.payload.plan_id:
                raise AppError(403, 'ELDER_ACCESS_DENIED', 'Task belongs to another elder/plan')
        self.calls += 1
        row = CheckinRow(elder_id=elder_id, type=payload.type,
                         local_date=local_date(payload.occurred_at), occurred_at=payload.occurred_at,
                         task_id=payload.task_id, payload_json=payload.payload.model_dump(mode='json'),
                         slot_key=payload.payload.meal_slot if payload.type == 'diet' else None,
                         source='agent_confirmed', created_at=self.clock.now(), updated_at=self.clock.now())
        tx.add(row)
        tx.flush()
        if self.fail_after_write:
            raise AppError(502, 'PROVIDER_ERROR', 'Injected B failure after SQL write')
        return Checkin(checkin_id=row.id, elder_id=elder_id, type=row.type, local_date=row.local_date,
                       occurred_at=row.occurred_at, task_id=row.task_id, payload=payload.payload,
                       version=row.version, source=row.source, created_at=row.created_at,
                       updated_at=row.updated_at, cancelled=False)


class TestMedia:
    __test__ = False

    def get_asset(self, tx, actor, asset_id):
        # Only this fixture's owner asset is granted; never used in production.
        if asset_id != 'owned-image':
            raise AppError(404, 'NOT_FOUND', 'Foreign asset')
        from app.schemas.identity import MediaAsset
        return MediaAsset(asset_id=asset_id, purpose='meal', mime_type='image/png',
                          size_bytes=10, duration_ms=None, content_url='/test-only',
                          expires_at=datetime(2027, 1, 1, tzinfo=timezone.utc))


class TestBinding:
    __test__ = False

    def __init__(self, clock):
        self.clock, self.calls = clock, 0

    def issue_code(self, tx, actor, elder_id):
        self.calls += 1
        from datetime import timedelta
        return BindingCode(code='0012', expires_at=self.clock.now() + timedelta(minutes=5), display_text='0012')


@dataclass
class Harness:
    factory: object
    clock: FakeClock
    seed: dict
    memory: MemoryService
    agent: AgentService
    tools: TestCheckins
    binding: TestBinding
    provider: MockUnderstanding

    def actor(self, name='elder'):
        account = self.seed[name]
        return Actor(account['user_id'], Role(account['role']))

    @property
    def elder_id(self):
        return self.seed['elder']['elder_id']

    @contextmanager
    def tx(self, write=True):
        with UnitOfWork(self.factory, write=write) as uow:
            yield uow.session
            uow.commit()

    def turn(self, body, actor=None, provider=None, **snapshots):
        actor = actor or self.actor()
        with self.tx(write=False) as tx:
            old = self.agent.replay(tx, actor, body)
            if old:
                return old
            snapshot = self.agent.read_snapshot(tx, actor, body, **snapshots)
        # Intentionally outside every Session / write lock.
        plan = (provider or self.provider).plan(body, snapshot)
        with self.tx() as tx:
            return self.agent.record_turn(tx, actor, body, snapshot, plan)


@pytest.fixture
def h(tmp_path):
    clock = FakeClock(datetime(2026, 10, 30, 4, 0, tzinfo=timezone.utc))
    engine = build_engine(tmp_path / 'agent-db')
    create_tables(engine)
    factory = sessions(engine)
    seed = framework_seed(factory, clock)
    bundle = compose()
    memory = MemoryService(clock, bundle.access)
    tools, binding = TestCheckins(clock), TestBinding(clock)
    bundle = replace(bundle, memory=memory, checkins=tools, media=TestMedia(), binding=binding)
    agent = AgentService(clock, bundle, memory)
    yield Harness(factory, clock, seed, memory, agent, tools, binding, MockUnderstanding())
    engine.dispose()
