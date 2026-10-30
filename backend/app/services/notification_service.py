from datetime import datetime, timedelta

from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.contracts.context import Actor
from app.contracts.ports import AccessPort, ChangePort, MediaPort
from app.core.clock import Clock, SystemClock, local_date
from app.core.errors import AppError, unimplemented
from app.models.health import Notification as NoticeRow, NotificationEvent as EventRow, Presence as PresenceRow, DailyTask
from app.models.identity import ElderProfile
from app.schemas.common import Page
from app.schemas.health import NotificationEnqueue, Notification, NotificationEvent, Presence, PresenceWrite
from app.schemas.identity import EventResult
from app.services.health_service import authorize, invalid, materialize_tasks, live_records, task_dto, settings_for, at_local


TEMPLATES = {
    "diet": "记得记录今天的餐食，有需要时告诉我。",
    "exercise": "今天活动了吗？可以告诉我您的运动记录。",
    "medication": "请核对既定用药任务，服用后请明确确认。",
    "general": "家人惦记着您，有需要时请告诉我们。",
}


def notice_dto(row):
    return Notification(notification_id=row.id, elder_id=row.elder_id, kind=row.kind,
        title=row.title, text=row.text, audio_asset_id=row.audio_asset_id, repeat_count=row.repeat_count,
        due_at=row.due_at, delivery_state=row.delivery_state, task_state=row.task_state,
        push_state=row.push_state, displayed_at=row.displayed_at, answered_at=row.answered_at,
        played_at=row.played_at, proposal_id=row.proposal_id, related_task_id=row.related_task_id)


def transition_error(message):
    raise AppError(409, "INVALID_NOTIFICATION_TRANSITION", message)


class NotificationService:
    def __init__(self, clock: Clock | None = None, *, access: AccessPort | None = None,
                 media: MediaPort | None = None, changes: ChangePort | None = None):
        self.clock, self.access, self.media, self.changes = clock or SystemClock(), access, media, changes

    def bind(self, *, changes=None) -> "NotificationService":
        """Preserve A2's late-binding seam; only composition calls this."""
        if changes is not None:
            self.changes = changes
        return self

    def mark_proposal_handled(self, tx: Session, notification_id: str) -> None:
        """Trusted A2 system hook; no actor forgery or proposal state machine."""
        row = tx.get(NoticeRow, notification_id)
        if row is None or row.proposal_id is None:
            raise AppError(404, "NOT_FOUND", "Proposal notification unavailable")
        row.task_state = "handled"
        tx.flush()

    def presence(self, tx, actor, elder_id, body: PresenceWrite):
        authorize(tx, actor, elder_id, "self", self.access)
        now = self.clock.now()
        row = tx.get(PresenceRow, (elder_id, body.client_id))
        if body.visible:
            if row is None:
                row = PresenceRow(elder_id=elder_id, client_id=body.client_id)
                tx.add(row)
            row.active_until = now + timedelta(seconds=25)
        elif row:
            tx.delete(row)
        tx.flush()
        return Presence(active_until=row.active_until if body.visible else None, server_time=now)

    def query(self, tx, actor, elder_id, task_state=None, limit=20, cursor=None):
        authorize(tx, actor, elder_id, access=self.access)
        query = select(NoticeRow).where(NoticeRow.elder_id == elder_id)
        if task_state is not None:
            query = query.where(NoticeRow.task_state == task_state)
        rows = list(tx.scalars(query.order_by(NoticeRow.due_at, NoticeRow.id)))
        rows = [r for r in rows if not (r.delivery_state == "pending" and r.related_task_id
                and tx.get(DailyTask, r.related_task_id).waiting_for_meal)]
        if cursor:
            indexes = [i for i, row in enumerate(rows) if row.id == cursor]
            if not indexes:
                invalid("Cursor does not belong to this notification query")
            rows = rows[indexes[0] + 1:]
        return Page[Notification](items=[notice_dto(r) for r in rows[:limit]],
            next_cursor=rows[limit - 1].id if len(rows) > limit else None)

    def _enqueue(self, tx, source_key, payload):
        """Trusted deterministic insertion, also used by this domain's scanner.

        Caller already authorized an actor OR selected elders via the internal
        scan. No synthetic user actor, network call or delivery side effect.
        """
        if not source_key:
            invalid("source_key must not be empty")
        old = tx.scalar(select(NoticeRow).where(NoticeRow.source_key == source_key))
        text = payload.text
        if payload.template_id:
            if payload.template_id not in TEMPLATES:
                invalid("Unknown reminder template")
            text = text or TEMPLATES[payload.template_id]
        text = text or "请收听家人的录音。"
        if old:
            values = (payload.elder_id, payload.kind, payload.title, text,
                      payload.audio_asset_id, payload.repeat_count, payload.proposal_id, payload.related_task_id)
            previous = (old.elder_id, old.kind, old.title, old.text, old.audio_asset_id,
                        old.repeat_count, old.proposal_id, old.related_task_id)
            if values != previous:
                raise AppError(409, "IDEMPOTENCY_CONFLICT", "source_key belongs to a different notification")
            return notice_dto(old)
        if payload.related_task_id:
            task = tx.get(DailyTask, payload.related_task_id)
            if task is None or task.elder_id != payload.elder_id:
                invalid("Reminder task does not belong to this elder")
            if payload.category != "general" and task.category != payload.category:
                invalid("Reminder category does not match task")
        if payload.proposal_id:
            if self.changes is None:
                unimplemented()
            # The public enqueue path checks proposal access using its real
            # actor before entering this helper. System scan never enqueues proposals.
        row = NoticeRow(elder_id=payload.elder_id, source_key=source_key, kind=payload.kind.value,
            title=payload.title, text=text, audio_asset_id=payload.audio_asset_id,
            repeat_count=payload.repeat_count, due_at=payload.due_at,
            proposal_id=payload.proposal_id, related_task_id=payload.related_task_id)
        tx.add(row)
        tx.flush()
        return notice_dto(row)

    def enqueue(self, tx: Session, actor: Actor, source_key: str, payload: NotificationEnqueue) -> Notification:
        authorize(tx, actor, payload.elder_id, access=self.access)
        if payload.kind == "family_voice":
            authorize(tx, actor, payload.elder_id, "child", self.access)
        if payload.audio_asset_id:
            if self.media is None:
                unimplemented()
            asset = self.media.get_asset(tx, actor, payload.audio_asset_id)
            if not asset.mime_type.startswith("audio/") or asset.size_bytes == 0:
                invalid("Reminder audio must be a nonempty audio asset")
        if payload.proposal_id:
            if self.changes is None:
                unimplemented()
            proposal = self.changes.read(tx, actor, payload.proposal_id)
            if proposal.elder_id != payload.elder_id:
                invalid("Proposal does not belong to reminder elder")
        return self._enqueue(tx, source_key, payload)

    def handle_event(self, tx: Session, actor: Actor, notification_id: str,
                     event: NotificationEvent, now: datetime) -> EventResult:
        row = tx.get(NoticeRow, notification_id)
        if row is None:
            raise AppError(404, "NOT_FOUND", "Notification unavailable")
        try:
            authorize(tx, actor, row.elder_id, "self", self.access)
        except AppError as exc:
            raise AppError(404, "NOT_FOUND", "Notification unavailable") from exc
        saved = tx.get(EventRow, event.event_id)
        event_data = event.model_dump(mode="json")
        if saved:
            if (saved.actor_user_id != actor.user_id or saved.notification_id != notification_id
                    or saved.payload_json.get("event") != event_data):
                raise AppError(409, "IDEMPOTENCY_CONFLICT", "event_id was used for another event")
            return EventResult.model_validate(saved.payload_json["result"])
        kind = event.event_type.value
        proposal = None
        if kind in {"displayed", "answered", "playback_completed"}:
            visible = tx.scalar(select(PresenceRow.client_id).where(
                PresenceRow.elder_id == row.elder_id, PresenceRow.active_until > now))
            if not visible:
                raise AppError(409, "APP_NOT_VISIBLE", "A current visible heartbeat is required")
            if row.due_at > now or (row.snoozed_until and row.snoozed_until > now):
                transition_error("Reminder is not due")
            if row.related_task_id and tx.get(DailyTask, row.related_task_id).waiting_for_meal:
                transition_error("The related task is still waiting for a meal")
            if row.task_state not in {"open", "snoozed"}:
                transition_error("Reminder is already handled or dismissed")
            if kind == "displayed":
                if row.delivery_state == "pending":
                    row.delivery_state, row.displayed_at = "displayed", now
                # Late receipts cannot move a played/answered call backwards.
            elif kind == "answered":
                if row.delivery_state == "pending":
                    transition_error("Display the reminder before answering")
                if row.delivery_state == "displayed":
                    row.delivery_state, row.answered_at = "answered", now
            else:
                if row.delivery_state not in {"answered", "played"}:
                    transition_error("Answer before completing playback")
                if row.audio_asset_id is None or self.media is None:
                    transition_error("No playable audio is registered")
                asset = self.media.get_asset(tx, actor, row.audio_asset_id)
                if not asset.mime_type.startswith("audio/") or asset.size_bytes == 0:
                    transition_error("Audio playback is unavailable")
                # Each distinct completion receipt attests one full play. Store
                # receipts durably; duplicate event IDs cannot increase this count.
                played = tx.scalar(select(func.count()).select_from(EventRow).where(
                    EventRow.notification_id == row.id, EventRow.event_type == "playback_completed"))
                if row.delivery_state != "played" and played + 1 >= row.repeat_count:
                    row.delivery_state, row.played_at = "played", now
                    if row.proposal_id:
                        if self.changes is None:
                            unimplemented()
                        proposal = self.changes.mark_played(tx, actor, row.proposal_id, now)
        else:
            if row.proposal_id:
                transition_error("Use the proposal accept/reject decision")
            if row.task_state in {"handled", "dismissed"}:
                transition_error("Reminder is already resolved")
            if kind == "handled":
                row.task_state = "handled"
            elif kind == "dismissed":
                row.task_state = "dismissed"
            elif kind == "snoozed":
                row.task_state, row.snoozed_until = "snoozed", now + timedelta(minutes=event.snooze_minutes)
        tx.flush()
        result = EventResult(notification=notice_dto(row), change_proposal=proposal)
        tx.add(EventRow(id=event.event_id, notification_id=row.id, actor_user_id=actor.user_id,
            event_type=kind, occurred_at=now, payload_json={"event": event_data, "result": result.model_dump(mode="json", exclude_unset=True)}))
        tx.flush()
        return result

    def scan(self, tx: Session, now: datetime) -> list[Notification]:
        """Internal system entry. Select today's goals; never ring for old seeds.

        A wires this through a frozen system port/tick hook. This method owns no
        Session and does no TTS, media I/O, push or proposal state transitions.
        """
        day = local_date(now)
        result = []
        for elder in tx.scalars(select(ElderProfile).order_by(ElderProfile.id)):
            tasks = materialize_tasks(tx, elder.id, day, now)
            records = live_records(tx, elder.id, day)
            settings = settings_for(tx, elder.id)
            for task in tasks:
                if task.waiting_for_meal or task.due_at is None or task.due_at > now:
                    continue
                if task_dto(task, records).completion != "pending":
                    continue
                if task.category == "diet" and not any(m.enabled and m.slot == task.slot_key for m in settings.meals):
                    continue
                if task.category == "exercise" and not settings.exercise.enabled:
                    continue
                source = f"reminder:{task.source_key or task.id}"
                # Repeated scan or service restart never updates delivery state.
                result.append(self._enqueue(tx, source, NotificationEnqueue(
                    elder_id=elder.id, category=task.category,
                    kind={"diet": "meal_checkin", "exercise": "exercise_checkin", "medication": "medication"}[task.category],
                    title=task.title, text=TEMPLATES[task.category], due_at=task.due_at, related_task_id=task.id)))
            if settings.daily_summary.enabled and at_local(day, settings.daily_summary.local_time) <= now:
                result.append(self._enqueue(tx, f"summary:{elder.id}:{day}", NotificationEnqueue(
                    elder_id=elder.id, category="general", kind="daily_summary", title="今日记录待核对",
                    text="可以查看今天的记录；尚未记录不代表实际未完成。", due_at=at_local(day, settings.daily_summary.local_time))))
        return result
