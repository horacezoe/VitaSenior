"""Isolated SQLite and explicit cross-domain doubles, never production stubs."""
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.contracts.context import Actor
from app.core.clock import FakeClock
from app.core.db import build_engine, create_tables, sessions
from app.models.agent import MemoryDocument
from app.schemas.enums import Role
from app.seed import framework_seed
from app.services.health_service import CheckinService
from app.services.medication_service import MedicationService
from app.services.report_service import ReportService


class MemoryDouble:
    """Persist an audit in the SAME tx to prove atomic source invalidation."""
    def __init__(self, clock):
        self.clock = clock
        self.fail = False

    def on_source_changed(self, tx, actor, elder_id, source_ref):
        row = tx.get(MemoryDocument, elder_id)
        if row is None:
            row = MemoryDocument(elder_id=elder_id, entries_json=[], revisions_json=[], version=1)
            tx.add(row)
        row.revisions_json = [*row.revisions_json, source_ref.model_dump(mode="json")]
        row.version += 1
        row.updated_at = self.clock.now()
        tx.flush()
        if self.fail:
            raise RuntimeError("Injected memory failure")


@pytest.fixture
def health(tmp_path):
    clock = FakeClock(datetime(2026, 10, 30, 0, tzinfo=timezone.utc))
    engine = build_engine(tmp_path / "health")
    create_tables(engine)
    factory = sessions(engine)
    seed = framework_seed(factory, clock)
    actors = {k: Actor(v["user_id"], Role(v["role"])) for k, v in seed.items()}
    memory = MemoryDouble(clock)
    env = SimpleNamespace(clock=clock, engine=engine, factory=factory, seed=seed, actors=actors,
        elder=seed["elder"]["elder_id"], actor=actors["elder"], memory=memory,
        checkins=CheckinService(clock, memory=memory), medication=MedicationService(clock, memory=memory),
        reports=ReportService(clock))
    yield env
    engine.dispose()


