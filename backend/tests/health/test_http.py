from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.composition import compose
from app.core.config import Settings
from app.main import create_app
from app.models.health import Checkin
from app.seed import framework_seed


@pytest.fixture
def api(health, tmp_path):
    h = health
    settings = Settings(data_dir=tmp_path / "http", database_url=None, scanner_enabled=False)
    # Test-only explicit composition. Production must be connected by A; no
    # monkeypatch of the real composition or fake success response is used.
    bundle = replace(compose(h.clock, settings), checkins=h.checkins, medication=h.medication,
                     reports=h.reports, tasks=h.checkins, history=h.checkins)
    app = create_app(settings, clock=h.clock, services=bundle)
    app.state.capabilities_declared |= frozenset({"PLAN02", "PLAN03", "TASK01", "REC02", "REC03", "REPORT01"})
    with TestClient(app, raise_server_exceptions=False) as client:
        seed = framework_seed(app.state.sessions, h.clock)
        tokens = {}
        for label, account in seed.items():
            identity = {"phone": account["phone"], "role": account["role"]}
            challenge = client.post("/api/v1/auth/code", json=identity).json()["data"]["challenge_id"]
            response = client.post("/api/v1/auth/login", json={**identity, "challenge_id": challenge, "code": "123456"})
            assert response.status_code == 200
            tokens[label] = {"Authorization": "Bearer " + response.json()["data"]["access_token"]}
        yield app, client, seed, tokens, h


def test_http_same_meal_replay_conflict_and_child_report(api):
    app, client, seed, tokens, h = api
    elder = seed["elder"]["elder_id"]
    url = f"/api/v1/elders/{elder}/checkins"
    body = {"type": "diet", "occurred_at": h.clock.now().isoformat(),
            "payload": {"meal_slot": "lunch", "foods": ["豆腐"]}}
    headers = {**tokens["elder"], "Idempotency-Key": "meal"}
    first = client.post(url, json=body, headers=headers)
    assert first.status_code == 201, first.text
    replay = client.post(url, json=body, headers=headers)
    assert replay.status_code == 201 and replay.json()["data"] == first.json()["data"]
    assert replay.json()["meta"]["request_id"] != first.json()["meta"]["request_id"]
    changed = {**body, "payload": {"meal_slot": "lunch", "foods": ["粥"]}}
    assert client.post(url, json=changed, headers=headers).status_code == 409
    replaced = client.post(url, json=changed, headers={**tokens["elder"], "Idempotency-Key": "meal-2"})
    assert replaced.status_code == 200 and replaced.json()["meta"]["replaced"] is True
    assert replaced.json()["data"]["version"] == 2
    report = client.get(f"/api/v1/elders/{elder}/reports/daily?date=2026-10-30", headers=tokens["bound_child"])
    assert report.status_code == 200, report.text
    assert report.json()["data"]["records"]["diet"][0]["payload"]["foods"] == ["粥"]
    assert client.get(f"/api/v1/elders/{elder}/reports/daily?date=2026-10-30", headers=tokens["unbound_child"]).status_code == 403
    assert client.post(url, json=body, headers={**tokens["bound_child"], "Idempotency-Key": "child"}).status_code == 403


def test_http_concurrent_idempotency_and_task_reads(api):
    app, client, seed, tokens, h = api
    elder = seed["elder"]["elder_id"]
    body = {"type": "exercise", "occurred_at": h.clock.now().isoformat(),
            "payload": {"activity": "散步", "duration_minutes": 20}}
    headers = {**tokens["elder"], "Idempotency-Key": "walk"}
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: client.post(f"/api/v1/elders/{elder}/checkins", json=body, headers=headers), range(2)))
    assert all(r.status_code == 201 for r in results), [r.text for r in results]
    assert len({r.json()["data"]["checkin_id"] for r in results}) == 1
    with ThreadPoolExecutor(max_workers=2) as pool:
        tasks = list(pool.map(lambda _: client.get(f"/api/v1/elders/{elder}/tasks?date=2026-10-30", headers=tokens["elder"]), range(2)))
    assert all(r.status_code == 200 for r in tasks), [r.text for r in tasks]
    assert tasks[0].json()["data"] == tasks[1].json()["data"]
    with app.state.sessions() as tx:
        assert tx.scalar(select(func.count()).select_from(Checkin)) == 1


def test_http_plan_validation_update_and_rollback(api):
    app, client, seed, tokens, h = api
    elder = seed["elder"]["elder_id"]
    body = {"name": "用户药物", "dose_display": "用户既定用量", "start_date": "2026-10-30",
            "end_date": "2026-10-30", "schedule": {"mode": "fixed", "slots": [{"slot_id": "morning", "local_time": "09:00"}]}}
    headers = {**tokens["elder"], "Idempotency-Key": "plan"}
    result = client.post(f"/api/v1/elders/{elder}/medication-plans", json=body, headers=headers)
    assert result.status_code == 201, result.text
    plan_id = result.json()["data"]["plan_id"]
    update_url = f"/api/v1/medication-plans/{plan_id}"
    invalid = {"expected_version": 1, "patch": {"start_date": "2026-10-31"}}
    assert client.put(update_url, json=invalid, headers=headers).status_code == 422
    valid = {"expected_version": 1, "patch": {"notes": "核对后的备注"}}
    good = client.put(update_url, json=valid, headers=headers)
    assert good.status_code == 200, good.text
    assert good.json()["data"]["version"] == 2
    # Failed validation was not cached as a successful idempotency result.
    stale = client.put(update_url, json=valid, headers={**headers, "Idempotency-Key": "stale"})
    assert stale.status_code == 409


def test_http_memory_failure_rolls_back_record_and_idempotency(api):
    app, client, seed, tokens, h = api
    elder = seed["elder"]["elder_id"]
    body = {"type": "diet", "occurred_at": h.clock.now().isoformat(),
            "payload": {"meal_slot": "lunch", "foods": ["豆腐"]}}
    url = f"/api/v1/elders/{elder}/checkins"
    headers = {**tokens["elder"], "Idempotency-Key": "one"}
    first = client.post(url, json=body, headers=headers).json()["data"]
    correction = {"expected_version": 1, "payload": {"meal_slot": "lunch", "foods": ["粥"]}}
    h.memory.fail = True
    failed = client.put(f'/api/v1/checkins/{first["checkin_id"]}', json=correction, headers=headers)
    assert failed.status_code == 500
    h.memory.fail = False
    recovered = client.put(f'/api/v1/checkins/{first["checkin_id"]}', json=correction, headers=headers)
    assert recovered.status_code == 200, recovered.text
    assert recovered.json()["data"]["version"] == 2


def test_real_a_onboarding_imports_plans_and_history_once(api):
    app, client, seed, tokens, h = api
    created = client.post("/api/v1/demo/experiences", json={"scenario": "diabetes_daily"},
        headers={"Idempotency-Key": "health-demo"})
    assert created.status_code == 201, created.text
    demo = created.json()["data"]
    account = demo["elder_account"]
    challenge = client.post("/api/v1/auth/code", json=account).json()["data"]["challenge_id"]
    login = client.post("/api/v1/auth/login", json={**account, "challenge_id": challenge, "code": "123456"})
    headers = {"Authorization": "Bearer " + login.json()["data"]["access_token"], "Idempotency-Key": "draft"}
    elder = demo["elder_id"]
    draft = client.post(f"/api/v1/elders/{elder}/onboarding/match", headers=headers,
        json={"sample_identity_key": "community_sample_001"})
    assert draft.status_code == 200, draft.text
    data = draft.json()["data"]
    body = {"draft_id": data["draft_id"], "profile": data["profile_draft"],
        "medication_plans": data["medication_plan_drafts"], "expected_version": 1}
    confirm = client.post(f"/api/v1/elders/{elder}/onboarding/confirm", headers=headers, json=body)
    assert confirm.status_code == 200, confirm.text
    with app.state.sessions() as tx:
        count = tx.scalar(select(func.count()).select_from(Checkin).where(Checkin.elder_id == elder))
        assert count > 14
    replay = client.post(f"/api/v1/elders/{elder}/onboarding/confirm", headers=headers, json=body)
    assert replay.status_code == 200 and replay.json()["data"] == confirm.json()["data"]
    with app.state.sessions() as tx:
        assert tx.scalar(select(func.count()).select_from(Checkin).where(Checkin.elder_id == elder)) == count
