import json
from datetime import date
from types import SimpleNamespace
import httpx
from fastapi.testclient import TestClient
from app.main import create_app
from app.core.config import Settings
from app.core.uow import UnitOfWork
from app.seed import framework_seed
from app.schemas.health import DailyInsights
from app.providers.report_writer import MiMoReportWriter
from datetime import datetime, timedelta, timezone
from app.core.clock import FakeClock, local_date
from app.models.health import Checkin

INSIGHTS=dict(warm_message='今天的点滴都值得被看见。',elder_praise='谢谢您认真记录生活。',reminder='按自己的节奏慢慢来。',diet_advice='可以继续记录下一餐。',exercise_advice='按自己的能力活动。',medication_advice='按既定计划核对，不自行改药。',safety_review={'status':'insufficient_data','findings':[]})

def test_enriched_report_authorization_snapshot_and_no_provider_write_lock(tmp_path):
    app=create_app(Settings(data_dir=tmp_path,database_url=None,scanner_enabled=False))
    with TestClient(app) as client:
        seed=framework_seed(app.state.sessions,app.state.clock)
        calls=[]
        class Writer:
            def generate(self,snapshot):
                calls.append(snapshot)
                with UnitOfWork(app.state.sessions) as unit:unit.commit()
                return DailyInsights(**INSIGHTS)
        app.state.report_writer=Writer()
        url=f'/api/v1/elders/{seed["elder"]["elder_id"]}/reports/daily?date={app.state.clock.now().date()}&include_ai=true'
        assert client.get(url).status_code==401 and not calls
        for role in ('unbound_child','elder'):
            account={k:seed[role][k] for k in ('phone','role')}
            challenge=client.post('/api/v1/auth/code',json=account).json()['data']['challenge_id']
            token=client.post('/api/v1/auth/login',json={**account,'challenge_id':challenge,'code':'123456'}).json()['data']['access_token']
            result=client.get(url,headers={'Authorization':'Bearer '+token})
            if role=='unbound_child':assert result.status_code==403 and not calls
            else:
                assert result.status_code==200,result.text
                assert result.json()['data']['ai_status']=='ready'
                assert calls[0].profile.elder_id==seed['elder']['elder_id']
                assert calls[0].memory.elder_id==seed['elder']['elder_id']

def test_writer_sends_all_sources_and_caches_identical_snapshot():
    calls=[]
    def handler(request):
        body=json.loads(request.content);context=json.loads(body['messages'][1]['content']);calls.append(context)
        assert set(context)=={'profile','memory','report','safety_sources','history'}
        return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps(INSIGHTS)}}]})
    class Document:
        def model_dump(self,**kwargs):return {'version':1}
    writer=MiMoReportWriter(Settings(chat_api_key='test-only-key',chat_base_url='https://api.xiaomimimo.com/v1',chat_model='test'),httpx.MockTransport(handler))
    snapshot=SimpleNamespace(profile=Document(),memory=Document(),report=Document())
    assert writer.generate(snapshot)==writer.generate(snapshot)
    assert len(calls)==1


def test_empty_day_generates_for_both_roles_using_profile_and_only_valid_past_records(tmp_path):
    clock=FakeClock(datetime(2026,11,1,4,tzinfo=timezone.utc))
    app=create_app(Settings(data_dir=tmp_path,database_url=None,scanner_enabled=False),clock=clock)
    with TestClient(app) as client:
        seed=framework_seed(app.state.sessions,clock)
        elder=seed['elder']['elder_id']
        day=local_date(clock.now())
        with UnitOfWork(app.state.sessions) as unit:
            for key,offset,cancelled in [('recent',1,False),('cancelled',2,True),('too-old',8,False)]:
                when=clock.now()-timedelta(days=offset)
                unit.session.add(Checkin(id=key,elder_id=elder,type='exercise',local_date=day-timedelta(days=offset),
                    payload_json={'activity':'散步','duration_minutes':12},occurred_at=when,created_at=when,updated_at=when,
                    cancelled_at=clock.now() if cancelled else None))
            unit.commit()
        calls=[]
        class Writer:
            def generate(self,snapshot):
                calls.append(snapshot)
                assert not any(getattr(snapshot.report.records,k) for k in ('diet','exercise','medication'))
                assert snapshot.profile.elder_id==elder
                assert [r.checkin_id for r in snapshot.history]==['recent']
                assert snapshot.history[0].local_date==day-timedelta(days=1)
                with UnitOfWork(app.state.sessions) as unit: unit.commit()
                return DailyInsights(**INSIGHTS)
        app.state.report_writer=Writer()
        for label in ('elder','bound_child'):
            account={k:seed[label][k] for k in ('phone','role')}
            challenge=client.post('/api/v1/auth/code',json=account).json()['data']['challenge_id']
            token=client.post('/api/v1/auth/login',json={**account,'challenge_id':challenge,'code':'123456'}).json()['data']['access_token']
            result=client.get(f'/api/v1/elders/{elder}/reports/daily',params={'date':str(day),'include_ai':'true'},headers={'Authorization':'Bearer '+token})
            assert result.status_code==200,result.text
            data=result.json()['data']
            assert data['ai_status']=='ready' and data['insights']['warm_message']==INSIGHTS['warm_message']
            assert data['records']=={'diet':[],'exercise':[],'medication':[]}
        assert len(calls)==2
