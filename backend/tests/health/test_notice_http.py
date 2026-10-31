"""CHANGE01 speech through NOTI03, using the real default A/B/C services."""
from datetime import timedelta
import hashlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.main import create_app
from app.models.health import Checkin
from .test_activation import production, headers, get


@pytest.mark.parametrize("outcome", ["unplayed", "reject", "timeout"])
def test_full_content_http_playback_and_restarted_scanner(production, outcome):
    p = production
    result = p.client.post(f"/api/v1/elders/{p.elder}/change-proposals",
        headers=headers(p, "full-proposal", "bound_child"),
        json={"target_type": "profile", "target_id": p.elder, "operation": "update",
              "base_version": 1, "patch": {"medical_notes": "补充社区复查记录"}})
    assert result.status_code == 201, result.text
    proposal = result.json()["data"]
    path = f'/api/v1/change-proposals/{proposal["proposal_id"]}'
    notice = next(n for n in get(p, "notifications")["items"]
                  if n["proposal_id"] == proposal["proposal_id"])
    assert "补充社区复查记录" in notice["text"] and "60秒" in notice["text"]
    catalog = Path(__file__).resolve().parents[2] / "fixtures" / "agent" / "proposal_manifest.json"
    sample = next(r for r in json.loads(catalog.read_text(encoding="utf-8-sig"))
                  if r["text"] == notice["text"])
    asset = p.client.get(f'/api/v1/media/{notice["audio_asset_id"]}', headers=p.tokens["elder"])
    assert asset.status_code == 200, asset.text
    audio = p.client.get(asset.json()["data"]["content_url"])
    assert audio.status_code == 200
    assert hashlib.sha256(audio.content).hexdigest() == sample["sha256"]
    events = f'/api/v1/notifications/{notice["notification_id"]}/events'

    def current():
        response = p.client.get(path, headers=p.tokens["elder"])
        assert response.status_code == 200, response.text
        return response.json()["data"]

    def emit(kind):
        visible = p.client.post(f"/api/v1/elders/{p.elder}/presence", headers=p.tokens["elder"],
            json={"client_id": "http-player", "visible": True})
        assert visible.status_code == 200, visible.text
        response = p.client.post(events, headers=headers(p, kind),
            json={"event_id": kind, "event_type": kind})
        assert response.status_code == 200, response.text
        return response.json()["data"]

    p.clock.advance(seconds=120)
    p.app.state.scanner.tick()
    assert current()["status"] == "pending_notice" and current()["auto_apply_at"] is None
    emit("displayed")
    emit("answered")
    p.clock.advance(seconds=120)
    p.app.state.scanner.tick()
    assert current()["auto_apply_at"] is None
    if outcome != "unplayed":
        played = emit("playback_completed")
        assert played["change_proposal"]["status"] == "awaiting_decision"
        deadline = current()["auto_apply_at"]
        assert deadline == (p.clock.now() + timedelta(seconds=60)).isoformat().replace("+00:00", "Z")
        p.clock.advance(seconds=5)
        assert emit("playback_completed") == played  # same event/key, same deadline
        if outcome == "reject":
            decision = p.client.post(path + "/decision", headers=headers(p, "reject"),
                json={"decision": "reject"})
            assert decision.status_code == 200, decision.text
    p.clock.advance(seconds=61)
    # A new app/scanner recovers the persisted state; it uses the same injected clock.
    restarted = create_app(p.app.state.settings, clock=p.clock)
    with TestClient(restarted) as client:
        restarted.state.scanner.tick()
        state = client.get(path, headers=p.tokens["elder"])
        assert state.status_code == 200, state.text
        assert state.json()["data"]["status"] == {"unplayed": "pending_notice", "reject": "rejected", "timeout": "applied"}[outcome]
        with restarted.state.sessions() as tx:
            assert tx.scalar(select(func.count()).select_from(Checkin)) == 0


def test_unmatched_speech_cannot_arm_a_window_via_http(production):
    p = production
    result = p.client.post(f"/api/v1/elders/{p.elder}/change-proposals",
        headers=headers(p, "text-only", "bound_child"),
        json={"target_type": "profile", "target_id": p.elder, "operation": "update",
              "base_version": 1, "patch": {"medical_notes": "另一项没有匹配录音的真实修改"}})
    assert result.status_code == 201, result.text
    proposal = result.json()["data"]
    notice = next(n for n in get(p, "notifications")["items"]
                  if n["proposal_id"] == proposal["proposal_id"])
    assert notice["audio_asset_id"] is None and "另一项" in notice["text"]
    assert p.client.post(f"/api/v1/elders/{p.elder}/presence", headers=p.tokens["elder"],
        json={"client_id": "text-player", "visible": True}).status_code == 200
    for kind in ["displayed", "answered", "playback_completed"]:
        response = p.client.post(f'/api/v1/notifications/{notice["notification_id"]}/events',
            headers=headers(p, kind), json={"event_id": kind, "event_type": kind})
        assert response.status_code == (409 if kind == "playback_completed" else 200), response.text
    p.clock.advance(seconds=600)
    p.app.state.scanner.tick()
    state = p.client.get(f'/api/v1/change-proposals/{proposal["proposal_id"]}', headers=p.tokens["elder"])
    assert state.json()["data"]["status"] == "pending_notice"
    assert state.json()["data"]["auto_apply_at"] is None
