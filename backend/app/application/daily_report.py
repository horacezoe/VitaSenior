from app.providers.workflow_trace import run_node
from app.core.uow import UnitOfWork
from app.core.clock import local_date
from app.core.errors import AppError
from app.routers.dependencies import check_access
from app.contracts.report_writer import ReportInput, ReportWriter, report_digest
from app.schemas.health import ReportPerson
import hashlib, logging
log=logging.getLogger("vitasenior.workflow")

def _snapshot(auth, elder_id, day):
    state=auth.request.app.state
    with UnitOfWork(state.sessions) as unit:
        check_access(auth.request,unit.session,auth.actor,elder_id,'read')
        s=state.services
        report=s.reports.daily(unit.session,auth.actor,elder_id,day)
        report.medication_plans=s.medication.list(unit.session,auth.actor,elder_id).items
        profile=s.profile.read(unit.session,auth.actor,elder_id)
        memory=s.memory.context(unit.session,auth.actor,elder_id)
        sources=s.safety.sources(unit.session,auth.actor,elder_id,day,report) if s.safety else ()
        unit.commit()
    report.person=ReportPerson(**profile.model_dump(include={'display_name','birth_date','conditions','allergies'}))
    return ReportInput(profile,memory,report,sources)

def _digest(state,snapshot):
    return hashlib.sha256(('safety-llm-v2|'+state.settings.chat_model+'|'+report_digest(snapshot)).encode()).hexdigest()

def enriched_report(auth, elder_id, day, *, review_only=False):
    state=auth.request.app.state
    if day>local_date(state.clock.now()):raise AppError(422,'VALIDATION_ERROR','Cannot generate a future report')
    snapshot=_snapshot(auth,elder_id,day);report=snapshot.report
    digest=_digest(state,snapshot);safety=state.services.safety
    if review_only and safety:
        with UnitOfWork(state.sessions,write=False) as unit:
            if safety.reviewed(unit.session,auth.actor,elder_id,day,digest,state.settings.chat_model):return None
    writer: ReportWriter | None=state.report_writer
    if writer is None:report.ai_status='not_configured'
    else:
        insights=None
        try:
            insights=run_node(auth.request.state.request_id,str(day),"daily_report",lambda:writer.generate(snapshot))
            report.insights=insights;report.ai_status='ready'
        except AppError:
            report.ai_status='unavailable'
        # Re-read after provider I/O. Never persist an assessment of stale data.
        latest=_snapshot(auth,elder_id,day)
        if _digest(state,latest)!=digest:
            latest.report.ai_status='unavailable'
            return state.respond(auth.request,latest.report)
        if safety:
            review=insights.safety_review if insights else None
            if review is not None or report.ai_status=='unavailable':
                with UnitOfWork(state.sessions) as unit:
                    # Hold the final snapshot check and save in the SAME short write UoW.
                    check_access(auth.request,unit.session,auth.actor,elder_id,'read')
                    current=state.services.reports.daily(unit.session,auth.actor,elder_id,day)
                    current.medication_plans=state.services.medication.list(unit.session,auth.actor,elder_id).items
                    current_input=ReportInput(state.services.profile.read(unit.session,auth.actor,elder_id),state.services.memory.context(unit.session,auth.actor,elder_id),current,safety.sources(unit.session,auth.actor,elder_id,day,current))
                    if _digest(state,current_input)==digest:
                        safety.save(unit.session,auth.actor,elder_id,day,digest,state.settings.chat_model,review)
                    report.anomalies=safety.read(unit.session,auth.actor,elder_id,day)
                    report.safety_review_status=safety.status(unit.session,auth.actor,elder_id,day)
                    unit.commit()
    return state.respond(auth.request,report)

def automatic_review(auth,elder_id,day):
    try:enriched_report(auth,elder_id,day,review_only=True)
    except AppError as error:
        log.warning("Background assessment request_id=%s code=%s",auth.request.state.request_id,error.code)
