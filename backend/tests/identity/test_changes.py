"""CHANGE01-04: proposal window, single terminal state, cross-domain apply."""
from dataclasses import replace
from sqlalchemy import select, update
from fastapi.testclient import TestClient
from app.main import create_app
from app.contracts.context import Actor
from app.core.uow import UnitOfWork
from app.models.identity import ElderProfile, FamilyBinding
from app.schemas.enums import Role
from app.services.change_service import ChangeService
from conftest import hdr

def elder_actor(app, elder_id):
    with app.state.sessions() as tx:
        return Actor(tx.get(ElderProfile, elder_id).owner_user_id, Role.elder)

def play(app, proposal_id, elder_id):
    actor = elder_actor(app, elder_id)
    with UnitOfWork(app.state.sessions) as uow:
        result = app.state.services.changes.mark_played(uow.session, actor, proposal_id, app.state.clock.now())
        uow.commit()
    return result

def settle(app):
    with UnitOfWork(app.state.sessions) as uow:
        result = app.state.services.changes.apply_due(uow.session, app.state.clock.now())
        uow.commit()
    return result

def propose(demo, key, **overrides):
    body = {'target_type': 'profile', 'target_id': demo.elder_id, 'operation': 'update',
            'base_version': 1, 'patch': {'medical_notes': '补充社区复查记录'}, 'reason': '帮妈妈完善档案'}
    body.update(overrides)
    return demo.client.post(f'/api/v1/elders/{demo.elder_id}/change-proposals', headers=hdr(demo.child, key), json=body)

def decide(demo, proposal_id, decision, key='decide-1'):
    return demo.client.post(f'/api/v1/change-proposals/{proposal_id}/decision',
                            headers=hdr(demo.elder, key), json={'decision': decision})

def test_child_submit_only_writes_proposal_and_notification(demo, fakes):
    demo.bind_child()
    before = demo.client.get(f'/api/v1/elders/{demo.elder_id}/profile', headers=demo.elder).json()['data']
    created = propose(demo, 'c-1')
    assert created.status_code == 201, created.text
    proposal = created.json()['data']
    assert proposal['status'] == 'pending_notice'
    assert proposal['auto_apply_at'] is None and proposal['notified_at'] is None
    assert proposal['before_snapshot']['medical_notes'] == before['medical_notes']
    assert proposal['notification_id'] and proposal['created_by']
    assert len(fakes.notifications.enqueued) == 1
    notice = fakes.notifications.enqueued[0]
    assert notice.proposal_id == proposal['proposal_id'] and notice.task_state == 'open'
    after = demo.client.get(f'/api/v1/elders/{demo.elder_id}/profile', headers=demo.elder).json()['data']
    assert after['version'] == before['version'] and after['medical_notes'] == before['medical_notes']

def test_no_window_without_playback(demo, fakes, env):
    app, client, clock, seed = env
    demo.bind_child()
    proposal = propose(demo, 'c-2').json()['data']
    clock.advance(seconds=3600)
    assert settle(app) == []
    row = demo.client.get(f"/api/v1/change-proposals/{proposal['proposal_id']}", headers=demo.elder).json()['data']
    assert row['status'] == 'pending_notice' and row['auto_apply_at'] is None

def test_playback_arms_window_once(demo, fakes, env):
    app, client, clock, seed = env
    demo.bind_child()
    proposal = propose(demo, 'c-3').json()['data']
    armed = play(app, proposal['proposal_id'], demo.elder_id)
    assert armed.status == 'awaiting_decision'
    deadline = armed.auto_apply_at
    assert (deadline - clock.now()).total_seconds() == 60
    clock.advance(seconds=30)
    again = play(app, proposal['proposal_id'], demo.elder_id)
    assert again.auto_apply_at == deadline, 'a repeated receipt must not re-arm the window'

def test_settles_after_the_window_on_server_time(demo, fakes, env):
    app, client, clock, seed = env
    demo.bind_child()
    proposal = propose(demo, 'c-4').json()['data']
    play(app, proposal['proposal_id'], demo.elder_id)
    clock.advance(seconds=59)
    assert settle(app) == []
    clock.advance(seconds=2)
    settled = settle(app)
    assert [p.status for p in settled] == ['applied']
    assert settled[0].applied_by == 'timeout' and settled[0].applied_at is not None
    profile = demo.client.get(f'/api/v1/elders/{demo.elder_id}/profile', headers=demo.elder).json()['data']
    assert profile['version'] == 2 and profile['medical_notes'] == '补充社区复查记录'
    assert len(fakes.memory.invalidations) == 1
    source = fakes.memory.invalidations[0]['source']
    assert source.type == 'profile' and source.id == demo.elder_id and source.version == 2
    assert fakes.notifications.handled == [proposal['notification_id']]
    assert settle(app) == []   # idempotent: nothing left to apply

def test_reject_inside_the_window_keeps_the_target(demo, fakes, env):
    app, client, clock, seed = env
    demo.bind_child()
    proposal = propose(demo, 'c-5').json()['data']
    play(app, proposal['proposal_id'], demo.elder_id)
    clock.advance(seconds=30)
    rejected = decide(demo, proposal['proposal_id'], 'reject')
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()['data']['status'] == 'rejected'
    profile = demo.client.get(f'/api/v1/elders/{demo.elder_id}/profile', headers=demo.elder).json()['data']
    assert profile['version'] == 1 and profile['medical_notes'] == ''
    assert fakes.notifications.handled == [proposal['notification_id']]
    clock.advance(seconds=120)
    assert settle(app) == []
    again = decide(demo, proposal['proposal_id'], 'reject', key='decide-2')
    assert again.status_code == 409 and again.json()['error']['code'] == 'CHANGE_ALREADY_APPLIED'

def test_decision_after_the_deadline_cannot_undo_it(demo, fakes, env):
    app, client, clock, seed = env
    demo.bind_child()
    proposal = propose(demo, 'c-6').json()['data']
    play(app, proposal['proposal_id'], demo.elder_id)
    clock.advance(seconds=61)
    late = decide(demo, proposal['proposal_id'], 'reject')
    assert late.status_code == 409 and late.json()['error']['code'] == 'CHANGE_ALREADY_APPLIED'
    profile = demo.client.get(f'/api/v1/elders/{demo.elder_id}/profile', headers=demo.elder).json()['data']
    assert profile['version'] == 2 and profile['medical_notes'] == '补充社区复查记录'

def test_accept_is_idempotent(demo, fakes):
    demo.bind_child()
    proposal = propose(demo, 'c-7').json()['data']
    proposal_id = proposal['proposal_id']
    first = decide(demo, proposal_id, 'accept', key='acc-1')
    assert first.status_code == 200, first.text
    assert first.json()['data']['status'] == 'applied'
    assert first.json()['data']['applied_by'] == 'elder_accept'
    replay = decide(demo, proposal_id, 'accept', key='acc-1')
    assert replay.json()['data'] == first.json()['data']
    other_key = decide(demo, proposal_id, 'accept', key='acc-2')
    assert other_key.status_code == 409 and other_key.json()['error']['code'] == 'CHANGE_ALREADY_APPLIED'

def test_stale_base_version_becomes_conflicted(demo, fakes):
    demo.bind_child()
    proposal = propose(demo, 'c-8').json()['data']
    edited = demo.client.put(f'/api/v1/elders/{demo.elder_id}/profile', headers=hdr(demo.elder, 'self-edit'),
                             json={'expected_version': 1, 'patch': {'medical_notes': '老人自己先改了'}})
    assert edited.status_code == 200, edited.text
    decided = decide(demo, proposal['proposal_id'], 'accept')
    assert decided.status_code == 200, decided.text
    assert decided.json()['data']['status'] == 'conflicted'
    assert decided.json()['data']['conflict_reason'] == 'version_changed'
    profile = demo.client.get(f'/api/v1/elders/{demo.elder_id}/profile', headers=demo.elder).json()['data']
    assert profile['version'] == 2 and profile['medical_notes'] == '老人自己先改了'
    assert fakes.notifications.handled == [proposal['notification_id']]

def test_revoked_binding_is_not_silently_applied(demo, fakes, env):
    app, client, clock, seed = env
    demo.bind_child()
    proposal = propose(demo, 'c-9').json()['data']
    with UnitOfWork(app.state.sessions) as uow:
        uow.session.execute(update(FamilyBinding).where(FamilyBinding.elder_id == demo.elder_id,
                                                       FamilyBinding.status == 'active').values(status='revoked'))
        uow.commit()
    decided = decide(demo, proposal['proposal_id'], 'accept')
    assert decided.status_code == 200, decided.text
    assert decided.json()['data']['status'] == 'conflicted'
    assert decided.json()['data']['conflict_reason'] == 'binding_revoked'
    profile = demo.client.get(f'/api/v1/elders/{demo.elder_id}/profile', headers=demo.elder).json()['data']
    assert profile['version'] == 1

def test_medication_proposal_applies_through_the_b_port(demo, fakes):
    demo.bind_child()
    fakes.medication.seed_plan('plan_demo', demo.elder_id)
    created = propose(demo, 'c-10', target_type='medication_plan', target_id='plan_demo',
                      operation='update', base_version=1, patch={'notes': '新的用药说明'})
    assert created.status_code == 201, created.text
    proposal = created.json()['data']
    assert proposal['before_snapshot']['plan_id'] == 'plan_demo'
    applied = decide(demo, proposal['proposal_id'], 'accept')
    assert applied.status_code == 200 and applied.json()['data']['status'] == 'applied'
    call = fakes.medication.calls[0]
    assert call['operation'] == 'update' and call['target_id'] == 'plan_demo'
    assert call['expected_version'] == 1 and call['patch'].notes == '新的用药说明'
    assert fakes.medication.plans['plan_demo']['version'] == 2

def test_settings_proposal_bumps_the_profile_version(demo, fakes):
    demo.bind_child()
    created = propose(demo, 'c-11', target_type='reminder_settings', target_id=demo.elder_id,
                      operation='update', base_version=1, patch={'voice_enabled': False})
    assert created.status_code == 201, created.text
    assert created.json()['data']['before_snapshot']['voice_enabled'] is True
    applied = decide(demo, created.json()['data']['proposal_id'], 'accept')
    assert applied.status_code == 200 and applied.json()['data']['status'] == 'applied'
    profile = demo.client.get(f'/api/v1/elders/{demo.elder_id}/profile', headers=demo.elder).json()['data']
    assert profile['version'] == 2

def test_only_a_bound_child_proposes_and_only_the_elder_decides(demo, fakes):
    unbound = propose(demo, 'c-12')
    assert unbound.status_code == 403
    demo.bind_child()
    proposal = propose(demo, 'c-13').json()['data']
    # A child is not the owner: the framework answers 404 for a sub-resource it may
    # not act on, so no existence oracle leaks.
    as_child = demo.client.post(f"/api/v1/change-proposals/{proposal['proposal_id']}/decision",
                                headers=hdr(demo.child, 'child-decide'), json={'decision': 'accept'})
    assert as_child.status_code == 404
    still_pending = demo.client.get(f"/api/v1/change-proposals/{proposal['proposal_id']}", headers=demo.child)
    assert still_pending.json()['data']['status'] == 'pending_notice'
    # An elder cannot file a child proposal against their own profile.
    body = {'target_type': 'profile', 'target_id': demo.elder_id, 'operation': 'update',
            'base_version': 1, 'patch': {'medical_notes': 'x'}}
    elder_proposes = demo.client.post(f'/api/v1/elders/{demo.elder_id}/change-proposals',
                                      headers=hdr(demo.elder, 'c-14'), json=body)
    assert elder_proposes.status_code == 403

def test_list_and_read_are_shared_with_the_bound_child(demo, fakes):
    demo.bind_child()
    first = propose(demo, 'c-15').json()['data']
    propose(demo, 'c-16', patch={'medical_notes': '第二条'})
    listed = demo.client.get(f'/api/v1/elders/{demo.elder_id}/change-proposals?limit=1', headers=demo.child)
    assert listed.status_code == 200, listed.text
    page = listed.json()['data']
    assert len(page['items']) == 1 and page['next_cursor']
    page2 = demo.client.get(f"/api/v1/elders/{demo.elder_id}/change-proposals?limit=1&cursor={page['next_cursor']}", headers=demo.child)
    assert len(page2.json()['data']['items']) == 1
    assert page2.json()['data']['items'][0]['proposal_id'] != page['items'][0]['proposal_id']
    read_one = demo.client.get(f"/api/v1/change-proposals/{first['proposal_id']}", headers=demo.child)
    assert read_one.status_code == 200 and read_one.json()['data']['proposal_id'] == first['proposal_id']
    filtered = demo.client.get(f'/api/v1/elders/{demo.elder_id}/change-proposals?status=pending_notice', headers=demo.child)
    assert len(filtered.json()['data']['items']) == 2

def test_a_restart_resumes_the_persisted_window(demo, fakes, env):
    app, client, clock, seed = env
    demo.bind_child()
    proposal = propose(demo, 'c-17').json()['data']
    play(app, proposal['proposal_id'], demo.elder_id)
    deadline = demo.client.get(f"/api/v1/change-proposals/{proposal['proposal_id']}", headers=demo.elder).json()['data']['auto_apply_at']
    restarted = create_app(app.state.settings, clock=clock)
    with TestClient(restarted, raise_server_exceptions=False):
        restarted.state.services = replace(
            restarted.state.services,
            medication=fakes.medication, notifications=fakes.notifications, memory=fakes.memory,
            changes=ChangeService(clock, app.state.settings).bind(
                medication=fakes.medication, notifications=fakes.notifications, memory=fakes.memory))
        clock.advance(seconds=61)
        settled = settle(restarted)
        assert [p.status for p in settled] == ['applied']
        assert settled[0].applied_by == 'timeout'  # deadline came from SQLite, not a timer
    with app.state.sessions() as tx:
        assert tx.scalar(select(ElderProfile).where(ElderProfile.id == demo.elder_id)).version == 2
