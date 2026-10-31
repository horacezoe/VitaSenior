"""Trusted provenance persists across session boundaries and corrections."""
import pytest
from app.models.health import Checkin
from app.schemas.health import CheckinUpdate
from .helpers import transact
from .test_b1 import walk

def test_trusted_checkin_provenance_and_revision_are_persisted(health):
    h = health
    record = transact(h, h.checkins.create_or_update, walk(h), source="agent_confirmed")
    assert record.source == "agent_confirmed"
    updated = transact(h, h.checkins.create_or_update, CheckinUpdate(expected_version=1,
        payload={"activity": "散步", "duration_minutes": 25}), record.checkin_id)
    assert updated.source == "user" and updated.version == 2
    with h.factory() as tx:
        row = tx.get(Checkin, record.checkin_id)
        assert row.source == "user" and row.revisions_json[0]["source"] == "agent_confirmed"


def test_unknown_internal_provenance_is_rejected(health):
    from app.core.errors import AppError
    h = health
    with pytest.raises(AppError) as exc:
        transact(h, h.checkins.create_or_update, walk(h), source="demo_seed")
    assert exc.value.status == 422

