from datetime import date as Date
from typing import Annotated
from fastapi import APIRouter, Query, Header, UploadFile, File, Form, Response
from app.schemas.common import Envelope, Page
from app.schemas.enums import Category, ProposalStatus, TaskState
from app.routers.dependencies import Auth, Context, Public, access, resource_access, role
from app.schemas.identity import Dashboard, EventResult
from app.schemas.health import Calendar, CancelledCheckin, Checkin, CheckinUpdate, CheckinWrite, DailyReport, FamilyReminderWrite, MedicationPlan, MedicationPlanWrite, Notification, NotificationEvent, PlanList, PlanUpdate, Presence, PresenceWrite, ReminderSettings, SettingsUpdate, TaskList
from app.application.health_flows import unavailable, perform

router = APIRouter()

@router.get("/elders/{elder_id}/medication-plans", operation_id="PLAN01", response_model=Envelope[PlanList], status_code=200)
def plan01(ctx: Context, elder_id: str, active: bool | None = None):
    access(ctx, elder_id)
    unavailable(ctx.request.app.state.services)

@router.post("/elders/{elder_id}/medication-plans", operation_id="PLAN02", response_model=Envelope[MedicationPlan], status_code=201)
def plan02(ctx: Auth, elder_id: str, body: MedicationPlanWrite, idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=200)]):
    return perform(ctx, service_name="medication", elder_id=elder_id, scope="proposal",
        body=body.model_dump(mode="json"), key=idempotency_key, status=201,
        operation=lambda s, tx, actor, elder: s.medication.apply_change(tx, actor, elder, "create", None, body, None))

@router.put("/medication-plans/{plan_id}", operation_id="PLAN03", response_model=Envelope[MedicationPlan], status_code=200)
def plan03(ctx: Auth, plan_id: str, body: PlanUpdate, idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=200)]):
    return perform(ctx, service_name="medication", resource=("plan", plan_id), scope="proposal",
        body=body.model_dump(mode="json"), key=idempotency_key,
        operation=lambda s, tx, actor, elder: s.medication.apply_change(tx, actor, elder, "update", plan_id, body.patch, body.expected_version))

@router.get("/elders/{elder_id}/reminder-settings", operation_id="SET01", response_model=Envelope[ReminderSettings], status_code=200)
def set01(ctx: Context, elder_id: str):
    access(ctx, elder_id)
    unavailable(ctx.request.app.state.services)

@router.put("/elders/{elder_id}/reminder-settings", operation_id="SET02", response_model=Envelope[ReminderSettings], status_code=200)
def set02(ctx: Context, elder_id: str, body: SettingsUpdate, idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=200)]):
    access(ctx, elder_id, "proposal")
    unavailable(ctx.request.app.state.services)

@router.get("/elders/{elder_id}/tasks", operation_id="TASK01", response_model=Envelope[TaskList], status_code=200)
def task01(ctx: Auth, elder_id: str, date: Annotated[Date, Query()]):
    return perform(ctx, service_name="tasks", elder_id=elder_id, snapshot=True,
        operation=lambda s, tx, actor, elder: s.tasks.today(tx, actor, elder, date))

@router.get("/elders/{elder_id}/checkins", operation_id="REC01", response_model=Envelope[Page[Checkin]], status_code=200)
def rec01(ctx: Context, elder_id: str, date: Annotated[Date, Query()], type: Category | None = None, limit: Annotated[int, Query(ge=1, le=100)] = 20, cursor: str | None = None):
    access(ctx, elder_id)
    unavailable(ctx.request.app.state.services)

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
def rec04(ctx: Context, checkin_id: str, idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=200)], expected_version: Annotated[int, Query(ge=1)]):
    resource_access(ctx, "checkin", checkin_id, "self")
    unavailable(ctx.request.app.state.services)

@router.get("/elders/{elder_id}/dashboard", operation_id="DASH01", response_model=Envelope[Dashboard], status_code=200)
def dash01(ctx: Context, elder_id: str, date: Date | None = None):
    access(ctx, elder_id)
    unavailable(ctx.request.app.state.services)

@router.get("/elders/{elder_id}/calendar", operation_id="CAL01", response_model=Envelope[Calendar], status_code=200)
def cal01(ctx: Context, elder_id: str, month: Annotated[str, Query(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")]):
    access(ctx, elder_id)
    unavailable(ctx.request.app.state.services)

@router.get("/elders/{elder_id}/reports/daily", operation_id="REPORT01", response_model=Envelope[DailyReport], status_code=200)
def report01(ctx: Auth, elder_id: str, date: Annotated[Date, Query()]):
    return perform(ctx, service_name="reports", elder_id=elder_id, snapshot=True,
        operation=lambda s, tx, actor, elder: s.reports.daily(tx, actor, elder, date))

@router.post("/elders/{elder_id}/presence", operation_id="NOTI01", response_model=Envelope[Presence], status_code=200)
def noti01(ctx: Context, elder_id: str, body: PresenceWrite):
    access(ctx, elder_id, "self")
    unavailable(ctx.request.app.state.services)

@router.get("/elders/{elder_id}/notifications", operation_id="NOTI02", response_model=Envelope[Page[Notification]], status_code=200)
def noti02(ctx: Context, elder_id: str, task_state: TaskState | None = None, limit: Annotated[int, Query(ge=1, le=100)] = 20, cursor: str | None = None):
    access(ctx, elder_id)
    unavailable(ctx.request.app.state.services)

@router.post("/notifications/{notification_id}/events", operation_id="NOTI03", response_model=Envelope[EventResult], status_code=200)
def noti03(ctx: Auth, notification_id: str, body: NotificationEvent, idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=200)]):
    return perform(ctx, service_name="notifications", resource=("notification", notification_id), scope="self",
        body=body.model_dump(mode="json"), key=idempotency_key,
        operation=lambda s, tx, actor, elder: s.notifications.handle_event(tx, actor, notification_id, body, ctx.request.app.state.clock.now()))

@router.post("/elders/{elder_id}/family-reminders", operation_id="NOTI04", response_model=Envelope[Notification], status_code=201)
def noti04(ctx: Context, elder_id: str, body: FamilyReminderWrite, idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=200)]):
    access(ctx, elder_id, "child")
    unavailable(ctx.request.app.state.services)
