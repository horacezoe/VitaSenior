"""Real default composition, real A/B/C, tmp SQLite. No service doubles.

The test-only operation declaration lets us verify before committing activation;
once registered the same checks also exercise the actual production declarations.
"""
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
import hashlib
import io
import json
import wave

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.core.clock import FakeClock
from app.core.config import Settings
from app.core.uow import UnitOfWork
from app.main import create_app
from app.models.health import Checkin, DailyTask, DailyGoalBatch, Notification, NotificationEvent, MedicationPlan
from app.models.identity import ElderProfile
from app.models.agent import MemoryDocument
from app.schemas.agent import MemoryEntry
from app.seed import framework_seed

OPERATIONS = frozenset({"PLAN01", "PLAN02", "PLAN03", "SET01", "SET02", "TASK01",
    "REC01", "REC02", "REC03", "REC04", "REPORT01", "DASH01", "CAL01",
    "NOTI01", "NOTI02", "NOTI03", "NOTI04"})
FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "health"


@pytest.fixture
def production(tmp_path):
    clock = FakeClock(datetime(2026, 10, 30, 4, tzinfo=timezone.utc))
    app = create_app(Settings(data_dir=tmp_path / "production", database_url=None, scanner_enabled=False), clock=clock)
    app.state.capabilities_declared |= OPERATIONS
    with TestClient(app, raise_server_exceptions=False) as client:
        seed = framework_seed(app.state.sessions, clock)
        tokens = {}
        for label, account in seed.items():
            account = {"phone": account["phone"], "role": account["role"]}
            challenge = client.post("/api/v1/auth/code", json=account).json()["data"]["challenge_id"]
            result = client.post("/api/v1/auth/login", json={**account, "challenge_id": challenge, "code": "123456"})
            assert result.status_code == 200, result.text
            tokens[label] = {"Authorization": "Bearer " + result.json()["data"]["access_token"]}
        yield SimpleNamespace(app=app, client=client, clock=clock, seed=seed, tokens=tokens,
            elder=seed["elder"]["elder_id"])


def headers(p, key, label="elder"):
    return {**p.tokens[label], "Idempotency-Key": key}


def get(p, suffix, label="elder"):
    response = p.client.get(f"/api/v1/elders/{p.elder}/{suffix}", headers=p.tokens[label])
    assert response.status_code == 200, response.text
    return response.json()["data"]


def post_checkin(p, category="diet", key="checkin"):
    payload = {"meal_slot": "lunch", "foods": ["豆腐"]} if category == "diet" else {"activity": "散步", "duration_minutes": 20}
    response = p.client.post(f"/api/v1/elders/{p.elder}/checkins", headers=headers(p, key),
        json={"type": category, "occurred_at": p.clock.now().isoformat(), "payload": payload})
    assert response.status_code == 201, response.text
    return response.json()["data"]


def test_default_plans_settings_versions_and_child_denial(production):
    p = production
    assert get(p, "medication-plans")["items"] == []
    settings = get(p, "reminder-settings", "bound_child")
    body = {"expected_version": settings["version"], "patch": {"voice_enabled": False}}
    url = f"/api/v1/elders/{p.elder}/reminder-settings"
    assert p.client.put(url, json=body, headers=headers(p, "child", "bound_child")).status_code == 403
    updated = p.client.put(url, json=body, headers=headers(p, "settings"))
    assert updated.status_code == 200, updated.text
    assert updated.json()["data"]["version"] == 2
    assert p.client.put(url, json=body, headers=headers(p, "settings")).json()["data"] == updated.json()["data"]
    assert p.client.put(url, json=body, headers=headers(p, "stale")).status_code == 409
    plan = {"name": "既定药物", "dose_display": "本人既定用量", "start_date": "2026-10-30",
        "schedule": {"mode": "fixed", "slots": [{"slot_id": "afternoon", "local_time": "13:00"}]}}
    created = p.client.post(f"/api/v1/elders/{p.elder}/medication-plans", json=plan, headers=headers(p, "plan"))
    assert created.status_code == 201, created.text
    plan_id = created.json()["data"]["plan_id"]
    assert get(p, "medication-plans?active=true")["items"][0]["plan_id"] == plan_id
    changed = p.client.put(f"/api/v1/medication-plans/{plan_id}", headers=headers(p, "plan-update"),
        json={"expected_version": 1, "patch": {"notes": "核对过的备注"}})
    assert changed.status_code == 200, changed.text
    assert changed.json()["data"]["version"] == 2
    assert any(t["plan_id"] == plan_id for t in get(p, "tasks?date=2026-10-30")["items"])


def test_records_correction_cancel_and_three_views_persist(production):
    p = production
    first = post_checkin(p)
    post_checkin(p, "exercise", "walk-1")
    post_checkin(p, "exercise", "walk-2")
    page = get(p, "checkins?date=2026-10-30&type=exercise&limit=1", "bound_child")
    assert len(page["items"]) == 1 and page["next_cursor"]
    assert len(get(p, f'checkins?date=2026-10-30&type=exercise&cursor={page["next_cursor"]}')["items"]) == 1
    update = p.client.put(f'/api/v1/checkins/{first["checkin_id"]}', headers=headers(p, "correct"),
        json={"expected_version": 1, "payload": {"meal_slot": "lunch", "foods": ["青菜", "粥"]}})
    assert update.status_code == 200, update.text
    report = get(p, "reports/daily?date=2026-10-30", "bound_child")
    dashboard = get(p, "dashboard?date=2026-10-30", "bound_child")
    calendar = get(p, "calendar?month=2026-10", "bound_child")
    assert report["completion"] == dashboard["completion"] == calendar["days"][29]
    assert report["records"] == dashboard["today_records"]
    assert report["records"]["diet"][0]["payload"]["foods"] == ["青菜", "粥"]
    url = f'/api/v1/checkins/{first["checkin_id"]}?expected_version=2'
    cancel = p.client.delete(url, headers=headers(p, "cancel"))
    assert cancel.status_code == 200, cancel.text
    assert p.client.delete(url, headers=headers(p, "cancel")).json()["data"] == cancel.json()["data"]
    assert p.client.delete(url, headers=headers(p, "stale-cancel")).status_code == 409
    assert get(p, "reports/daily?date=2026-10-30")["completion"]["progress"]["diet"]["completed"] == 0
    with p.app.state.sessions() as tx:
        row = tx.get(Checkin, first["checkin_id"])
        assert row.cancelled_at is not None and len(row.revisions_json) == 2
        assert row.payload_json["foods"] == ["青菜", "粥"]


@pytest.mark.parametrize("suffix", ["medication-plans", "reminder-settings", "tasks?date=2026-10-30",
    "checkins?date=2026-10-30", "dashboard", "calendar?month=2026-10", "reports/daily?date=2026-10-30", "notifications"])
def test_unbound_read_denied_for_every_query(production, suffix):
    p = production
    assert p.client.get(f"/api/v1/elders/{p.elder}/{suffix}", headers=p.tokens["unbound_child"]).status_code == 403


def upload_voice(p, label="bound_child", file="exercise.wav"):
    audio = (FIXTURES / file).read_bytes()
    response = p.client.post("/api/v1/media", headers=headers(p, "voice-" + file, label),
        data={"purpose": "voice_message"}, files={"file": (file, audio, "audio/wav")})
    assert response.status_code == 201, response.text
    return response.json()["data"]["asset_id"], audio


def test_family_voice_priority_shared_copy_repeats_and_no_taken(production):
    p = production
    source, audio = upload_voice(p)
    url = f"/api/v1/elders/{p.elder}/family-reminders"
    body = {"category": "exercise", "template_id": "diet", "audio_asset_id": source, "repeat_count": 2}
    response = p.client.post(url, json=body, headers=headers(p, "family", "bound_child"))
    assert response.status_code == 201, response.text
    notice = response.json()["data"]
    assert p.client.post(url, json=body, headers=headers(p, "family", "bound_child")).json()["data"] == notice
    asset = p.client.get(f'/api/v1/media/{notice["audio_asset_id"]}', headers=p.tokens["elder"])
    assert asset.status_code == 200, asset.text
    assert p.client.get(asset.json()["data"]["content_url"]).content == audio
    assert get(p, "notifications", "bound_child")["items"][0]["delivery_state"] == "pending"
    events = f'/api/v1/notifications/{notice["notification_id"]}/events'
    def emit(kind, key):
        return p.client.post(events, headers=headers(p, key), json={"event_id": key, "event_type": kind})
    assert emit("displayed", "hidden").status_code == 409
    assert p.client.post(f"/api/v1/elders/{p.elder}/presence", headers=p.tokens["elder"],
        json={"client_id": "web", "visible": True}).status_code == 200
    assert emit("displayed", "displayed").status_code == 200
    assert emit("answered", "answered").status_code == 200
    first = emit("playback_completed", "play-1")
    assert first.status_code == 200, first.text
    assert first.json()["data"]["notification"]["delivery_state"] == "answered"
    assert emit("playback_completed", "play-1").json()["data"] == first.json()["data"]
    assert emit("playback_completed", "play-2").json()["data"]["notification"]["delivery_state"] == "played"
    with p.app.state.sessions() as tx:
        assert tx.scalar(select(func.count()).select_from(Checkin)) == 0
    assert get(p, "reports/daily?date=2026-10-30")["completion"]["progress"]["exercise"]["completed"] == 0


@pytest.mark.parametrize("template", ["diet", "exercise", "medication", "general"])
def test_family_fixed_speech_exact_fixture_integrity(production, template):
    p = production
    response = p.client.post(f"/api/v1/elders/{p.elder}/family-reminders", headers=headers(p, template, "bound_child"),
        json={"category": "general", "template_id": template})
    assert response.status_code == 201, response.text
    notice = response.json()["data"]
    row = next(r for r in json.loads((FIXTURES / "audio_manifest.json").read_text(encoding="utf-8-sig")) if r["template_id"] == template)
    assert notice["text"] == row["text"] and row["is_mock"] is True
    asset = p.client.get(f'/api/v1/media/{notice["audio_asset_id"]}', headers=p.tokens["elder"]).json()["data"]
    raw = p.client.get(asset["content_url"]).content
    assert hashlib.sha256(raw).hexdigest() == row["sha256"]
    with wave.open(io.BytesIO(raw)) as wav:
        assert wav.getnframes() / wav.getframerate() > 2


def test_family_ownership_permissions_and_text_fallback(production):
    p = production
    source, _ = upload_voice(p, "elder")
    url = f"/api/v1/elders/{p.elder}/family-reminders"
    body = {"category": "general", "audio_asset_id": source}
    assert p.client.post(url, json=body, headers=headers(p, "foreign", "bound_child")).status_code == 404
    assert p.client.post(url, json=body, headers=headers(p, "unbound", "unbound_child")).status_code == 403
    text = p.client.post(url, json={"category": "general", "text": "周日一起吃饭"}, headers=headers(p, "text", "bound_child"))
    assert text.status_code == 201, text.text
    assert text.json()["data"]["audio_asset_id"] is None
    assert text.json()["data"]["text"] == "周日一起吃饭"
    assert p.client.post(url, json={"category": "general", "template_id": "missing"}, headers=headers(p, "bad-template", "bound_child")).status_code == 422


def test_speech_preparation_does_not_hold_write_lock(production, monkeypatch):
    p = production
    original = Path.read_bytes
    checks = []
    def read_bytes(path):
        if path.parent == FIXTURES and path.suffix == ".wav":
            with UnitOfWork(p.app.state.sessions) as unit:
                unit.commit()
            checks.append(path.name)
        return original(path)
    monkeypatch.setattr(Path, "read_bytes", read_bytes)
    result = p.client.post(f"/api/v1/elders/{p.elder}/family-reminders", headers=headers(p, "outside-lock", "bound_child"),
        json={"category": "general", "template_id": "general"})
    assert result.status_code == 201, result.text
    assert checks == ["general.wav"]


def test_calendar_invalid_year_is_validation_error(production):
    p = production
    assert p.client.get(f"/api/v1/elders/{p.elder}/calendar?month=0000-01", headers=p.tokens["elder"]).status_code == 422


def test_correction_invalidates_real_c_memory_and_dashboard(production):
    p = production
    record = post_checkin(p)
    # Fixture is an already-persisted observation. Formation rules are tested by
    # C; this verifies B's actual transactional source-invalidation port.
    entry = MemoryEntry(entry_id="saved-observation", kind="meal_routine", text="演示观察",
        source_type="observed_pattern", source_ids=[{"type": "checkin", "id": record["checkin_id"], "version": 1}],
        created_at=p.clock.now(), updated_at=p.clock.now())
    with UnitOfWork(p.app.state.sessions) as unit:
        unit.session.add(MemoryDocument(elder_id=p.elder, version=2,
            entries_json=[entry.model_dump(mode="json")], revisions_json=[], updated_at=p.clock.now()))
        unit.commit()
    assert "演示观察" in get(p, "dashboard")["memory_summary"]
    response = p.client.put(f'/api/v1/checkins/{record["checkin_id"]}', headers=headers(p, "real-c-correction"),
        json={"expected_version": 1, "payload": {"meal_slot": "lunch", "foods": ["青菜"]}})
    assert response.status_code == 200, response.text
    memory = get(p, "memory")
    assert memory["entries"] == [] and memory["version"] == 3
    assert get(p, "dashboard")["memory_summary"] == ""


def test_default_medication_task_requires_matching_plan_and_explicit_taken(production):
    p = production
    plan = {"name": "既定药物", "dose_display": "明确的既定用量", "start_date": "2026-10-30",
        "schedule": {"mode": "fixed", "slots": [{"slot_id": "afternoon", "local_time": "13:00"}]}}
    url = f"/api/v1/elders/{p.elder}/medication-plans"
    first = p.client.post(url, json=plan, headers=headers(p, "med-1"))
    second = p.client.post(url, json=plan, headers=headers(p, "med-2"))
    assert first.status_code == second.status_code == 201
    plan_id = first.json()["data"]["plan_id"]
    task = next(t for t in get(p, "tasks?date=2026-10-30")["items"] if t["plan_id"] == plan_id)
    checkin_url = f"/api/v1/elders/{p.elder}/checkins"
    body = {"type": "medication", "task_id": task["task_id"], "occurred_at": p.clock.now().isoformat(),
        "payload": {"plan_id": second.json()["data"]["plan_id"], "slot_id": "afternoon", "intake_status": "taken"}}
    assert p.client.post(checkin_url, json=body, headers=headers(p, "wrong-plan")).status_code == 422
    body["payload"]["plan_id"] = plan_id
    result = p.client.post(checkin_url, json=body, headers=headers(p, "explicit-taken"))
    assert result.status_code == 201, result.text
    assert p.client.post(checkin_url, json=body, headers=headers(p, "explicit-taken")).json()["data"] == result.json()["data"]
    assert p.client.post(checkin_url, json=body, headers=headers(p, "duplicate-task")).status_code == 409
    progress = get(p, "reports/daily?date=2026-10-30")["completion"]["progress"]["medication"]
    assert progress["expected"] == 2 and progress["completed"] == 1


def test_invalid_legacy_plan_is_rejected_and_can_be_repaired(production):
    p = production
    with UnitOfWork(p.app.state.sessions) as unit:
        unit.session.add(MedicationPlan(id="legacy-invalid", elder_id=p.elder, name="待核对计划",
            dose_display="既定用量", schedule={"mode": "fixed", "slots": []},
            start_date=p.clock.now().date(), updated_at=p.clock.now()))
        unit.commit()
    read = p.client.get(f"/api/v1/elders/{p.elder}/medication-plans", headers=p.tokens["elder"])
    assert read.status_code == 422 and read.json()["error"]["code"] == "VALIDATION_ERROR"
    url = "/api/v1/medication-plans/legacy-invalid"
    invalid = p.client.put(url, json={"expected_version": 1, "patch": {"notes": "仍无时段"}}, headers=headers(p, "invalid-plan"))
    assert invalid.status_code == 422
    repaired = p.client.put(url, json={"expected_version": 1, "patch": {"schedule": {
        "mode": "fixed", "slots": [{"slot_id": "one", "local_time": "13:00"}]}}}, headers=headers(p, "repair"))
    assert repaired.status_code == 200, repaired.text
    assert repaired.json()["data"]["version"] == 2
    assert get(p, "medication-plans")["items"][0]["schedule"]["slots"][0]["slot_id"] == "one"


def test_actual_default_registration_enables_core_and_gates_proposal_receipts(production):
    p = production
    # A fresh default app has no test-only capability override or service bundle.
    app = create_app(p.app.state.settings, clock=p.clock)
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/api/v1/runtime", headers=p.tokens["elder"])
        assert response.status_code == 200, response.text
        runtime = response.json()["data"]["capabilities"]
        assert all(runtime[name] is True for name in OPERATIONS - {"NOTI03"})
        assert runtime["NOTI03"] is False
        result = client.post(f"/api/v1/elders/{p.elder}/family-reminders",
            headers=headers(p, "gated-receipt", "bound_child"), json={"category": "general", "template_id": "general"})
        assert result.status_code == 201, result.text
        notice_id = result.json()["data"]["notification_id"]
        event = client.post(f"/api/v1/notifications/{notice_id}/events", headers=headers(p, "gated-event"),
            json={"event_id": "held-for-announcement-contract", "event_type": "handled"})
        assert event.status_code == 501 and event.json()["error"]["code"] == "MODULE_NOT_IMPLEMENTED"
        with app.state.sessions() as tx:
            assert tx.get(Notification, notice_id).task_state == "open"
