"""Real A + C HTTP tests; B dependencies are never silently replaced."""
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, func

from app.core.clock import FakeClock
from app.core.config import Settings
from app.core.errors import AppError
from app.core.uow import UnitOfWork
from app.main import create_app
from app.composition import compose
from app.models.agent import AgentTurn, AgentAction, MemoryDocument
from app.models.identity import ElderProfile, MediaAsset, BindingCode, IdempotencyRecord
from app.models.identity import ChangeProposal as ProposalRow
from app.models.health import Notification as NoticeRow
from app.contracts.context import Actor
from app.schemas.enums import Role
from app.providers.mock_audio import FIXTURES
from app.providers.mock_audio import MockASR, MockTTS
from app.providers.mock_chat import MockUnderstanding
from app.services.agent_service import AgentService
from app.services.memory_service import MemoryService
from app.seed import framework_seed


@pytest.fixture
def api(tmp_path):
    clock = FakeClock(datetime(2026, 10, 30, 4, tzinfo=timezone.utc))
    settings=Settings(data_dir=tmp_path/'api', database_url=None, scanner_enabled=False)
    services=compose(clock,settings)
    memory=MemoryService(clock,services.access)
    services=replace(services,memory=memory)
    # Real B services, with the same C memory/Clock that production A will wire.
    services.checkins.memory=memory
    services.medication.memory=memory
    services.reports.memory=memory
    services.changes.bind(medication=services.medication,notifications=services.notifications,memory=memory)
    app = create_app(settings, clock=clock, services=services)
    # Explicit integration-test injection until A applies the shared wiring.
    # Normal runtime is guarded 501; no test substitute is installed in product.
    app.state.agent=AgentService(clock,services,memory)
    app.state.agent_chat=MockUnderstanding()
    app.state.agent_asr=MockASR()
    app.state.agent_tts=MockTTS()
    with TestClient(app, raise_server_exceptions=False) as client:
        seed = framework_seed(app.state.sessions, clock)
        headers = {}
        for name, account in seed.items():
            body = {k: account[k] for k in ['phone','role']}
            challenge = client.post('/api/v1/auth/code',json=body).json()['data']['challenge_id']
            result = client.post('/api/v1/auth/login',json={**body,'challenge_id':challenge,'code':'123456'})
            assert result.status_code == 200, result.text
            headers[name] = {'Authorization':'Bearer '+result.json()['data']['access_token']}
        yield app, client, clock, seed, headers


def hdr(api, key='one', account='elder'):
    return {**api[4][account],'Idempotency-Key':key}


def turn(api, fixture='exercise_walk', client_id='turn-1', key=None, **kwargs):
    body={'elder_id':api[3]['elder']['elder_id'],'client_turn_id':client_id,'text':'我散步了20分钟',
          'mock_fixture_id':fixture, **kwargs}
    return api[1].post('/api/v1/agent/turns',json=body,headers=hdr(api,key or client_id))


def count(api, model):
    with api[0].state.sessions() as tx:return tx.scalar(select(func.count()).select_from(model))


def upload(api, *, account='elder', filename='exercise_input.wav', raw=None, mime='audio/wav'):
    raw = raw if raw is not None else (FIXTURES/filename).read_bytes()
    response=api[1].post('/api/v1/media',headers=hdr(api,'upload-'+account,account),
                         data={'purpose':'agent_audio','elder_id':api[3][account]['elder_id']},
                         files={'file':(filename,raw,mime)})
    assert response.status_code==201,response.text
    return response.json()['data']['asset_id']


def test_memory_endpoints_and_idempotent_versioned_corrections(api):
    app,client,clock,seed,_=api
    result=turn(api,'explicit_preference',text='我喜欢清淡饮食')
    assert result.status_code==201,result.text
    data=result.json()['data']
    assert data['providers']['chat']=='mock' and data['memory']['changed']
    path=f"/api/v1/elders/{seed['elder']['elder_id']}/memory"
    doc=client.get(path,headers=hdr(api)).json()['data']
    assert doc['version']==2 and len(doc['entries'])==1
    assert doc['updated_at'].startswith('2026-10-30T04:00:00')
    assert app.state.agent.memory.clock is clock and app.state.services.memory.clock is clock
    entry=doc['entries'][0]['entry_id']
    body={'expected_version':2,'text':'不喜欢甜食'}
    updated=client.put(path+'/entries/'+entry,json=body,headers=hdr(api,'edit'))
    assert updated.status_code==200,updated.text
    assert updated.json()['data']['version']==3
    replay=client.put(path+'/entries/'+entry,json=body,headers=hdr(api,'edit'))
    assert replay.status_code==200 and replay.json()['data']==updated.json()['data']
    conflict=client.put(path+'/entries/'+entry,json={**body,'text':'异体'},headers=hdr(api,'edit'))
    assert conflict.status_code==409 and conflict.json()['error']['code']=='IDEMPOTENCY_CONFLICT'
    removed=client.delete(path+'/entries/'+entry+'?expected_version=3',headers=hdr(api,'delete'))
    assert removed.status_code==200 and removed.json()['data']['entries']==[]
    assert client.delete(path+'/entries/'+entry+'?expected_version=3',headers=hdr(api,'delete')).status_code==200
    query=turn(api,None,'query',text='我喜欢什么',conversation_id='new-conversation')
    assert query.status_code==201 and '目前没有已保存' in query.json()['data']['reply']['text']


def test_real_profile_port_confirmation_and_replay(api):
    _,client,_,seed,_=api
    result=turn(api,'profile_update')
    assert result.status_code==201,result.text
    action=result.json()['data']['actions'][0]
    assert action['status']=='pending'
    assert set(action['preview']['patch'])=={'medical_notes'}
    path=f"/api/v1/agent/actions/{action['action_id']}/decision"
    confirmed=client.post(path,json={'decision':'confirm'},headers=hdr(api,'confirm'))
    assert confirmed.status_code==200,confirmed.text
    assert confirmed.json()['data']['status']=='confirmed'
    assert confirmed.json()['data']['result']['version']==2
    assert client.post(path,json={'decision':'confirm'},headers=hdr(api,'confirm-again')).json()['data']==confirmed.json()['data']
    profile=client.get(f"/api/v1/elders/{seed['elder']['elder_id']}/profile",headers=hdr(api))
    assert profile.json()['data']['version']==2
    assert count(api,AgentAction)==1


def test_unimplemented_b_write_rolls_back_and_cancel_still_works(api):
    app,client,_,_,_=api
    class MissingCheckins:
        def create_or_update(self,*args):
            raise AppError(501,'MODULE_NOT_IMPLEMENTED','Explicit missing B test port')
    app.state.agent.services=replace(app.state.agent.services,checkins=MissingCheckins())
    result=turn(api)
    assert result.status_code==201,result.text
    action_id=result.json()['data']['actions'][0]['action_id']
    path=f'/api/v1/agent/actions/{action_id}/decision'
    failed=client.post(path,json={'decision':'confirm'},headers=hdr(api,'confirm'))
    assert failed.status_code==501 and failed.json()['error']['code']=='MODULE_NOT_IMPLEMENTED'
    with app.state.sessions() as tx:
        row=tx.get(AgentAction,action_id)
        assert row.status=='pending' and row.result_json is None
        assert tx.scalar(select(IdempotencyRecord).where(IdempotencyRecord.key=='confirm')) is None
    cancelled=client.post(path,json={'decision':'cancel'},headers=hdr(api,'cancel'))
    assert cancelled.status_code==200 and cancelled.json()['data']['status']=='cancelled'
    assert client.post(path,json={'decision':'confirm'},headers=hdr(api,'retry')).json()['error']['code']=='ACTION_CANCELLED'


def test_real_binding_tool_and_client_turn_id_conflicts(api):
    result=turn(api,'binding_code')
    assert result.status_code==201,result.text
    assert result.json()['data']['actions'][0]['status']=='confirmed'
    assert count(api,BindingCode)==1
    assert turn(api,'binding_code',key='new-http-key').json()['data']==result.json()['data']
    assert count(api,BindingCode)==1
    different=turn(api,'binding_code',text='不同请求',key='different-body')
    assert different.status_code==409 and different.json()['error']['code']=='IDEMPOTENCY_CONFLICT'
    samekeynewturn=turn(api,'binding_code',client_id='different-client',key='turn-1')
    assert samekeynewturn.status_code==409 and count(api,BindingCode)==1


def test_real_asr_and_tts_media_ticket_roundtrip(api):
    _,client,_,seed,_=api
    asset=upload(api)
    recognized=client.post('/api/v1/ai/asr',headers=hdr(api),json={
        'elder_id':seed['elder']['elder_id'],'audio_asset_id':asset,'mock_fixture_id':'exercise_walk'})
    assert recognized.status_code==200,recognized.text
    assert recognized.json()['data']=={'transcript':'我散步了20分钟。','language':'zh-CN','provider':'mock','is_mock':True}
    text='【模拟】要记下这次散步20分钟吗？'
    speech=client.post('/api/v1/ai/tts',headers=hdr(api),json={'elder_id':seed['elder']['elder_id'],'text':text})
    assert speech.status_code==200,speech.text
    media=speech.json()['data']['audio_asset']
    assert media['duration_ms']>0
    content=client.get(media['content_url'])
    assert content.status_code==200 and content.headers['content-type'].startswith('audio/wav')
    assert content.content==(FIXTURES/'exercise_reply.wav').read_bytes()
    greeting=client.post('/api/v1/ai/tts',headers=hdr(api),json={'elder_id':seed['elder']['elder_id'],'text':'您好'})
    assert greeting.status_code==200,greeting.text
    assert client.get(greeting.json()['data']['audio_asset']['content_url']).content==(FIXTURES/'greeting.wav').read_bytes()
    before=count(api,MediaAsset)
    unavailable=client.post('/api/v1/ai/tts',headers=hdr(api),json={'elder_id':seed['elder']['elder_id'],'text':'没有对应固定录音的新提案内容'})
    assert unavailable.status_code==501 and count(api,MediaAsset)==before


def test_audio_only_turn_and_text_correction_precedence(api):
    app,_,_,_,_=api
    asset=upload(api)
    response=turn(api,'exercise_walk',audio_asset_id=asset,text=None)
    assert response.status_code==201,response.text
    data=response.json()['data']
    assert data['transcript']=='我散步了20分钟。'
    assert data['providers']=={'chat':'mock','asr':'mock','tts':'mock'}
    assert data['reply']['audio_asset_id'] and data['degraded']==[]
    class NoASR:
        def transcribe(self,*args):raise AssertionError('Corrected text must not run ASR')
    app.state.agent_asr=NoASR()
    text=turn(api,'explicit_preference','corrected',audio_asset_id=asset,text='我喜欢清淡饮食')
    assert text.status_code==201,text.text
    assert text.json()['data']['providers']['asr']=='not_used'
    # Same client_turn_id skips all providers and retains the original result.
    assert turn(api,'exercise_walk',key='audio-replay',audio_asset_id=asset,text=None).json()['data']==data


def test_unknown_audio_and_other_elders_media_are_rejected(api):
    _,client,_,seed,_=api
    raw=bytearray((FIXTURES/'exercise_input.wav').read_bytes());raw[-2]^=1
    unknown=upload(api,raw=bytes(raw))
    response=client.post('/api/v1/ai/asr',headers=hdr(api),json={'elder_id':seed['elder']['elder_id'],'audio_asset_id':unknown})
    assert response.status_code==422
    foreign=upload(api,account='stranger_elder')
    denied=client.post('/api/v1/ai/asr',headers=hdr(api),json={'elder_id':seed['elder']['elder_id'],'audio_asset_id':foreign})
    assert denied.status_code==404
    assert count(api,AgentTurn)==0


def test_http_permission_matrix_and_action_expiry(api):
    _,client,clock,seed,_=api
    path=f"/api/v1/elders/{seed['elder']['elder_id']}/memory"
    assert client.get(path).status_code==401
    assert client.get(path,headers=hdr(api,account='bound_child')).status_code==200
    assert client.get(path,headers=hdr(api,account='unbound_child')).status_code==403
    assert client.get(path,headers=hdr(api,account='stranger_elder')).status_code==403
    write=client.put(path+'/entries/missing',headers=hdr(api,account='bound_child'),json={'expected_version':1,'text':'改动'})
    assert write.status_code==403
    result=turn(api)
    action=result.json()['data']['actions'][0]['action_id']
    decide=f'/api/v1/agent/actions/{action}/decision'
    assert client.post(decide,headers=hdr(api,account='stranger_elder'),json={'decision':'confirm'}).status_code==404
    clock.advance(seconds=601)
    expired=client.post(decide,headers=hdr(api),json={'decision':'confirm'})
    assert expired.status_code==409 and expired.json()['error']['code']=='ACTION_EXPIRED'


@pytest.mark.parametrize('change',['writer','session_expiry','profile_version','memory_version'])
def test_provider_has_no_write_lock_and_fresh_write_rechecks(api,change):
    app,_,clock,seed,_=api
    original=app.state.agent_chat
    class Provider:
        def plan(self,request,snapshot):
            with UnitOfWork(app.state.sessions) as unit:
                if change=='profile_version':
                    unit.session.get(ElderProfile,seed['elder']['elder_id']).version+=1
                else:
                    elder=seed['elder']['elder_id'] if change=='memory_version' else seed['stranger_elder']['elder_id']
                    unit.session.add(MemoryDocument(elder_id=elder,version=2,entries_json=[],revisions_json=[],updated_at=clock.now()))
                unit.commit()
            if change=='session_expiry':clock.advance(seconds=48*3600+1)
            return original.plan(request,snapshot)
    app.state.agent_chat=Provider()
    response=turn(api)
    expected={'writer':201,'session_expiry':401,'profile_version':409,'memory_version':409}[change]
    assert response.status_code==expected,response.text
    if change!='writer':assert count(api,AgentTurn)==count(api,AgentAction)==0


def test_model_failures_no_writes_and_tts_failure_preserves_text(api):
    app,_,_,_,_=api
    timed=turn(api,'provider_timeout')
    assert timed.status_code==504 and count(api,AgentTurn)==count(api,AgentAction)==0
    original=app.state.agent_chat
    class Invalid:
        def plan(self,request,snapshot):return replace(original.plan(request,snapshot),scene='not-a-scene')
    app.state.agent_chat=Invalid()
    invalid=turn(api)
    assert invalid.status_code==502 and count(api,AgentTurn)==0
    app.state.agent_chat=original
    class BrokenTTS:
        def synthesize(self,*args):raise AppError(502,'PROVIDER_ERROR','Injected TTS failure')
    app.state.agent_tts=BrokenTTS()
    text=turn(api)
    assert text.status_code==201,text.text
    assert text.json()['data']['degraded']==['tts_unavailable']
    assert text.json()['data']['reply'].get('audio_asset_id') is None
    assert count(api,MediaAsset)==0


def test_next_turn_confirms_real_a_profile_action(api):
    _,client,_,seed,_=api
    first=turn(api,'profile_update',conversation_id='profile-conversation')
    assert first.status_code==201,first.text
    confirm=turn(api,None,'confirmation',text='确认',conversation_id='profile-conversation')
    assert confirm.status_code==201,confirm.text
    assert confirm.json()['data']['actions'][0]['status']=='confirmed'
    profile=client.get(f"/api/v1/elders/{seed['elder']['elder_id']}/profile",headers=hdr(api))
    assert profile.json()['data']['version']==2


def test_actual_a_proposal_decision_via_resolved_notification(api):
    app,client,clock,seed,_=api
    class ClosingNotices:
        """Only B's close hook is replaced; A query/read/decide are real."""
        def mark_proposal_handled(self,tx,notification_id):
            tx.get(NoticeRow,notification_id).task_state='handled'
    app.state.services.changes.bind(notifications=ClosingNotices())
    with UnitOfWork(app.state.sessions) as unit:
        before=app.state.services.profile.read(unit.session,Actor(seed['elder']['user_id'],Role.elder),seed['elder']['elder_id'])
        proposal=ProposalRow(id='proposal-fixture',elder_id=seed['elder']['elder_id'],
                             created_by=seed['bound_child']['user_id'],target_type='profile',
                             target_id=seed['elder']['elder_id'],operation='update',base_version=1,
                             patch={'medical_notes':'拟修改'},before_snapshot=before.model_dump(mode='json'),
                             status='pending_notice',created_at=clock.now())
        unit.session.add(proposal);unit.session.flush()
        notice=NoticeRow(id='notice-fixture',elder_id=seed['elder']['elder_id'],source_key='fixture',
                         kind='profile_change',title='修改通知',text='待明确决定',due_at=clock.now(),proposal_id=proposal.id)
        unit.session.add(notice);unit.session.flush();proposal.notification_id=notice.id
        unit.commit()
    rejected=turn(api,'reject_change',text='拒绝这次修改',context={'notification_id':'notice-fixture'})
    assert rejected.status_code==201,rejected.text
    assert rejected.json()['data']['actions'][0]['status']=='confirmed'
    with app.state.sessions() as tx:
        proposal=tx.get(ProposalRow,'proposal-fixture')
        assert proposal.status=='rejected' and proposal.auto_apply_at is None
        assert tx.get(NoticeRow,'notice-fixture').task_state=='handled'
        assert tx.get(ElderProfile,seed['elder']['elder_id']).version==1


def test_default_unwired_deployment_stays_501_and_capability_false(tmp_path):
    clock=FakeClock(datetime(2026,10,30,4,tzinfo=timezone.utc))
    app=create_app(Settings(data_dir=tmp_path/'unwired',database_url=None,scanner_enabled=False),clock=clock)
    with TestClient(app,raise_server_exceptions=False) as client:
        seed=framework_seed(app.state.sessions,clock)
        account={'phone':seed['elder']['phone'],'role':'elder'}
        challenge=client.post('/api/v1/auth/code',json=account).json()['data']['challenge_id']
        login=client.post('/api/v1/auth/login',json={**account,'challenge_id':challenge,'code':'123456'})
        headers={'Authorization':'Bearer '+login.json()['data']['access_token'],'Idempotency-Key':'unwired'}
        elder=seed['elder']['elder_id']
        for path,body in [('/ai/tts',{'elder_id':elder,'text':'你好'}),
                          ('/agent/turns',{'elder_id':elder,'client_turn_id':'u','text':'您好'})]:
            result=client.post('/api/v1'+path,json=body,headers=headers)
            assert result.status_code==501,result.text
        runtime=client.get('/api/v1/runtime',headers=headers)
        assert runtime.status_code==200,runtime.text
        assert all(not runtime.json()['data']['capabilities'][key] for key in ['AI01','AI02','AGENT01','AGENT02','MEM01','MEM02','MEM03'])


def test_agent_cannot_manufacture_player_receipts():
    with pytest.raises(AppError) as exc:
        AgentService._validate_payload('respond_notification',{
            'notification_id':'n','event':{'event_id':'e','event_type':'playback_completed'}})
    assert exc.value.status==422


def test_actual_b_confirmation_writes_once_and_report_uses_same_record(api):
    from app.models.health import Checkin
    app,client,clock,seed,_=api
    prepared=turn(api,'exercise_walk')
    assert prepared.status_code==201,prepared.text
    assert count(api,Checkin)==0
    action=prepared.json()['data']['actions'][0]['action_id']
    decision=f'/api/v1/agent/actions/{action}/decision'
    confirmed=client.post(decision,json={'decision':'confirm'},headers=hdr(api,'real-b-confirm'))
    assert confirmed.status_code==200,confirmed.text
    assert count(api,Checkin)==1
    assert client.post(decision,json={'decision':'confirm'},headers=hdr(api,'real-b-repeat')).json()['data']==confirmed.json()['data']
    assert count(api,Checkin)==1
    with UnitOfWork(app.state.sessions) as unit:
        report=app.state.services.reports.daily(unit.session,Actor(seed['elder']['user_id'],Role.elder),
                                                seed['elder']['elder_id'],clock.now().date())
        assert report.records.exercise[0].checkin_id==confirmed.json()['data']['result']['checkin_id']
        assert report.completion.progress.exercise.completed==1
        unit.commit()
    # Current frozen B port defaults to user; C must not directly rewrite B's
    # table to pretend the missing agent_confirmed source argument is wired.
    assert confirmed.json()['data']['result']['source']=='user'
