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

INSIGHTS=dict(warm_message='今天的点滴都值得被看见。',elder_praise='谢谢您认真记录生活。',reminder='按自己的节奏慢慢来。',diet_advice='可以继续记录下一餐。',exercise_advice='按自己的能力活动。',medication_advice='按既定计划核对，不自行改药。')

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
        assert set(context)=={'profile','memory','report'}
        return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps(INSIGHTS)}}]})
    class Document:
        def model_dump(self,**kwargs):return {'version':1}
    writer=MiMoReportWriter(Settings(chat_api_key='test-only-key',chat_base_url='https://api.xiaomimimo.com/v1',chat_model='test'),httpx.MockTransport(handler))
    snapshot=SimpleNamespace(profile=Document(),memory=Document(),report=Document())
    assert writer.generate(snapshot)==writer.generate(snapshot)
    assert len(calls)==1
