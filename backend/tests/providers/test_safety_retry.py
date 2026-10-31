"""Bounded repair must never accept unsupported model evidence."""
from types import SimpleNamespace
import json
import httpx
import pytest
from app.core.config import Settings
from app.core.errors import AppError
from app.providers.report_writer import MiMoReportWriter
from app.schemas.health import SafetySource

TEXT=dict(warm_message='记录已整理。',elder_praise='记录值得鼓励。',reminder='和家人聊聊。',diet_advice='核对记录。',exercise_advice='按自己节奏。',medication_advice='核对既定计划。')


def test_one_schema_repair_then_validated_cache():
    class Doc:
        def model_dump(self,**kwargs):return {}
    sources=tuple(SafetySource(evidence=dict(type='medication_plan',id=f'p{i}',version=1),category='medication',basis='planned',medicine_id=f'p{i}',label=f'任意药{i}',facts={}) for i in range(2))
    calls=[]
    def handler(request):
        sent=json.loads(request.content);calls.append(sent)
        refs=[s.evidence.model_dump() for s in sources]
        if len(calls)==1:refs[0]['id']='not-authorized'
        value=dict(**TEXT,safety_review=dict(status='reviewed',findings=[dict(kind='drug_drug',title='潜在风险',detail='模型提示请药师核验。',basis='planned',evidence=refs)]))
        return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':json.dumps(value)}}]})
    writer=MiMoReportWriter(Settings(chat_api_key='test',chat_base_url='https://provider.test/v1',chat_model='test'),httpx.MockTransport(handler))
    snapshot=SimpleNamespace(profile=Doc(),memory=Doc(),report=Doc(),safety_sources=sources)
    result=writer.generate(snapshot);assert result.safety_review.findings[0].evidence[0].id=='p0'
    assert len(calls)==2 and '上次输出未通过校验' in calls[1]['messages'][0]['content']
    writer.generate(snapshot);assert len(calls)==2


def test_repair_shares_deadline_and_has_no_third_attempt(monkeypatch):
    import app.providers.report_writer as module
    ticks=[0.0];monkeypatch.setattr(module,'time',SimpleNamespace(monotonic=lambda:ticks[0]))
    writer=MiMoReportWriter(Settings());calls=[]
    def invalid(snapshot,*,timeout,correction=None):
        calls.append((timeout,correction));ticks[0]+=13
        raise AppError(502,'PROVIDER_ERROR','Unsupported model evidence')
    monkeypatch.setattr(writer,'_generate',invalid)
    with pytest.raises(AppError):writer.generate(None)
    assert [v[0] for v in calls]==[20,7] and calls[1][1]=='Unsupported model evidence'


def test_auth_failure_not_retried(monkeypatch):
    writer=MiMoReportWriter(Settings());calls=[]
    def failure(*args,**kwargs):
        calls.append(1);raise AppError(502,'PROVIDER_ERROR','Daily report provider unavailable')
    monkeypatch.setattr(writer,'_generate',failure)
    with pytest.raises(AppError):writer.generate(None)
    assert len(calls)==1
