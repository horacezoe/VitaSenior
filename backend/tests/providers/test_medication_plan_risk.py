from dataclasses import replace
import json
import httpx
import pytest
from sqlalchemy import select,func
from test_safety_review import h,TEXT
from app.core.config import Settings
from app.core.uow import UnitOfWork
from app.core.errors import AppError
from app.providers.report_writer import MiMoReportWriter
from app.models.health import MedicationPlan,Checkin,SafetySignal
from app.models.identity import ChangeProposal,FamilyBinding

DRAFT=dict(name='拟添加的模型药',dose_display='既定用量',schedule=dict(mode='fixed',slots=[dict(slot_id='evening',local_time='20:00')]),start_date='2026-10-30')

def setup_writer(h,*,mode='profile',hook=None):
    calls=[]
    def handler(request):
        context=json.loads(json.loads(request.content)['messages'][1]['content']);calls.append(context)
        with UnitOfWork(h.app.state.sessions) as u:u.commit() # model outside write transaction
        if hook:hook(context)
        if mode=='error':return httpx.Response(503)
        sources=context['safety_sources'];draft=next(s for s in sources if s['evidence']['type']=='proposed_plan')
        other=next(s for s in sources if s['category']==('profile' if mode=='profile' else 'medication') and s is not draft)
        refs=[draft['evidence'],other['evidence']]
        if mode=='invalid':refs[1]={**refs[1],'id':'invented'}
        status='insufficient_data' if mode=='insufficient' else 'reviewed'
        findings=[] if mode in {'clear','insufficient'} else [dict(kind='drug_profile' if mode=='profile' else 'drug_drug',title='潜在模型核对线索',detail='显式测试替身，请药师核验。',basis='planned',evidence=refs)]
        return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':json.dumps(dict(status=status,findings=findings) if context.get('purpose') else dict(**TEXT,safety_review=dict(status=status,findings=findings)))}}]})
    h.app.state.report_writer=MiMoReportWriter(Settings(chat_api_key='test',chat_base_url='https://provider.test/v1',chat_model='risk-test'),httpx.MockTransport(handler))
    return calls


def check(h,body=None,role='elder'):
    return h.client.post(f'/api/v1/elders/{h.elder}/medication-plan-risk',headers=h.tokens[role],json=body or dict(plan=DRAFT))

@pytest.mark.parametrize('role',['elder','bound_child'])
def test_preflight_checks_proposed_drug_existing_medicines_and_profile_without_saving(h,role):
    calls=setup_writer(h)
    with h.app.state.sessions() as tx:
        counts={m:tx.scalar(select(func.count()).select_from(m)) for m in [MedicationPlan,Checkin,ChangeProposal,SafetySignal]}
    result=check(h,role=role);assert result.status_code==200,result.text
    data=result.json()['data'];assert data['status']=='reviewed' and data['findings'][0]['kind']=='drug_profile'
    assert len(calls)==1
    sources=calls[0]['safety_sources'];assert any(s['category']=='profile' and 'allergies' in s['facts'] and 'conditions' in s['facts'] for s in sources)
    assert len([s for s in sources if s['category']=='medication'])==3
    with h.app.state.sessions() as tx:
        for m,n in counts.items():assert tx.scalar(select(func.count()).select_from(m))==n


def test_preflight_denies_unbound_actor_before_model(h):
    calls=setup_writer(h);assert check(h,role='unbound_child').status_code==403 and not calls

@pytest.mark.parametrize('mode,status',[('clear','reviewed'),('insufficient','insufficient_data'),('error','unavailable'),('invalid','unavailable')])
def test_preflight_distinguishes_no_findings_missing_data_and_failures(h,mode,status):
    setup_writer(h,mode=mode);result=check(h)
    assert result.status_code==200,result.text
    assert result.json()['data']['status']==status and not result.json()['data']['findings']


def test_preflight_does_not_claim_safe_when_unconfigured(h):
    result=check(h);assert result.status_code==200 and result.json()['data']['status']=='not_configured'


def test_replace_checks_new_version_without_self_interaction(h):
    with h.app.state.sessions() as tx:plan=tx.scalar(select(MedicationPlan).where(MedicationPlan.elder_id==h.elder));target,version=plan.id,plan.version
    calls=setup_writer(h,mode='drug');result=check(h,dict(plan=DRAFT,replace_plan_id=target,expected_version=version))
    assert result.status_code==200,result.text
    assert all(s['evidence']['id']!=target for s in calls[0]['safety_sources'] if s['evidence']['type']=='medication_plan')
    assert len([s for s in calls[0]['safety_sources'] if s['evidence']['type']=='medication_plan'])==1
    assert check(h,dict(plan=DRAFT,replace_plan_id=target,expected_version=version+1)).status_code==409
    assert check(h,dict(plan=DRAFT,replace_plan_id=target)).status_code==422


def test_profile_or_plan_change_during_model_requires_recheck(h):
    def change(context):
        with UnitOfWork(h.app.state.sessions) as u:
            plan=u.session.scalar(select(MedicationPlan).where(MedicationPlan.elder_id==h.elder));plan.version+=1;u.commit()
    setup_writer(h,hook=change)
    result=check(h);assert result.status_code==409,result.text


def test_revoked_binding_during_model_cannot_receive_health_response(h):
    def revoke(context):
        with UnitOfWork(h.app.state.sessions) as u:
            binding=u.session.scalar(select(FamilyBinding).where(FamilyBinding.elder_id==h.elder));binding.status='revoked';u.commit()
    setup_writer(h,hook=revoke);assert check(h,role='bound_child').status_code==403


def test_child_preflight_does_not_grant_direct_plan_mutation(h):
    setup_writer(h);assert check(h,role='bound_child').status_code==200
    response=h.client.post(f'/api/v1/elders/{h.elder}/medication-plans',headers={**h.tokens['bound_child'],'Idempotency-Key':'still-proposal-required'},json=DRAFT)
    assert response.status_code==403 and response.json()['error']['code']=='PROPOSAL_REQUIRED'


def test_saved_plan_automatically_checks_and_persists_real_profile_evidence(h):
    def handler(request):
        data=json.loads(json.loads(request.content)['messages'][1]['content'])
        assert not any(s['evidence']['type']=='proposed_plan' for s in data['safety_sources'])
        profile=next(s for s in data['safety_sources'] if s['category']=='profile')
        medicine=next(s for s in data['safety_sources'] if s['label']==DRAFT['name'])
        finding=dict(kind='drug_profile',title='潜在用药档案核对线索',detail='测试模型提示，请药师核验。',basis='planned',evidence=[profile['evidence'],medicine['evidence']])
        return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps(dict(**TEXT,safety_review=dict(status='reviewed',findings=[finding])))}}]})
    h.app.state.report_writer=MiMoReportWriter(Settings(chat_api_key='test',chat_base_url='https://provider.test/v1',chat_model='test'),httpx.MockTransport(handler))
    response=h.client.post(f'/api/v1/elders/{h.elder}/medication-plans',headers={**h.tokens['elder'],'Idempotency-Key':'post-check'},json=DRAFT)
    assert response.status_code==201,response.text
    with h.app.state.sessions() as tx:
        signal=tx.scalar(select(SafetySignal).where(SafetySignal.elder_id==h.elder))
        assert signal and signal.payload['kind']=='drug_profile'
        assert all(r['type']!='proposed_plan' for r in signal.payload['evidence'])
