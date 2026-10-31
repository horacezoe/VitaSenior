from app.providers.workflow_trace import run_node
from app.core.uow import UnitOfWork
from app.core.clock import local_date
from app.core.errors import AppError
from app.routers.dependencies import check_access
from app.contracts.report_writer import ReportInput, ReportWriter
from app.schemas.health import ReportPerson

def enriched_report(auth, elder_id, day):
    state=auth.request.app.state
    if day>local_date(state.clock.now()):raise AppError(422,'VALIDATION_ERROR','Cannot generate a future report')
    # Daily goals may materialize. Commit the short write before any provider I/O.
    with UnitOfWork(state.sessions) as unit:
        check_access(auth.request,unit.session,auth.actor,elder_id,'read')
        services=state.services
        report=services.reports.daily(unit.session,auth.actor,elder_id,day)
        report.medication_plans=services.medication.list(unit.session,auth.actor,elder_id).items
        profile=services.profile.read(unit.session,auth.actor,elder_id)
        memory=services.memory.context(unit.session,auth.actor,elder_id)
        unit.commit()
    report.person=ReportPerson(**profile.model_dump(include={'display_name','birth_date','conditions','allergies'}))
    writer: ReportWriter | None=state.report_writer
    if writer is None:report.ai_status='not_configured'
    else:
        try:
            report.insights=run_node(auth.request.state.request_id, str(day), "daily_report", lambda: writer.generate(ReportInput(profile,memory,report)))
            report.ai_status='ready'
        except AppError:
            report.ai_status='unavailable'
    return state.respond(auth.request,report)
