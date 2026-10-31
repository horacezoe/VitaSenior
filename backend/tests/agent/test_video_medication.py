"""Real HTTP workflow with explicit provider seams and isolated DB/FakeClock."""
from dataclasses import replace
import json
import httpx
import pytest
from sqlalchemy import select,func
from test_http import api,hdr
from test_f2_http import real_api,turn,upload,count
from test_real_understanding import candidate,response
from app.contracts.context import Actor
from app.core.uow import UnitOfWork
from app.core.config import Settings
from app.models.health import Checkin,SafetySignal,Notification
from app.schemas.enums import Role
from app.schemas.health import MedicationPlanWrite,DailyInsights
from app.providers.report_writer import MiMoReportWriter

TEXT=dict(warm_message='记录已整理。',elder_praise='每份记录都值得鼓励。',reminder='和家人聊聊。',diet_advice='核对记录。',exercise_advice='按自己节奏活动。',medication_advice='核对既定计划。')

def add_plan(api,name='测试片',mode='fixed'):
    app,_,clock,seed,_=api
    actor=Actor(seed['elder']['user_id'],Role.elder)
    schedule={'mode':'fixed','slots':[{'slot_id':'morning','local_time':'08:00'}]} if mode=='fixed' else {'mode':'after_meal','slots':[{'slot_id':'lunch','meal_slot':'lunch','delay_minutes':5}]}
    with UnitOfWork(app.state.sessions) as u:
        plan=app.state.services.medication.apply_change(u.session,actor,seed['elder']['elder_id'],'create',None,
            MedicationPlanWrite(name=name,dose_display='既定用量',start_date='2026-10-31',schedule=schedule),None)
        u.commit()
    return plan

@pytest.mark.parametrize('spoken',['我刚才把药吃了。','药我已经吃完了，帮我打卡。','我已经服药了。','帮我记录一下，我刚刚服用了测试片。','测试片吃过了。','我按计划吃药了。'])
def test_common_medication_speech_with_camera_is_not_a_meal(real_api,spoken):
    api,captured=real_api;add_plan(api);api[2].advance(seconds=86400)
    prepared=turn(api,text=spoken,image_asset_ids=[upload(api)])
    assert prepared.status_code==201,prepared.text
    data=prepared.json()['data'];assert data['scene']=='medication_checkin'
    action=data['actions'][0];assert action['type']=='record_medication' and action['status']=='pending'
    assert count(api,Checkin)==0 and not captured.calls
    done=turn(api,key='yes-med',text='确认。',conversation_id=data['conversation_id'],context={'pending_action_id':action['action_id']})
    assert done.status_code==201,done.text
    assert done.json()['data']['actions'][0]['status']=='confirmed' and count(api,Checkin)==1
    assert turn(api,key='yes-med',text='确认。',conversation_id=data['conversation_id'],context={'pending_action_id':action['action_id']}).status_code==201
    assert count(api,Checkin)==1
    with api[0].state.sessions() as tx:assert tx.scalar(select(Checkin)).source=='agent_confirmed'

@pytest.mark.parametrize('spoken',['我还没吃药。','我准备吃药。','我吃药了吗？','这盒药给你看看。','我要停药。'])
def test_no_medication_record_from_negation_question_future_or_camera(real_api,spoken):
    api,captured=real_api;add_plan(api);api[2].advance(seconds=86400)
    captured.handler=lambda req:response(candidate(intent='medication',foods=[],food_groups=[],reply='请核对药名。'))
    value=turn(api,text=spoken,image_asset_ids=[upload(api)])
    assert value.status_code==201,value.text
    assert not value.json()['data']['actions'] and count(api,Checkin)==0


def test_unknown_drug_is_not_bound_to_only_plan(real_api):
    api,_=real_api;add_plan(api);api[2].advance(seconds=86400)
    value=turn(api,text='我吃了不在计划里的药品。').json()['data']
    assert not value['actions'] and '没和既定计划对上' in value['reply']['text']
    assert count(api,Checkin)==0


def test_after_meal_intake_does_not_require_meal_checkin(real_api):
    api,_=real_api;add_plan(api,mode='after_meal');api[2].advance(seconds=86400)
    value=turn(api,text='我吃药了。').json()['data']
    assert value['actions'][0]['type']=='record_medication' and value['actions'][0]['status']=='pending'
    assert '不用再等' in value['reply']['text']
    assert count(api,Checkin)==0


def test_named_followup_without_word_medicine_keeps_true_target(real_api):
    api,_=real_api;one=add_plan(api,'甲片');add_plan(api,'乙片');api[2].advance(seconds=86400)
    first=turn(api,text='我已经吃药了。').json()['data']
    assert not first['actions']
    second=turn(api,key='name-only',text='甲片，早上那次。',conversation_id=first['conversation_id'])
    assert second.status_code==201,second.text
    assert second.json()['data']['actions'][0]['preview']['plan_id']==one.plan_id


def test_risk_question_uses_configured_report_llm_outside_write_tx_and_reaches_speech(real_api):
    api,captured=real_api;add_plan(api,'模型甲片');add_plan(api,'模型乙片');api[2].advance(seconds=86400)
    app=api[0];calls=[]
    def safety(request):
        # A concurrent write must remain possible during the model request.
        with UnitOfWork(app.state.sessions) as u:u.commit()
        payload=json.loads(request.content);context=json.loads(payload['messages'][1]['content']);calls.append(context)
        refs=[s['evidence'] for s in context['safety_sources'] if s['evidence']['type']=='medication_plan']
        value=dict(**TEXT,safety_review=dict(status='reviewed',findings=[dict(kind='drug_drug',title='潜在模型用药风险',detail='模型提出的核对线索，请药师核验。',basis='planned',evidence=refs)]))
        return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps(value,ensure_ascii=False)}}]})
    app.state.report_writer=MiMoReportWriter(Settings(chat_api_key='explicit-substitute',chat_base_url='https://provider.test/v1',chat_model='risk-test'),httpx.MockTransport(safety))
    captured.handler=lambda req:response(candidate(intent='medication_risk',foods=[],food_groups=[],reply='这是计划层面的线索，请药师核验。'))
    value=turn(api,text='这些药会有相互作用吗？')
    assert value.status_code==201,value.text
    text=value.json()['data']['reply']['text'];assert '潜在模型用药风险' in text and '药师' in text
    assert len(calls)==1 and count(api,SafetySignal)==1 and count(api,Checkin)==0
    assert not captured.calls  # No second LLM request merely to restate the reviewed result.
    detailed=turn(api,key='new-risk-food',text='模型甲片和一种新的蔬菜会有冲突吗？')
    assert detailed.status_code==201,detailed.text
    sent=captured.calls[-1].content.decode();assert '既定用药计划' in sent and '模型甲片' in sent
    again=turn(api,key='risk-again',text='还有什么药物冲突风险？')
    assert again.status_code==201 and len(calls)==1
    spoken=[]
    class UnavailableSpeech:
        name='real';is_mock=False
        def synthesize(self,text):
            from app.core.errors import AppError
            spoken.append(text);raise AppError(502,'PROVIDER_ERROR','Explicit test audio unavailable')
    app.state.agent_tts=UnavailableSpeech()
    captured.handler=lambda req:response(candidate(intent='chat',foods=[],food_groups=[],reply='我陪您聊聊。'))
    reminder=turn(api,key='chat-warning',text='你好。')
    assert reminder.status_code==201 and '潜在模型用药风险' in spoken[0]


def test_fixed_time_scanner_not_early_dedup_and_intake_closes_notification(real_api):
    api,_=real_api;add_plan(api);api[2].advance(seconds=20*3600-1)
    app=api[0]
    app.state.scanner.tick()
    def med_notices():
        with app.state.sessions() as tx:return list(tx.scalars(select(Notification).where(Notification.kind=='medication')))
    assert not med_notices()
    api[2].advance(seconds=1);app.state.scanner.tick();found=med_notices();assert len(found)==1
    app.state.scanner.tick();assert med_notices()[0].id==found[0].id
    first=turn(api,text='药吃完了。').json()['data'];a=first['actions'][0]
    assert turn(api,key='done-med',text='确认。',context={'pending_action_id':a['action_id']}).status_code==201
    assert med_notices()[0].task_state=='handled' and count(api,Checkin)==1


def test_after_meal_five_minutes_uses_record_time_and_not_scan_time(real_api):
    api,_=real_api;add_plan(api,mode='after_meal');api[2].advance(seconds=86400)
    app,client,clock,seed,_=api
    def medication_count():
        with app.state.sessions() as tx:return tx.scalar(select(func.count()).select_from(Notification).where(Notification.kind=='medication'))
    app.state.scanner.tick();assert medication_count()==0
    meal=client.post(f"/api/v1/elders/{seed['elder']['elder_id']}/checkins",headers=hdr(api,'meal-clock'),json=dict(type='diet',occurred_at=clock.now().isoformat(),payload=dict(meal_slot='lunch',foods=['豆腐'])))
    assert meal.status_code==201,meal.text
    clock.advance(seconds=299);app.state.scanner.tick();assert medication_count()==0
    clock.advance(seconds=1);app.state.scanner.tick();assert medication_count()==1
    app.state.scanner.tick();assert medication_count()==1


def test_audio_only_medication_intake_loads_tasks_after_asr(real_api):
    api,captured=real_api;add_plan(api);api[2].advance(seconds=86400)
    from app.schemas.agent import ASRResult
    from test_http import upload as upload_audio
    class ASR:
        def transcribe(self,*args):return ASRResult(transcript='我刚才把药吃了。',provider='real',language='zh',is_mock=False)
    api[0].state.agent_asr=ASR()
    audio=upload_audio(api)
    from test_real_understanding import PNG
    image=api[1].post('/api/v1/media',headers=hdr(api,'separate-image-upload'),data={'purpose':'meal','elder_id':api[3]['elder']['elder_id']},files={'file':('camera.png',PNG,'image/png')})
    assert image.status_code==201,image.text
    value=turn(api,text=None,audio_asset_id=audio,image_asset_ids=[image.json()['data']['asset_id']])
    assert value.status_code==201,value.text
    data=value.json()['data'];assert data['actions'][0]['type']=='record_medication' and data['providers']['asr']=='real'
    assert count(api,Checkin)==0 and not captured.calls


@pytest.mark.parametrize('mode,state',[('fixed','before_clock'),('after_meal','waiting_meal'),('after_meal','countdown')])
def test_early_intake_saved_once_and_no_later_reminder(real_api,mode,state):
    api,captured=real_api;add_plan(api,name='降压药',mode=mode)
    app,client,clock,seed,_=api
    clock.advance(seconds=19*3600+30*60 if mode=='fixed' else 86400)
    path=f"/api/v1/elders/{seed['elder']['elder_id']}"
    def meal(key):
        result=client.post(path+'/checkins',headers=hdr(api,key),json=dict(type='diet',occurred_at=clock.now().isoformat(),payload=dict(meal_slot='lunch',foods=['豆腐'])))
        assert result.status_code==201,result.text
    if state=='countdown':meal('before-med-meal')
    occurred=clock.now()
    pending=turn(api,text='呃，吃完之后，我吃了降压药。',image_asset_ids=[upload(api)])
    assert pending.status_code==201,pending.text
    value=pending.json()['data'];action=value['actions'][0]
    assert action['type']=='record_medication' and action['status']=='pending' and not captured.calls
    with app.state.sessions() as tx:
        assert tx.scalar(select(func.count()).select_from(Checkin).where(Checkin.type=='medication'))==0
    args=dict(text='确认。',conversation_id=value['conversation_id'],context={'pending_action_id':action['action_id']})
    done=turn(api,key='early-confirm',**args)
    assert done.status_code==201,done.text
    assert turn(api,key='early-confirm-again',**args).status_code==201
    with app.state.sessions() as tx:
        rows=list(tx.scalars(select(Checkin).where(Checkin.type=='medication')))
        assert len(rows)==1 and rows[0].occurred_at==occurred and rows[0].source=='agent_confirmed'
    if state=='waiting_meal':meal('later-meal')
    clock.advance(seconds=3600);app.state.scanner.tick();app.state.scanner.tick()
    with app.state.sessions() as tx:
        notices=list(tx.scalars(select(Notification).where(Notification.kind=='medication')))
        assert not any(n.task_state in {'open','snoozed'} for n in notices)
    report=client.get(path+'/reports/daily?date=2026-10-31',headers=hdr(api)).json()['data']
    assert len(report['records']['medication'])==1 and report['completion']['progress']['medication']['completed']==1


def test_future_slot_followup_remembers_medicine(real_api):
    api,_=real_api;app,_,clock,seed,_=api
    actor=Actor(seed['elder']['user_id'],Role.elder)
    with UnitOfWork(app.state.sessions) as u:
        app.state.services.medication.apply_change(u.session,actor,seed['elder']['elder_id'],'create',None,
            MedicationPlanWrite(name='甲片',dose_display='既定用量',start_date='2026-10-31',schedule={'mode':'fixed','slots':[{'slot_id':'am','local_time':'08:00'},{'slot_id':'pm','local_time':'20:00'}]}),None)
        u.commit()
    add_plan(api,'乙片');clock.advance(seconds=86400)
    first=turn(api,text='我吃了甲片。').json()['data']
    assert not first['actions'] and '20:00' in first['reply']['text']
    follow=turn(api,key='future-evening',text='晚上那次。',conversation_id=first['conversation_id'])
    assert follow.status_code==201,follow.text
    assert follow.json()['data']['actions'][0]['preview']['slot_id']=='pm' and count(api,Checkin)==0


def test_after_meal_period_only_followup_without_food_record(real_api):
    api,_=real_api;app,_,clock,seed,_=api
    actor=Actor(seed['elder']['user_id'],Role.elder)
    with UnitOfWork(app.state.sessions) as u:
        app.state.services.medication.apply_change(u.session,actor,seed['elder']['elder_id'],'create',None,
            MedicationPlanWrite(name='甲片',dose_display='既定用量',start_date='2026-10-31',schedule={'mode':'after_meal','slots':[{'slot_id':'am','meal_slot':'breakfast','delay_minutes':5},{'slot_id':'noon','meal_slot':'lunch','delay_minutes':5}]}),None)
        u.commit()
    clock.advance(seconds=86400)
    first=turn(api,text='我吃了甲片。').json()['data'];assert not first['actions']
    follow=turn(api,key='meal-period',text='午餐那次。',conversation_id=first['conversation_id'])
    assert follow.status_code==201,follow.text
    assert follow.json()['data']['actions'][0]['preview']['slot_id']=='noon'
    assert count(api,Checkin)==0
