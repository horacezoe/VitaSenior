from datetime import datetime,timezone
from types import SimpleNamespace
import json
import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select,func
from app.main import create_app
from app.seed import framework_seed
from app.core.config import Settings
from app.core.clock import FakeClock
from app.core.uow import UnitOfWork
from app.core.errors import AppError
from app.models.health import SafetySignal,MedicationPlan
from app.schemas.health import DailyInsights,SafetySource
from app.providers.report_writer import MiMoReportWriter

TEXT=dict(warm_message='日常记录已整理。',elder_praise='每一份记录都值得鼓励。',reminder='有需要可以找家人聊聊。',diet_advice='核对餐食记录。',exercise_advice='按自己的节奏活动。',medication_advice='请按既定计划核对。')

@pytest.fixture
def h(tmp_path):
    clock=FakeClock(datetime(2026,10,30,tzinfo=timezone.utc))
    app=create_app(Settings(data_dir=tmp_path,database_url=None,scanner_enabled=False,safety_review_enabled=True),clock=clock)
    with TestClient(app) as client:
        seed=framework_seed(app.state.sessions,clock);tokens={}
        for name in ('elder','bound_child','unbound_child'):
            a={k:seed[name][k] for k in ('phone','role')}
            challenge=client.post('/api/v1/auth/code',json=a).json()['data']['challenge_id']
            login=client.post('/api/v1/auth/login',json={**a,'challenge_id':challenge,'code':'123456'})
            tokens[name]={'Authorization':'Bearer '+login.json()['data']['access_token']}
        elder=seed['elder']['elder_id']
        for n in ('模型药A','模型药B'):
            r=client.post(f'/api/v1/elders/{elder}/medication-plans',headers={**tokens['elder'],'Idempotency-Key':n.encode().hex()},json=dict(name=n,dose_display='既定用量',schedule=dict(mode='fixed',slots=[dict(slot_id='morning',local_time='07:00')]),start_date='2026-10-30'))
            assert r.status_code==201,r.text
        yield SimpleNamespace(app=app,client=client,elder=elder,tokens=tokens,url=f'/api/v1/elders/{elder}/reports/daily?date=2026-10-30',clock=clock)

class Writer:
    def __init__(self,h):self.h,self.calls,self.mode=h,0,'alert'
    def generate(self,snapshot):
        self.calls+=1
        if self.mode=="error":raise AppError(504,"PROVIDER_TIMEOUT","Test model timeout")
        with UnitOfWork(self.h.app.state.sessions) as u:u.commit() # no DB write lock during model work
        refs=[s.evidence.model_dump() for s in snapshot.safety_sources if s.evidence.type=='medication_plan']
        if self.mode=='stale':
            with UnitOfWork(self.h.app.state.sessions) as u:
                p=u.session.get(MedicationPlan,refs[0]['id']);p.version+=1;p.name+='已更正';u.commit()
        findings=[] if self.mode=='clear' else [dict(kind='drug_drug',title='潜在用药问题需核对',detail='替身模型对所提供的两项计划提出核对线索。',basis='planned',evidence=refs)]
        return DailyInsights(**TEXT,safety_review=dict(status='reviewed',findings=findings))

def test_model_assessment_persists_history_and_deduplicates_polling(h):
    writer=Writer(h);h.app.state.report_writer=writer
    assert h.client.get(h.url,headers=h.tokens['unbound_child']).status_code==403 and writer.calls==0
    h.client.get(h.url,headers=h.tokens['elder']) # background model assessment
    report=h.client.get(h.url,headers=h.tokens['bound_child']).json()['data']
    assert writer.calls==1 and len(report['anomalies'])==1
    a=report['anomalies'][0];assert a['basis']=='planned' and a['status']=='active'
    cal=h.client.get(f'/api/v1/elders/{h.elder}/calendar?month=2026-10',headers=h.tokens['elder']).json()['data']
    assert next(d for d in cal['days'] if d['date']=='2026-10-30')['anomalies'][0]['anomaly_id']==a['anomaly_id']
    with UnitOfWork(h.app.state.sessions) as u:
        p=u.session.scalar(select(MedicationPlan).where(MedicationPlan.elder_id==h.elder));p.version+=1;p.notes='本人已更正计划说明';u.commit()
    writer.mode='clear';h.clock.advance(seconds=10)
    h.client.get(h.url,headers=h.tokens['elder'])
    history=h.client.get(h.url,headers=h.tokens['elder']).json()['data']['anomalies'][0]
    assert history['anomaly_id']==a['anomaly_id'] and history['status']=='resolved' and history['revision']>a['revision']
    with UnitOfWork(h.app.state.sessions,write=False) as u:assert u.session.get(SafetySignal,a['anomaly_id']).history

def test_stale_model_output_is_not_committed(h):
    writer=Writer(h);writer.mode='stale';h.app.state.report_writer=writer
    response=h.client.get(h.url+'&include_ai=true',headers=h.tokens['elder'])
    assert response.json()['data']['ai_status']=='unavailable'
    with UnitOfWork(h.app.state.sessions,write=False) as u:assert u.session.scalar(select(func.count()).select_from(SafetySignal))==0

def test_real_adapter_requires_grounded_evidence_not_a_local_drug_table():
    sources=tuple(SafetySource(evidence=dict(type='medication_plan',id=f'p{i}',version=1),category='medication',basis='planned',medicine_id=f'p{i}',label=f'任意模型药{i}',facts={}) for i in range(2))
    class Doc:
        def model_dump(self,**kwargs):return {}
    finding=dict(kind='drug_drug',title='潜在冲突',detail='模型核对提示',basis='planned',evidence=[s.evidence.model_dump() for s in sources])
    def handler(request):
        context=json.loads(json.loads(request.content)['messages'][1]['content']);assert len(context['safety_sources'])==2
        return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps(dict(**TEXT,safety_review=dict(status='reviewed',findings=[finding])))}}]})
    snapshot=SimpleNamespace(profile=Doc(),memory=Doc(),report=Doc(),safety_sources=sources)
    p=MiMoReportWriter(Settings(chat_api_key='test',chat_base_url='https://api.xiaomimimo.com/v1',chat_model='test'),httpx.MockTransport(handler))
    assert len(p.generate(snapshot).safety_review.findings)==1
    finding['evidence'][0]['id']='invented'
    p.cache.clear()
    with pytest.raises(AppError):p.generate(snapshot)
    assert not p.cache

def test_shared_rewards_are_identical_and_idempotent(h):
    body=dict(type='exercise',occurred_at=h.clock.now().isoformat(),payload=dict(activity='散步',duration_minutes=15))
    headers={**h.tokens['elder'],'Idempotency-Key':'reward-once'}
    a=h.client.post(f'/api/v1/elders/{h.elder}/checkins',headers=headers,json=body)
    b=h.client.post(f'/api/v1/elders/{h.elder}/checkins',headers=headers,json=body)
    assert a.status_code==b.status_code==201
    assert a.json()['data']['checkin_id']==b.json()['data']['checkin_id']
    one=h.client.get(h.url,headers=h.tokens['elder']).json()['data']['reward_summary']
    two=h.client.get(h.url,headers=h.tokens['bound_child']).json()['data']['reward_summary']
    assert one==two==dict(cumulative=1,on_date=1)

def test_failure_does_not_erase_previous_warning(h):
    writer=Writer(h);h.app.state.report_writer=writer
    h.client.get(h.url,headers=h.tokens['elder'])
    with UnitOfWork(h.app.state.sessions) as u:
        p=u.session.scalar(select(MedicationPlan).where(MedicationPlan.elder_id==h.elder));p.version+=1;p.notes='待重新核对';u.commit()
    writer.mode='error'
    result=h.client.get(h.url+'&include_ai=true',headers=h.tokens['elder']).json()['data']
    assert result['ai_status']=='unavailable' and result['safety_review_status']=='unavailable'
    assert result['anomalies'][0]['status']=='active'
