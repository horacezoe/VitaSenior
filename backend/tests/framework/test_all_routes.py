"""Every P0 placeholder receives an authorized schema-valid request (no fake 200)."""
import pytest
from app.core.uow import UnitOfWork
from app.models.identity import MediaAsset, ChangeProposal
from app.models.health import MedicationPlan, Checkin, Notification
from app.models.agent import AgentTurn, AgentAction
from datetime import date

CASES = [
('DEMO01','post','/demo/experiences',{},'elder'),
('ONB01','post','/elders/{elder}/onboarding/match',{'sample_identity_key':'sample'},'elder'),
('ONB02','post','/elders/{elder}/onboarding/confirm',{'draft_id':'draft','profile':{'display_name':'老人'},'medication_plans':[],'expected_version':1},'elder'),
('PROF01','get','/elders/{elder}/profile',None,'elder'),
('PROF02','put','/elders/{elder}/profile',{'expected_version':1,'patch':{'medical_notes':'note'}},'elder'),
('BIND01','post','/elders/{elder}/binding-codes',None,'elder'),
('BIND02','post','/family-bindings/preview',{'code':'0012'},'bound_child'),
('BIND03','post','/family-bindings',{'code':'0012','relationship':'子女'},'bound_child'),
('BIND04','get','/me/elders',None,'bound_child'),
('MEDIA01','post','/media','multipart','elder'),
('MEDIA02','get','/media/asset',None,'elder'),
('MEDIA03','get','/media/asset/content',None,'elder'),
('CHANGE01','post','/elders/{elder}/change-proposals',{'target_type':'profile','target_id':'{elder}','operation':'update','base_version':1,'patch':{'medical_notes':'note'}},'bound_child'),
('CHANGE02','get','/elders/{elder}/change-proposals',None,'bound_child'),
('CHANGE03','get','/change-proposals/proposal',None,'elder'),
('CHANGE04','post','/change-proposals/proposal/decision',{'decision':'reject'},'elder'),
('PLAN01','get','/elders/{elder}/medication-plans',None,'bound_child'),
('PLAN02','post','/elders/{elder}/medication-plans',{'name':'demo','dose_display':'provided','schedule':{'mode':'fixed','slots':[{'slot_id':'morning','local_time':'08:00'}]},'start_date':'2026-10-30'},'elder'),
('PLAN03','put','/medication-plans/plan',{'expected_version':1,'patch':{'notes':'note'}},'elder'),
('SET01','get','/elders/{elder}/reminder-settings',None,'bound_child'),
('SET02','put','/elders/{elder}/reminder-settings',{'expected_version':1,'patch':{'voice_enabled':True}},'elder'),
('TASK01','get','/elders/{elder}/tasks?date=2026-10-30',None,'elder'),
('REC01','get','/elders/{elder}/checkins?date=2026-10-30',None,'elder'),
('REC02','post','/elders/{elder}/checkins',{'type':'exercise','occurred_at':'2026-10-30T04:00:00Z','payload':{'activity':'散步','duration_minutes':20}},'elder'),
('REC03','put','/checkins/checkin',{'expected_version':1,'payload':{'activity':'散步','duration_minutes':30}},'elder'),
('REC04','delete','/checkins/checkin?expected_version=1',None,'elder'),
('DASH01','get','/elders/{elder}/dashboard',None,'bound_child'),
('CAL01','get','/elders/{elder}/calendar?month=2026-10',None,'bound_child'),
('REPORT01','get','/elders/{elder}/reports/daily?date=2026-10-30',None,'bound_child'),
('NOTI01','post','/elders/{elder}/presence',{'client_id':'page','visible':True},'elder'),
('NOTI02','get','/elders/{elder}/notifications',None,'bound_child'),
('NOTI03','post','/notifications/notice/events',{'event_id':'evt','event_type':'displayed'},'elder'),
('NOTI04','post','/elders/{elder}/family-reminders',{'category':'general','text':'关怀'},'bound_child'),
('AI01','post','/ai/asr',{'elder_id':'{elder}','audio_asset_id':'asset'},'elder'),
('AI02','post','/ai/tts',{'elder_id':'{elder}','text':'您好'},'elder'),
('AGENT01','post','/agent/turns',{'elder_id':'{elder}','client_turn_id':'client1','text':'您好'},'elder'),
('AGENT02','post','/agent/actions/action/decision',{'decision':'confirm'},'elder'),
('MEM01','get','/elders/{elder}/memory',None,'bound_child'),
('MEM02','put','/elders/{elder}/memory/entries/entry',{'expected_version':1,'text':'更正'},'elder'),
('MEM03','delete','/elders/{elder}/memory/entries/entry?expected_version=1',None,'elder'),
]

@pytest.fixture
def resources(env):
    app,client,clock,seed=env
    elder=seed['elder']['elder_id']
    with UnitOfWork(app.state.sessions) as u:
        tx=u.session
        tx.add(MediaAsset(id='asset',owner_user_id=seed['elder']['user_id'],elder_id=elder,purpose='agent_audio',mime_type='audio/wav',size_bytes=10,relative_path='test.wav',created_at=clock.now()))
        tx.add(MedicationPlan(id='plan',elder_id=elder,name='demo',dose_display='provided',schedule={'mode':'fixed','slots':[]},start_date=date(2026,10,30),updated_at=clock.now()))
        tx.add(Checkin(id='checkin',elder_id=elder,type='exercise',local_date=date(2026,10,30),occurred_at=clock.now(),payload_json={'activity':'walk','duration_minutes':20},created_at=clock.now(),updated_at=clock.now()))
        tx.add(ChangeProposal(id='proposal',elder_id=elder,created_by=seed['bound_child']['user_id'],target_type='profile',target_id=elder,operation='update',base_version=1,patch={'medical_notes':'note'}))
        tx.add(AgentTurn(id='turn',elder_id=elder,actor_user_id=seed['elder']['user_id'],conversation_id='conv',client_turn_id='ct',request_json={},response_json={},created_at=clock.now()))
        tx.flush()
        tx.add(Notification(id='notice',elder_id=elder,source_key='fixture-notice',kind='profile_change',title='fixture',text='fixture',due_at=clock.now(),proposal_id='proposal'))
        tx.add(AgentAction(id='action',elder_id=elder,turn_id='turn',type='record_diet',payload_json={},expires_at=clock.now()))
        tx.flush()
        u.commit()
    return elder

@pytest.mark.parametrize('operation,method,path,body,account',CASES,ids=[c[0] for c in CASES])
def test_all_placeholders(operation,method,path,body,account,env,tokens,resources):
    app,client,clock,seed=env
    path='/api/v1'+path.format(elder=resources)
    import json
    kwargs={'headers':tokens[account]}
    if body=='multipart':
        kwargs.update(files={'file':('test.wav',b'RIFF-test','audio/wav')},data={'purpose':'agent_audio','elder_id':resources})
    elif body is not None:
        kwargs['json']=json.loads(json.dumps(body).replace('{elder}',resources))
    response=client.request(method,path,**kwargs)
    assert response.status_code==501,(operation,response.text)
    assert response.json()['error']['code']=='MODULE_NOT_IMPLEMENTED'
    assert 'data' not in response.json()

@pytest.mark.parametrize('kind,path,method,body',[
('checkin','/checkins/checkin','put',{'expected_version':1,'payload':{'activity':'walk','duration_minutes':30}}),
('plan','/medication-plans/plan','put',{'expected_version':1,'patch':{'notes':'x'}}),
('proposal','/change-proposals/proposal','get',None),
('notification','/notifications/notice/events','post',{'event_id':'evt','event_type':'displayed'}),
('action','/agent/actions/action/decision','post',{'decision':'confirm'}),
('media','/media/asset','get',None),
])
def test_resource_guards(kind,path,method,body,env,tokens,resources):
    app,client,clock,seed=env
    kwargs={'headers':tokens['unbound_child']}
    if body is not None:kwargs['json']=body
    r=client.request(method,'/api/v1'+path,**kwargs)
    assert r.status_code==404,r.text
