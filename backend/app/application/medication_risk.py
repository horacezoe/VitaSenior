"""Read-only medication draft review; all model I/O occurs outside UoWs."""
from dataclasses import replace
import hashlib,json
from app.application.daily_report import _snapshot
from app.contracts.report_writer import report_digest,MedicationRiskReviewer
from app.core.auth import authenticate
from app.core.clock import local_date
from app.core.errors import AppError
from app.core.uow import UnitOfWork
from app.routers.dependencies import check_access
from app.providers.workflow_trace import run_node
from app.schemas.health import SafetySource,MedicationRiskCheckResult


def _input(auth,elder_id,body):
    state=auth.request.app.state
    # Reauthenticate, including after network I/O: a revoked session/binding
    # cannot obtain a model response containing someone else's health details.
    with UnitOfWork(state.sessions,write=False) as unit:
        scheme,_,token=auth.request.headers.get('authorization','').partition(' ')
        actor=authenticate(unit.session,token if scheme.lower()=='bearer' else None,state.clock)
        if actor!=auth.actor:raise AppError(401,'UNAUTHENTICATED','Session actor changed')
        check_access(auth.request,unit.session,actor,elder_id,'read')
        plans=state.services.medication.list(unit.session,actor,elder_id,True).items
        if body.replace_plan_id:
            target=state.services.medication.get_plan(unit.session,actor,body.replace_plan_id)
            if target.elder_id!=elder_id:raise AppError(404,'NOT_FOUND','Plan unavailable')
            if target.version!=body.expected_version or not target.active:
                raise AppError(409,'VERSION_CONFLICT','Plan changed; reload before checking')
        if body.plan.medicine_asset_id:
            state.services.media.get_asset(unit.session,actor,body.plan.medicine_asset_id)
    snapshot=_snapshot(auth,elder_id,local_date(state.clock.now()))
    sources=[s for s in snapshot.safety_sources if s.evidence.type!='medication_plan']
    # Include active future plans for draft review; the model sees dates and
    # must distinguish overlapping schedules from separate treatment periods.
    for plan in plans:
        if plan.plan_id==body.replace_plan_id:continue
        sources.append(SafetySource(evidence=dict(type='medication_plan',id=plan.plan_id,version=plan.version),category='medication',basis='planned',medicine_id=plan.plan_id,label=plan.name,facts=plan.model_dump(mode='json')))
    digest=hashlib.sha256(json.dumps(body.plan.model_dump(mode='json'),sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    sources.append(SafetySource(evidence=dict(type='proposed_plan',id='draft-'+digest,version=1),category='medication',basis='planned',medicine_id=body.replace_plan_id or 'draft-'+digest,label='拟添加/修改：'+body.plan.name,facts=body.plan.model_dump(mode='json')))
    # A replacement must not remain in the duplicate report context either.
    report=snapshot.report.model_copy(deep=True)
    report.medication_plans=[p for p in plans if p.plan_id!=body.replace_plan_id]
    return replace(snapshot,report=report,safety_sources=tuple(sources))


def check_medication_risk(auth,elder_id,body):
    state=auth.request.app.state
    snapshot=_input(auth,elder_id,body);digest=report_digest(snapshot)
    writer=state.report_writer
    if writer is None:
        return MedicationRiskCheckResult(status='not_configured',checked_at=state.clock.now())
    try:
        review=run_node(auth.request.state.request_id,'plan-draft','medication_plan_risk',
            lambda:writer.review_plan(snapshot) if isinstance(writer,MedicationRiskReviewer) else writer.generate(snapshot).safety_review)
        if review is None:raise AppError(502,'PROVIDER_ERROR','Missing model safety assessment')
    except AppError as error:
        if error.status not in {502,504}:raise
        # No invented successful findings and no medication/proposal is saved.
        _input(auth,elder_id,body)
        return MedicationRiskCheckResult(status='unavailable',model=state.settings.chat_model,checked_at=state.clock.now())
    latest=_input(auth,elder_id,body)
    if report_digest(latest)!=digest:
        raise AppError(409,'VERSION_CONFLICT','Health information changed during check; please review again')
    return MedicationRiskCheckResult(status=review.status,findings=review.findings,model=state.settings.chat_model,checked_at=state.clock.now())
