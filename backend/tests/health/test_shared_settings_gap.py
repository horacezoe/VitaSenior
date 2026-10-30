"""Executable A-owned integration gap; expected failure is never a pass.

Remove the strict xfail after A routes approved settings through B's frozen
update_settings port, preserving the caller's tx/version/authority.
"""
import pytest

from .test_activation import production, get, headers


class SharedSettingsGap(AssertionError):
    pass


@pytest.mark.xfail(strict=True, raises=SharedSettingsGap,
    reason="A ChangeService._apply settings branch bypasses MedicationPort.update_settings")
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
    actual = get(p, "reports/daily?date=2026-10-31")["completion"]["progress"]["exercise"]["expected"]
    if actual == 1:
        raise SharedSettingsGap("Proposal applied, settings disabled, but existing future exercise goal still counts as 1")
    assert actual == 0
