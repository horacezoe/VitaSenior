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
from app.contracts.media import GeneratedAudio
from app.main import create_app
from app.core.config import Settings
from app.models.agent import AgentTurn, AgentAction
from app.models.health import Checkin as CheckinRow
from app.models.identity import ElderProfile
from app.providers.mock_audio import FIXTURES
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
            audio=GeneratedAudio(spoken.content,spoken.mime_type,spoken.duration_ms))
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
