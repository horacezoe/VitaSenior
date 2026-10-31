"""Community sources, server-owned demo identity and atomic onboarding over HTTP."""
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.core.errors import AppError
from app.core.config import Settings
from app.core.db import Base, build_engine, sessions
from app.core.uow import UnitOfWork
from app.fixtures.identity import SAMPLE_PROFILES, UNMATCHED_PERSONA
from app.main import create_app
from app.models.identity import CommunityRecord, DemoIdentity, ElderProfile, User
from app.models.health import Checkin, MedicationPlan, Notification, DailyTask
from app.seed import seed_community_records


def auth_header(client, phone, role):
    account = {'phone': phone, 'role': role}
    challenge = client.post('/api/v1/auth/code', json=account)
    assert challenge.status_code == 200, challenge.text
    response = client.post('/api/v1/auth/login', json={**account, 'code': '123456',
                           'challenge_id': challenge.json()['data']['challenge_id']})
    assert response.status_code == 200, response.text
    return {'Authorization': 'Bearer ' + response.json()['data']['access_token']}


def hdr(auth, key):
    return {**auth, 'Idempotency-Key': key}


def family(env, persona):
    app, client, clock, _ = env
    response = client.post('/api/v1/demo/experiences', json={'persona_id': persona},
                           headers={'Idempotency-Key': f'family-{persona}'})
    assert response.status_code == 201, response.text
    demo = response.json()['data']
    return demo, auth_header(client, demo['elder_account']['phone'], 'elder')


def match(client, demo, auth, body=None, key='auto'):
    response = client.post(f"/api/v1/elders/{demo['elder_id']}/onboarding/match",
                           json=body or {}, headers=hdr(auth, key))
    assert response.status_code == 200, response.text
    return response.json()['data']


def confirm(client, demo, auth, draft, plans=None, key='confirm'):
    return client.post(f"/api/v1/elders/{demo['elder_id']}/onboarding/confirm", headers=hdr(auth, key),
                       json={'draft_id': draft['draft_id'], 'profile': draft['profile_draft'],
                             'medication_plans': draft['medication_plan_drafts'] if plans is None else plans,
                             'expected_version': 1})


def test_catalog_only_contains_fictional_summaries_and_seeding_preserves_rows(env):
    app, client, clock, _ = env
    response = client.get('/api/v1/demo/personas')
    assert response.status_code == 200
    data = response.json()['data']
    assert data['is_mock'] is True and len(data['items']) == 14
    assert sum(bool(p['conditions']) for p in data['items']) == 12
    assert all(set(p) == {'persona_id', 'display_name', 'conditions', 'has_community_record'} for p in data['items'])
    with UnitOfWork(app.state.sessions) as uow:
        row = uow.session.get(CommunityRecord, 'community_sample_002')
        source = deepcopy(row.sample_json)
        source['profile']['medical_notes'] = '保留既有社区数据'
        row.sample_json = source
        uow.commit()
    with UnitOfWork(app.state.sessions) as uow:
        seed_community_records(uow.session)
        seed_community_records(uow.session)
        uow.commit()
    with app.state.sessions() as tx:
        assert tx.scalar(select(func.count()).select_from(CommunityRecord)) == 13
        assert tx.get(CommunityRecord, 'community_sample_002').sample_json['profile']['medical_notes'] == '保留既有社区数据'


@pytest.mark.parametrize('persona', [*SAMPLE_PROFILES, UNMATCHED_PERSONA])
def test_each_persona_auto_matches_and_confirms_consistent_history(env, persona):
    app, client, clock, _ = env
    demo, auth = family(env, persona)
    draft = match(client, demo, auth)
    assert draft['is_mock'] is True and draft['match_basis'] == 'demo_account'
    source = SAMPLE_PROFILES.get(persona)
    assert draft['match_status'] == ('matched' if source else 'not_found')
    assert match(client, demo, auth, key='refresh')['draft_id'] == draft['draft_id']
    with app.state.sessions() as tx:
        elder = tx.get(ElderProfile, demo['elder_id'])
        assert elder.onboarding_status == 'draft' and elder.profile_json['display_name'] == '演示老人'
        identity = tx.get(DemoIdentity, elder.owner_user_id)
        assert identity.phone == demo['elder_account']['phone'] and identity.demo_id == demo['demo_id']
    if source:
        assert draft['profile_draft']['display_name'] == source['profile']['display_name']
        assert draft['profile_draft']['conditions'] == source['profile']['conditions']
        assert draft['record_number'] == source['record_number']
    else:
        draft['profile_draft']['display_name'] = '手工建档老人'
    response = confirm(client, demo, auth, draft)
    assert response.status_code == 200, response.text
    assert response.json()['data']['onboarding_status'] == 'confirmed'
    with app.state.sessions() as tx:
        plans = list(tx.scalars(select(MedicationPlan).where(MedicationPlan.elder_id == demo['elder_id'])))
        records = list(tx.scalars(select(Checkin).where(Checkin.elder_id == demo['elder_id'])))
        med_records = [r for r in records if r.type == 'medication']
        assert len(plans) == len(draft['medication_plan_drafts'])
        assert len(med_records) == len(plans) * 14
        assert (len(records) > 14) if source else not records
        assert all(r.source == 'demo_seed' for r in records)
        by_id = {p.id: p for p in plans}
        for record in med_records:
            plan = by_id[record.payload_json['plan_id']]
            assert plan.start_date <= record.local_date
            task = tx.get(DailyTask, record.task_id)
            assert task.plan_id == plan.id and task.plan_snapshot['name'] == plan.name
            if plan.schedule['mode'] == 'after_meal':
                meal = next(r for r in records if r.type == 'diet' and r.local_date == record.local_date
                            and r.slot_key == 'lunch')
                assert record.occurred_at == meal.occurred_at + timedelta(minutes=30)
        assert tx.scalar(select(func.count()).select_from(Notification).where(Notification.elder_id == demo['elder_id'])) == 0
        before = len(records)
    # Same key replays; new matches cannot replace a confirmed profile.
    assert confirm(client, demo, auth, draft).status_code == 200
    blocked = client.post(f"/api/v1/elders/{demo['elder_id']}/onboarding/match", json={}, headers=hdr(auth, 'after-confirm'))
    assert blocked.status_code == 409
    with app.state.sessions() as tx:
        assert tx.scalar(select(func.count()).select_from(Checkin).where(Checkin.elder_id == demo['elder_id'])) == before


@pytest.mark.parametrize('change,expected', [('reorder', 42), ('remove', 28), ('edit', 28), ('duplicate', 28)])
def test_history_follows_exact_retained_plans_with_stable_references(env, change, expected):
    app, client, clock, _ = env
    demo, auth = family(env, 'community_sample_012')
    draft = match(client, demo, auth)
    plans = deepcopy(draft['medication_plan_drafts'])
    if change == 'reorder':
        plans.reverse()
    elif change == 'remove':
        plans.pop(0)
    elif change == 'edit':
        plans[0]['dose_display'] = '本人修改的演示用量'
    else:
        plans.append(deepcopy(plans[0]))
    response = confirm(client, demo, auth, draft, plans)
    assert response.status_code == 200, response.text
    with app.state.sessions() as tx:
        records = list(tx.scalars(select(Checkin).where(Checkin.elder_id == demo['elder_id'], Checkin.type == 'medication')))
        assert len(records) == expected
        for record in records:
            row = tx.get(MedicationPlan, record.payload_json['plan_id'])
            assert row.dose_display == '演示档案中的既定用量'
            if change != 'reorder':
                assert row.name != '演示药品A'


def test_manual_override_survives_refresh_and_restart_without_importing_history(env):
    app, client, clock, _ = env
    demo, auth = family(env, 'community_sample_004')
    matched = match(client, demo, auth)
    manual = match(client, demo, auth, {'mode': 'manual'}, key='manual')
    assert manual['draft_id'] != matched['draft_id'] and manual['match_status'] == 'not_found'
    assert manual['match_basis'] == 'manual' and not manual['medication_plan_drafts']
    assert match(client, demo, auth, key='refresh')['draft_id'] == manual['draft_id']
    restarted = create_app(app.state.settings, clock=clock)
    with TestClient(restarted) as next_client:
        assert match(next_client, demo, auth, key='restart')['draft_id'] == manual['draft_id']
        manual['profile_draft']['display_name'] = '本人填写'
        response = confirm(next_client, demo, auth, manual)
        assert response.status_code == 200, response.text
    with app.state.sessions() as tx:
        assert tx.scalar(select(func.count()).select_from(Checkin).where(Checkin.elder_id == demo['elder_id'])) == 0
        assert tx.get(CommunityRecord, 'community_sample_004').sample_json['profile']['display_name'] == '王伯伯'


def test_identity_cannot_be_overridden_by_a_sample_key_or_another_actor(env):
    app, client, clock, seed = env
    demo, auth = family(env, 'community_sample_002')
    path = f"/api/v1/elders/{demo['elder_id']}/onboarding/match"
    denied = client.post(path, json={'sample_identity_key': 'community_sample_001'}, headers=hdr(auth, 'wrong-key'))
    assert denied.status_code == 403
    child = auth_header(client, demo['child_account']['phone'], 'child')
    stranger = auth_header(client, seed['stranger_elder']['phone'], 'elder')
    assert client.post(path, json={}, headers={'Idempotency-Key': 'no-token'}).status_code == 401
    for actor in (child, stranger):
        assert client.post(path, json={}, headers=hdr(actor, 'wrong-actor')).status_code == 403
    assert match(client, demo, auth)['profile_draft']['display_name'] == '张伯伯'


def test_unknown_persona_creates_no_accounts_and_legacy_account_can_fill_manually(env):
    app, client, clock, seed = env
    response = client.post('/api/v1/demo/experiences', json={'persona_id': 'does-not-exist'},
                           headers={'Idempotency-Key': 'bad-persona'})
    assert response.status_code == 422
    with app.state.sessions() as tx:
        assert tx.scalar(select(func.count()).select_from(User)) == 4
    auth = auth_header(client, seed['elder']['phone'], 'elder')
    draft = match(client, seed['elder'], auth)
    assert draft['match_status'] == 'not_found'


def test_history_failure_rolls_back_profile_plans_and_keeps_draft(env):
    app, client, clock, _ = env
    demo, auth = family(env, 'community_sample_012')
    draft = match(client, demo, auth)
    class BrokenHistory:
        def import_demo_history(self, *args, **kwargs):
            raise AppError(501, 'MODULE_NOT_IMPLEMENTED', 'injected history failure')
    app.state.services = replace(app.state.services, history=BrokenHistory())
    assert confirm(client, demo, auth, draft).status_code == 501
    with app.state.sessions() as tx:
        row = tx.get(ElderProfile, demo['elder_id'])
        assert row.onboarding_status == 'draft' and row.onboarding_draft['draft_id'] == draft['draft_id']
        assert tx.scalar(select(func.count()).select_from(MedicationPlan).where(MedicationPlan.elder_id == row.id)) == 0


def test_startup_adds_new_tables_to_existing_database_without_changing_profiles(tmp_path):
    directory = tmp_path / 'old-database'
    engine = build_engine(directory)
    # Reproduce the pre-feature schema: all original tables, neither new table.
    Base.metadata.create_all(engine, tables=[table for name, table in Base.metadata.tables.items()
                                            if name not in {'community_records', 'demo_identities'}])
    factory = sessions(engine)
    with UnitOfWork(factory) as uow:
        owner = User(id='old-user', phone='19900000009', role='elder', demo_id='demo_old')
        uow.session.add(owner)
        uow.session.flush()
        uow.session.add(ElderProfile(id='old-elder', owner_user_id=owner.id,
                                    profile_json={'display_name': '保留的老人档案', 'source': 'user_confirmed'},
                                    reminder_settings_json={}, onboarding_status='confirmed', version=7,
                                    updated_at=datetime(2026, 10, 30, tzinfo=timezone.utc)))
        uow.commit()
    engine.dispose()
    app = create_app(Settings(data_dir=directory, scanner_enabled=False, database_url=None))
    with TestClient(app) as client:
        assert client.get('/api/v1/demo/personas').status_code == 200
        with app.state.sessions() as tx:
            original = tx.get(ElderProfile, 'old-elder')
            assert original.profile_json['display_name'] == '保留的老人档案'
            assert original.onboarding_status == 'confirmed' and original.version == 7
            assert tx.scalar(select(func.count()).select_from(CommunityRecord)) == 13
            assert tx.scalar(select(func.count()).select_from(DemoIdentity)) == 0


def test_pre_upgrade_draft_does_not_guess_history_for_changed_plan(env):
    app, client, clock, _ = env
    demo, auth = family(env, 'community_sample_001')
    draft = match(client, demo, auth)
    with UnitOfWork(app.state.sessions) as uow:
        row = uow.session.get(ElderProfile, demo['elder_id'])
        old = dict(row.onboarding_draft)
        for key in ('history_key', 'medication_template_keys', 'result', 'profile_version'):
            old.pop(key)
        row.onboarding_draft = old
        uow.commit()
    changed = deepcopy(draft['medication_plan_drafts'])
    changed[0]['dose_display'] = '本人修改后的既定用量'
    assert confirm(client, demo, auth, draft, changed).status_code == 200
    with app.state.sessions() as tx:
        assert tx.scalar(select(func.count()).select_from(Checkin).where(
            Checkin.elder_id == demo['elder_id'], Checkin.type == 'medication')) == 0
