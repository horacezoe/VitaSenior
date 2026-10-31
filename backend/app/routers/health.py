from datetime import date as Date
from typing import Annotated
from fastapi import APIRouter, Query, Header
from app.schemas.common import Envelope, Page
from app.schemas.enums import Category, TaskState
from app.routers.dependencies import Auth
from app.schemas.identity import Dashboard, EventResult
from app.schemas.health import MedicationRiskCheckWrite, MedicationRiskCheckResult, Calendar, CancelledCheckin, Checkin, CheckinUpdate, CheckinWrite, DailyReport, FamilyReminderWrite, MedicationPlan, MedicationPlanWrite, Notification, NotificationEvent, PlanList, PlanUpdate, Presence, PresenceWrite, ReminderSettings, SettingsUpdate, TaskList
from app.application.health_flows import perform, family_reminder

router = APIRouter()

@router.post("/elders/{elder_id}/medication-plan-risk", operation_id="PLAN05", response_model=Envelope[MedicationRiskCheckResult])
def plan05(ctx: Auth, elder_id: str, body: MedicationRiskCheckWrite):
    from app.application.medication_risk import check_medication_risk
    return ctx.request.app.state.respond(ctx.request,check_medication_risk(ctx,elder_id,body))


@router.get("/elders/{elder_id}/medication-plans", operation_id="PLAN01", response_model=Envelope[PlanList], status_code=200)
def plan01(ctx: Auth, elder_id: str, active: bool | None = None):
    return perform(ctx, service_name="medication", elder_id=elder_id,
        operation=lambda s, tx, actor, elder: s.medication.list(tx, actor, elder, active))

@router.post("/elders/{elder_id}/medication-plans", operation_id="PLAN02", response_model=Envelope[MedicationPlan], status_code=201)
def plan02(ctx: Auth, elder_id: str, body: MedicationPlanWrite, idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=200)]):
    response = perform(ctx, service_name="medication", elder_id=elder_id, scope="proposal",
        body=body.model_dump(mode="json"), key=idempotency_key, status=201,
        operation=lambda s, tx, actor, elder: s.medication.apply_change(tx, actor, elder, "create", None, body, None))
    return _review_saved_plan(ctx,response)

@router.put("/medication-plans/{plan_id}", operation_id="PLAN03", response_model=Envelope[MedicationPlan], status_code=200)
def plan03(ctx: Auth, plan_id: str, body: PlanUpdate, idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=200)]):
    response = perform(ctx, service_name="medication", resource=("plan", plan_id), scope="proposal",
        body=body.model_dump(mode="json"), key=idempotency_key,
        operation=lambda s, tx, actor, elder: s.medication.apply_change(tx, actor, elder, "update", plan_id, body.patch, body.expected_version))
    return _review_saved_plan(ctx,response)

def _review_saved_plan(ctx,response):
    state=ctx.request.app.state
    if state.settings.safety_review_enabled and state.report_writer is not None:
        import json
        from starlette.background import BackgroundTask
        from app.application.daily_report import automatic_review
        from app.core.clock import local_date
        elder_id=json.loads(response.body)['data']['elder_id']
        response.background=BackgroundTask(automatic_review,ctx,elder_id,local_date(state.clock.now()))
    return response

@router.get("/elders/{elder_id}/reminder-settings", operation_id="SET01", response_model=Envelope[ReminderSettings], status_code=200)
def set01(ctx: Auth, elder_id: str):
    return perform(ctx, service_name="medication", elder_id=elder_id,
        operation=lambda s, tx, actor, elder: s.medication.settings(tx, actor, elder))

@router.put("/elders/{elder_id}/reminder-settings", operation_id="SET02", response_model=Envelope[ReminderSettings], status_code=200)
def set02(ctx: Auth, elder_id: str, body: SettingsUpdate, idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=200)]):
    return perform(ctx, service_name="medication", elder_id=elder_id, scope="proposal",
        body=body.model_dump(mode="json"), key=idempotency_key,
        operation=lambda s, tx, actor, elder: s.medication.update_settings(tx, actor, elder, body.expected_version, body.patch))

@router.get("/elders/{elder_id}/tasks", operation_id="TASK01", response_model=Envelope[TaskList], status_code=200)
def task01(ctx: Auth, elder_id: str, date: Annotated[Date, Query()]):
    return perform(ctx, service_name="tasks", elder_id=elder_id, snapshot=True,
        operation=lambda s, tx, actor, elder: s.tasks.today(tx, actor, elder, date))

@router.get("/elders/{elder_id}/checkins", operation_id="REC01", response_model=Envelope[Page[Checkin]], status_code=200)
def rec01(ctx: Auth, elder_id: str, date: Annotated[Date, Query()], type: Category | None = None, limit: Annotated[int, Query(ge=1, le=100)] = 20, cursor: str | None = None):
    return perform(ctx, service_name="checkins", elder_id=elder_id,
        operation=lambda s, tx, actor, elder: s.checkins.list(tx, actor, elder, date, type, limit, cursor))

@router.post("/elders/{elder_id}/checkins", operation_id="REC02", response_model=Envelope[Checkin], status_code=201, responses={200: {"model": Envelope[Checkin], "description": "Existing same-meal record replaced; meta.replaced=true"}})
def rec02(ctx: Auth, elder_id: str, body: CheckinWrite, idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=200)]):
    return perform(ctx, service_name="checkins", elder_id=elder_id, scope="self",
        body=body.model_dump(mode="json"), key=idempotency_key, status=201,
        operation=lambda s, tx, actor, elder: s.checkins.create_or_update(tx, actor, elder, body))

@router.put("/checkins/{checkin_id}", operation_id="REC03", response_model=Envelope[Checkin], status_code=200)
def rec03(ctx: Auth, checkin_id: str, body: CheckinUpdate, idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=200)]):
    return perform(ctx, service_name="checkins", resource=("checkin", checkin_id), scope="self",
        body=body.model_dump(mode="json"), key=idempotency_key,
        operation=lambda s, tx, actor, elder: s.checkins.create_or_update(tx, actor, elder, body, checkin_id))

@router.delete("/checkins/{checkin_id}", operation_id="REC04", response_model=Envelope[CancelledCheckin], status_code=200)
def rec04(ctx: Auth, checkin_id: str, idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=200)], expected_version: Annotated[int, Query(ge=1)]):
    return perform(ctx, service_name="checkins", resource=("checkin", checkin_id), scope="self",
        body={"expected_version": expected_version}, key=idempotency_key,
        operation=lambda s, tx, actor, elder: s.checkins.cancel(tx, actor, elder, checkin_id, expected_version))

@router.get("/elders/{elder_id}/dashboard", operation_id="DASH01", response_model=Envelope[Dashboard], status_code=200)
def dash01(ctx: Auth, elder_id: str, date: Date | None = None):
    return perform(ctx, service_name="reports", elder_id=elder_id, snapshot=True,
        operation=lambda s, tx, actor, elder: s.reports.dashboard(tx, actor, elder, date))

@router.get("/elders/{elder_id}/calendar", operation_id="CAL01", response_model=Envelope[Calendar], status_code=200)
def cal01(ctx: Auth, elder_id: str, month: Annotated[str, Query(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")]):
    return perform(ctx, service_name="reports", elder_id=elder_id, snapshot=True,
        operation=lambda s, tx, actor, elder: s.reports.calendar(tx, actor, elder, month))

@router.get("/elders/{elder_id}/reports/daily", operation_id="REPORT01", response_model=Envelope[DailyReport], status_code=200)
def report01(ctx: Auth, elder_id: str, date: Annotated[Date, Query()], include_ai: bool = False):
    if include_ai:
        from app.application.daily_report import enriched_report
        return enriched_report(ctx, elder_id, date)
    response = perform(ctx, service_name="reports", elder_id=elder_id, snapshot=True,
        operation=lambda s, tx, actor, elder: s.reports.daily(tx, actor, elder, date))
    if ctx.request.app.state.settings.safety_review_enabled and ctx.request.app.state.report_writer is not None:
        from starlette.background import BackgroundTask
        from app.application.daily_report import automatic_review
        response.background = BackgroundTask(automatic_review,ctx,elder_id,date)
    return response

@router.post("/elders/{elder_id}/presence", operation_id="NOTI01", response_model=Envelope[Presence], status_code=200)
def noti01(ctx: Auth, elder_id: str, body: PresenceWrite):
    return perform(ctx, service_name="notifications", elder_id=elder_id, scope="self",
        operation=lambda s, tx, actor, elder: s.notifications.presence(tx, actor, elder, body))

@router.get("/elders/{elder_id}/notifications", operation_id="NOTI02", response_model=Envelope[Page[Notification]], status_code=200)
def noti02(ctx: Auth, elder_id: str, task_state: TaskState | None = None, limit: Annotated[int, Query(ge=1, le=100)] = 20, cursor: str | None = None):
    return perform(ctx, service_name="notifications", elder_id=elder_id,
        operation=lambda s, tx, actor, elder: s.notifications.query(tx, actor, elder, task_state, limit, cursor))

@router.post("/notifications/{notification_id}/events", operation_id="NOTI03", response_model=Envelope[EventResult], status_code=200)
def noti03(ctx: Auth, notification_id: str, body: NotificationEvent, idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=200)]):
    return perform(ctx, service_name="notifications", resource=("notification", notification_id), scope="self",
        body=body.model_dump(mode="json"), key=idempotency_key,
        operation=lambda s, tx, actor, elder: s.notifications.handle_event(tx, actor, notification_id, body, ctx.request.app.state.clock.now()))

@router.post("/elders/{elder_id}/family-reminders", operation_id="NOTI04", response_model=Envelope[Notification], status_code=201)
def noti04(ctx: Auth, elder_id: str, body: FamilyReminderWrite, idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=200)]):
    return family_reminder(ctx, elder_id, body, idempotency_key)
