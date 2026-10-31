"""C acceptance against the default A composition and real A/B/C ports."""
from datetime import datetime, timezone, timedelta
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, func

from app.core.clock import FakeClock, local_date
from app.core.uow import UnitOfWork
from app.core.errors import AppError
from app.contracts.context import Actor
from app.contracts.media import GeneratedAudio, SpokenNotice
from app.main import create_app
from app.core.config import Settings
from app.models.agent import AgentTurn, AgentAction
from app.models.health import Checkin as CheckinRow
from app.models.identity import ElderProfile
from app.providers.mock_audio import FIXTURES
from app.providers.proposal_notice import ProposalFixtureTTS, prepare_proposal_notice
from app.schemas.agent import MemoryEntry
from app.schemas.common import SourceRef
from app.schemas.enums import Role
from app.schemas.health import MedicationPlanWrite
from app.schemas.identity import ProfileProposal, ChangeDecision
from app.seed import framework_seed

PROPOSAL_TEXT='【模拟】孩子申请将医疗备注修改为“补充社区复查记录”。如不同意，请明确拒绝。'


@pytest.fixture
def live(tmp_path):
    clock=FakeClock(datetime(2026,10,30,4,tzinfo=timezone.utc))
    app=create_app(Settings(data_dir=tmp_path/'default',database_url=None,scanner_enabled=False),clock=clock)
    with TestClient(app,raise_server_exceptions=False) as client:
        seed=framework_seed(app.state.sessions,clock)
        headers={}
        for name,account in seed.items():
            body={k:account[k] for k in ['phone','role']}
            challenge=client.post('/api/v1/auth/code',json=body).json()['data']['challenge_id']
            response=client.post('/api/v1/auth/login',json={**body,'challenge_id':challenge,'code':'123456'})
            assert response.status_code==200,response.text
            headers[name]={'Authorization':'Bearer '+response.json()['data']['access_token']}
        yield app,client,clock,seed,headers


def send(live,text,client_id,fixture=None,context=None):
    _,client,_,seed,headers=live
    body={'elder_id':seed['elder']['elder_id'],'client_turn_id':client_id,'text':text,
          'mock_fixture_id':fixture,'context':context or {}}
    return client.post('/api/v1/agent/turns',headers={**headers['elder'],'Idempotency-Key':client_id},json=body)


def test_default_wiring_runtime_and_all_seven_c_routes(live):
    app,client,clock,seed,headers=live
    assert app.state.agent.memory is app.state.services.memory
    for service in [app.state.agent,app.state.services.memory,app.state.services.checkins,
                    app.state.services.medication,app.state.services.reports]:
        assert service.clock is clock
    runtime=client.get('/api/v1/runtime',headers=headers['elder'])
    assert runtime.status_code==200,runtime.text
    assert runtime.json()['data']['providers']=={'chat':'mock','asr':'mock','tts':'mock'}
    for op in ['AI01','AI02','AGENT01','AGENT02','MEM01','MEM02','MEM03','CHANGE04']:
        assert runtime.json()['data']['capabilities'][op] is True
    assert runtime.json()['data']['capabilities']['NOTI03'] is True


@pytest.mark.parametrize('outcome',['unplayed','reject','timeout'])
def test_full_spoken_proposal_and_c_decision_use_real_a_b_state(live,outcome):
    app,client,clock,seed,headers=live
    owner=Actor(seed['elder']['user_id'],Role.elder)
    child=Actor(seed['bound_child']['user_id'],Role.child)
    elder=seed['elder']['elder_id']
    # Exact full-content speech is prepared OUTSIDE any DB transaction. The
    # default CHANGE01 HTTP cue is intentionally not treated as this evidence.
    spoken=app.state.agent_tts.synthesize(PROPOSAL_TEXT)
    assert spoken.content==(FIXTURES/'proposal_change_example.wav').read_bytes()
    with UnitOfWork(app.state.sessions) as unit:
        proposal=app.state.services.changes.create(unit.session,child,elder,
            ProfileProposal(target_type='profile',target_id=elder,operation='update',base_version=1,
                            patch={'medical_notes':'补充社区复查记录'}),clock.now(),
            notice=SpokenNotice(text=PROPOSAL_TEXT,
                                audio=GeneratedAudio(spoken.content,spoken.mime_type,spoken.duration_ms)))
        unit.commit()
    with UnitOfWork(app.state.sessions,write=False) as unit:
        notice=app.state.services.notifications.query(unit.session,owner,elder).items[0]
        content=app.state.services.media.open_content(unit.session,owner,notice.audio_asset_id)
    assert content.path.read_bytes()==spoken.content
    clock.advance(seconds=120)
    app.state.scanner.tick()
    with UnitOfWork(app.state.sessions,write=False) as unit:
        current=app.state.services.changes.read(unit.session,owner,proposal.proposal_id)
        assert current.status=='pending_notice' and current.auto_apply_at is None
    if outcome=='unplayed':
        return
    from app.schemas.health import PresenceWrite, NotificationEvent
    # Use genuine client event semantics at the port, not a model-produced
    # playback receipt. B's HTTP flags are still owned by B.
    for kind in ['displayed','answered','playback_completed']:
        if kind=='playback_completed':clock.advance(seconds=spoken.duration_ms/1000)
        with UnitOfWork(app.state.sessions) as unit:
            app.state.services.notifications.presence(unit.session,owner,elder,PresenceWrite(client_id='player',visible=True))
            event=app.state.services.notifications.handle_event(unit.session,owner,notice.notification_id,
                NotificationEvent(event_id='actual-player-'+kind,event_type=kind),clock.now())
            unit.commit()
    assert event.change_proposal.status=='awaiting_decision'
    assert event.change_proposal.auto_apply_at==clock.now()+timedelta(seconds=60)
    if outcome=='reject':
        rejected=send(live,'拒绝修改','reject-real',context={'notification_id':notice.notification_id})
        assert rejected.status_code==201,rejected.text
        assert rejected.json()['data']['actions'][0]['status']=='confirmed'
    clock.advance(seconds=61)
    app.state.scanner.tick()
    with UnitOfWork(app.state.sessions,write=False) as unit:
        result=app.state.services.changes.read(unit.session,owner,proposal.proposal_id)
        profile=app.state.services.profile.read(unit.session,owner,elder)
        assert result.status==('rejected' if outcome=='reject' else 'applied')
        assert profile.version==(1 if outcome=='reject' else 2)
        if outcome=='timeout':assert result.applied_by=='timeout' and profile.medical_notes=='补充社区复查记录'
        assert unit.session.scalar(select(func.count()).select_from(CheckinRow))==0


def test_actual_b_correction_invalidates_pattern_in_new_conversation(live):
    app,_,clock,seed,_=live
    owner=Actor(seed['elder']['user_id'],Role.elder)
    elder=seed['elder']['elder_id']
    from pydantic import TypeAdapter
    from app.schemas.health import CheckinWrite
    with UnitOfWork(app.state.sessions) as unit:
        records=[]
        for index in range(3):
            body=TypeAdapter(CheckinWrite).validate_python({'type':'diet','occurred_at':clock.now()-timedelta(days=index),
                                                          'payload':{'meal_slot':'lunch','foods':['青菜']}})
            records.append(app.state.services.checkins.create_or_update(unit.session,owner,elder,body))
        entry=MemoryEntry(entry_id='verified-routine',kind='meal_routine',text='三次午餐都记录了青菜',
                          source_type='observed_pattern',source_ids=[SourceRef(type='checkin',id=r.checkin_id,version=r.version) for r in records],
                          created_at=clock.now(),updated_at=clock.now())
        app.state.services.memory.remember_pattern(unit.session,owner,elder,entry,records)
        unit.commit()
    before=send(live,'你观察到什么规律','before-correction')
    assert before.status_code==201 and '三次午餐' in before.json()['data']['reply']['text']
    with UnitOfWork(app.state.sessions) as unit:
        app.state.services.checkins.cancel(unit.session,owner,elder,records[0].checkin_id,records[0].version)
        unit.commit()
    after=send(live,'你观察到什么规律','after-correction')
    assert after.status_code==201,after.text
    assert '还没有足够' in after.json()['data']['reply']['text']
    with UnitOfWork(app.state.sessions,write=False) as unit:
        assert app.state.services.memory.context(unit.session,owner,elder).entries==[]


def test_default_change_http_notification_reads_actual_patch_values(live):
    """A narrates every submitted field, so the default HTTP notification text must
    carry the actual value (this was a strict xfail owned by A)."""
    _, client, _, seed, headers = live
    elder = seed['elder']['elder_id']
    created = client.post(f'/api/v1/elders/{elder}/change-proposals',
        headers={**headers['bound_child'], 'Idempotency-Key': 'actual-spoken-patch'},
        json={'target_type': 'profile', 'target_id': elder, 'operation': 'update',
              'base_version': 1, 'patch': {'medical_notes': '补充社区复查记录'}})
    assert created.status_code == 201, created.text
    notices = client.get(f'/api/v1/elders/{elder}/notifications', headers=headers['elder'])
    assert notices.status_code == 200, notices.text
    notice = next(n for n in notices.json()['data']['items']
                  if n['proposal_id'] == created.json()['data']['proposal_id'])
    assert '补充社区复查记录' in notice['text'], notice


@pytest.mark.parametrize('kind', ['profile', 'reminder_settings'])
def test_c_full_content_notice_drives_real_ports_and_shared_system_authorization(live, kind):
    import json
    from pydantic import TypeAdapter
    from app.schemas.identity import ChangeProposalWrite
    from app.schemas.health import NotificationEvent, PresenceWrite
    app, _, clock, seed, _ = live
    elder = seed['elder']['elder_id']
    owner = Actor(seed['elder']['user_id'], Role.elder)
    child = Actor(seed['bound_child']['user_id'], Role.child)
    case = next(c for c in json.loads((FIXTURES/'proposal_cases.json').read_text(encoding='utf-8'))
                if c['body']['target_type'] == kind)
    case['body']['target_id'] = elder
    body = TypeAdapter(ChangeProposalWrite).validate_python(case['body'])
    # All content/provider/file preparation precedes the first write UoW.
    text, spoken = prepare_proposal_notice(body, tts=ProposalFixtureTTS())
    assert spoken is not None
    with UnitOfWork(app.state.sessions) as unit:
        proposal = app.state.services.changes.create(unit.session, child, elder, body, clock.now(), notice=spoken)
        unit.commit()
    with UnitOfWork(app.state.sessions, write=False) as unit:
        notice = next(n for n in app.state.services.notifications.query(unit.session, owner, elder).items
                      if n.notification_id == proposal.notification_id)
        assert notice.text == text and notice.audio_asset_id
        content = app.state.services.media.open_content(unit.session, owner, notice.audio_asset_id)
    assert content.path.read_bytes() == spoken.audio.content
    clock.advance(seconds=120)
    app.state.scanner.tick()
    with UnitOfWork(app.state.sessions, write=False) as unit:
        assert app.state.services.changes.read(unit.session, owner, proposal.proposal_id).auto_apply_at is None
    for event_type in ['displayed', 'answered', 'playback_completed']:
        if event_type == 'playback_completed':
            clock.advance(seconds=spoken.audio.duration_ms/1000)
        with UnitOfWork(app.state.sessions) as unit:
            app.state.services.notifications.presence(unit.session, owner, elder, PresenceWrite(client_id='full-player', visible=True))
            result = app.state.services.notifications.handle_event(unit.session, owner, notice.notification_id,
                NotificationEvent(event_id='full-'+event_type, event_type=event_type), clock.now())
            unit.commit()
    assert result.change_proposal.auto_apply_at == clock.now()+timedelta(seconds=60)
    # Observe the real AccessPort during timeout invalidation; do not construct
    # an elder Actor, bypass authorization or swap the business implementation.
    seen = []
    original = app.state.services.memory.access
    class ObservedAccess:
        def require_elder_access(self, tx, actor, elder_id, write_scope='read'):
            seen.append(actor)
            return original.require_elder_access(tx, actor, elder_id, write_scope)
    app.state.services.memory.access = ObservedAccess()
    clock.advance(seconds=61)
    app.state.scanner.tick()
    from app.contracts.context import SYSTEM_ACTOR
    assert seen and all(actor == SYSTEM_ACTOR for actor in seen)
    with UnitOfWork(app.state.sessions, write=False) as unit:
        settled = app.state.services.changes.read(unit.session, owner, proposal.proposal_id)
        assert settled.status == 'applied' and settled.applied_by == 'timeout'
        assert unit.session.scalar(select(func.count()).select_from(CheckinRow)) == 0
        if kind == 'profile':
            assert app.state.services.profile.read(unit.session, owner, elder).medical_notes == '补充社区复查记录'
        else:
            assert app.state.services.medication.settings(unit.session, owner, elder).exercise.enabled is False


def test_unknown_proposal_speech_stays_unplayed_until_explicit_elder_decision(live):
    from app.schemas.health import NotificationEvent, PresenceWrite
    app, _, clock, seed, _ = live
    elder = seed['elder']['elder_id']
    owner = Actor(seed['elder']['user_id'], Role.elder)
    child = Actor(seed['bound_child']['user_id'], Role.child)
    body = ProfileProposal(target_type='profile', target_id=elder, operation='update', base_version=1,
                           patch={'medical_notes': '没有匹配音频的另一条实际修改'})
    text, spoken = prepare_proposal_notice(body, tts=ProposalFixtureTTS())
    assert '另一条实际修改' in text and spoken is None
    with UnitOfWork(app.state.sessions) as unit:
        proposal = app.state.services.changes.create(unit.session, child, elder, body, clock.now(), notice=spoken)
        app.state.services.notifications.presence(unit.session, owner, elder, PresenceWrite(client_id='no-audio', visible=True))
        unit.commit()
    # No audio means no complete playback evidence, even with an active client.
    with pytest.raises(AppError) as exc:
        with UnitOfWork(app.state.sessions) as unit:
            app.state.services.notifications.handle_event(unit.session, owner, proposal.notification_id,
                NotificationEvent(event_id='no-audio-play', event_type='playback_completed'), clock.now())
            unit.commit()
    assert exc.value.status in {409, 422}
    clock.advance(seconds=600)
    app.state.scanner.tick()
    with UnitOfWork(app.state.sessions) as unit:
        current = app.state.services.changes.read(unit.session, owner, proposal.proposal_id)
        assert current.status == 'pending_notice' and current.auto_apply_at is None
        accepted = app.state.services.changes.decide(unit.session, owner, proposal.proposal_id,
                                                    ChangeDecision(decision='accept'), clock.now())
        assert accepted.status == 'applied' and accepted.applied_by == 'elder_accept'
        unit.commit()


def test_client_cannot_self_declare_agent_provenance_and_direct_checkin_stays_user(live):
    _, client, clock, seed, headers = live
    elder = seed['elder']['elder_id']
    body = {'type': 'exercise', 'occurred_at': clock.now().isoformat(),
            'payload': {'activity': '散步', 'duration_minutes': 20}}
    response = client.post(f'/api/v1/elders/{elder}/checkins',
        headers={**headers['elder'], 'Idempotency-Key': 'spoof-source'},
        json={**body, 'source': 'agent_confirmed'})
    assert response.status_code == 422, response.text
    direct = client.post(f'/api/v1/elders/{elder}/checkins',
        headers={**headers['elder'], 'Idempotency-Key': 'direct-user'}, json=body)
    assert direct.status_code == 201, direct.text
    assert direct.json()['data']['source'] == 'user'
