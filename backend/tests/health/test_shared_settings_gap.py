"""Regression: an approved settings proposal must retire already-generated future
goals through B's frozen update_settings port.

This was a strict xfail owned by A. It is a plain test now: A routes the settings
branch through MedicationPort.update_settings, so B's implementation bumps the
profile version and re-times/retires future goals in the same transaction.
"""
from .test_activation import production, get, headers


def test_approved_settings_proposal_updates_existing_future_goals(production):
    p = production
    before = get(p, "reports/daily?date=2026-10-31")["completion"]["progress"]["exercise"]["expected"]
    assert before == 1
    created = p.client.post(f"/api/v1/elders/{p.elder}/change-proposals", headers=headers(p, "settings-proposal", "bound_child"),
        json={"target_type": "reminder_settings", "target_id": p.elder, "operation": "update", "base_version": 1,
              "patch": {"exercise": {"enabled": False, "local_time": "17:00"}}})
    assert created.status_code == 201, created.text
    proposal = created.json()["data"]
    decided = p.client.post(f'/api/v1/change-proposals/{proposal["proposal_id"]}/decision', headers=headers(p, "accept-settings"),
        json={"decision": "accept"})
    assert decided.status_code == 200 and decided.json()["data"]["status"] == "applied", decided.text
    assert get(p, "reminder-settings")["exercise"]["enabled"] is False
    # The port must also retire the already-generated future exercise goal.
    assert get(p, "reports/daily?date=2026-10-31")["completion"]["progress"]["exercise"]["expected"] == 0
