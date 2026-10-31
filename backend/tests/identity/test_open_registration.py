"""New phones authenticate without inheriting another person's community facts."""
from sqlalchemy import func, select

from app.models.identity import User, ElderProfile, AuthSession
from app.models.health import Checkin, MedicationPlan


def challenge(client, phone="13800000000", role="elder"):
    account = {"phone": phone, "role": role}
    response = client.post("/api/v1/auth/code", json=account)
    assert response.status_code == 200, response.text
    return {**account, "challenge_id": response.json()["data"]["challenge_id"]}


def login(client, account):
    response = client.post("/api/v1/auth/login", json={**account, "code": "123456"})
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    return data, {"Authorization": "Bearer " + data["access_token"]}


def test_new_elder_verifies_then_manually_confirms_empty_profile(env):
    app, client, _, _ = env
    account = challenge(client)
    with app.state.sessions() as tx:
        user = tx.scalar(select(User).where(User.phone == account["phone"]))
        assert tx.scalar(select(ElderProfile).where(ElderProfile.owner_user_id == user.id)) is None
    invalid = client.post("/api/v1/auth/login", json={**account, "code": "000000"})
    assert invalid.status_code == 401
    with app.state.sessions() as tx:
        assert tx.scalar(select(func.count()).select_from(AuthSession)) == 0
        assert tx.scalar(select(ElderProfile).where(ElderProfile.owner_user_id == user.id)) is None

    data, auth = login(client, account)
    elder = data["elder_id"]
    assert elder and data["bound_elders"] == []
    profile = client.get(f"/api/v1/elders/{elder}/profile", headers=auth).json()["data"]
    assert profile["onboarding_status"] == "draft"
    assert profile["conditions"] == profile["allergies"] == []
    assert profile["birth_date"] is None and profile["medical_notes"] == ""
    matched = client.post(f"/api/v1/elders/{elder}/onboarding/match", json={"mode": "auto"},
                          headers={**auth, "Idempotency-Key": "new-match"})
    assert matched.status_code == 200, matched.text
    draft = matched.json()["data"]
    assert draft["match_status"] == "not_found"
    assert draft["medication_plan_drafts"] == []
    # A new account must not use the compatibility key to borrow a sample identity.
    denied = client.post(f"/api/v1/elders/{elder}/onboarding/match",
                         json={"sample_identity_key": "community_sample_001"},
                         headers={**auth, "Idempotency-Key": "other-person"})
    assert denied.status_code == 403
    fields = {**draft["profile_draft"], "display_name": "自行填写的称呼"}
    confirmed = client.post(f"/api/v1/elders/{elder}/onboarding/confirm",
                            headers={**auth, "Idempotency-Key": "new-confirm"},
                            json={"draft_id": draft["draft_id"], "profile": fields,
                                  "medication_plans": [], "expected_version": profile["version"]})
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["data"]["source"] == "user_confirmed"
    # Repeat login keeps the same account and the saved profile.
    again, again_auth = login(client, challenge(client))
    assert again["user"]["user_id"] == data["user"]["user_id"]
    assert again["elder_id"] == elder
    saved = client.get(f"/api/v1/elders/{elder}/profile", headers=again_auth).json()["data"]
    assert saved["onboarding_status"] == "confirmed" and saved["display_name"] == fields["display_name"]
    assert saved["version"] == 2
    with app.state.sessions() as tx:
        assert tx.scalar(select(func.count()).select_from(Checkin).where(Checkin.elder_id == elder)) == 0
        assert tx.scalar(select(func.count()).select_from(MedicationPlan).where(MedicationPlan.elder_id == elder)) == 0


def test_new_child_has_no_elder_profile_or_implicit_family_access(env):
    app, client, _, seed = env
    data, auth = login(client, challenge(client, "13800000001", "child"))
    assert data["elder_id"] is None and data["bound_elders"] == []
    assert client.get(f"/api/v1/elders/{seed['elder']['elder_id']}/profile", headers=auth).status_code == 403
    with app.state.sessions() as tx:
        assert tx.scalar(select(ElderProfile).where(ElderProfile.owner_user_id == data["user"]["user_id"])) is None


def test_new_phone_keeps_challenge_ownership_expiry_and_role_checks(env):
    app, client, clock, _ = env
    first = challenge(client)
    other = challenge(client, "13800000002")
    assert client.post("/api/v1/auth/login", json={**first, "phone": other["phone"], "code": "123456"}).status_code == 401
    assert client.post("/api/v1/auth/code", json={"phone": first["phone"], "role": "child"}).status_code == 401
    clock.advance(seconds=301)
    expired = client.post("/api/v1/auth/login", json={**first, "code": "123456"})
    assert expired.status_code == 401 and expired.json()["error"]["code"] == "CHALLENGE_EXPIRED"
    valid = challenge(client)
    login(client, valid)
    assert client.post("/api/v1/auth/login", json={**valid, "code": "123456"}).status_code == 401
    with app.state.sessions() as tx:
        assert tx.scalar(select(func.count()).select_from(User).where(User.phone == first["phone"])) == 1
