from datetime import date, datetime
from sqlalchemy import String, JSON, ForeignKey, UniqueConstraint, CheckConstraint, Index, text
from sqlalchemy.orm import Mapped, mapped_column
from app.core.db import Base, UTCDateTime
from app.core.ids import new_id

class MedicationPlan(Base):
    __tablename__ = "medication_plans"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("plan"))
    elder_id: Mapped[str] = mapped_column(ForeignKey("elder_profiles.id"))
    name: Mapped[str] = mapped_column(String)
    dose_display: Mapped[str] = mapped_column(String)
    schedule: Mapped[dict] = mapped_column(JSON)
    start_date: Mapped[date] = mapped_column()
    end_date: Mapped[date | None] = mapped_column()
    medicine_asset_id: Mapped[str | None] = mapped_column(ForeignKey("media_assets.id"))
    notes: Mapped[str] = mapped_column(default="")
    active: Mapped[bool] = mapped_column(default=True)
    version: Mapped[int] = mapped_column(default=1)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime)
    __table_args__ = (CheckConstraint("version >= 1"), CheckConstraint("end_date IS NULL OR end_date >= start_date"))
class DailyTask(Base):
    __tablename__ = "daily_tasks"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("task"))
    elder_id: Mapped[str] = mapped_column(ForeignKey("elder_profiles.id"))
    local_date: Mapped[date] = mapped_column()
    category: Mapped[str] = mapped_column(String)
    slot_key: Mapped[str] = mapped_column(String)
    plan_id: Mapped[str | None] = mapped_column(ForeignKey("medication_plans.id"))
    plan_version: Mapped[int | None] = mapped_column()
    plan_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    title: Mapped[str] = mapped_column(String)
    dose_display: Mapped[str | None] = mapped_column(String)
    due_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    waiting_for_meal: Mapped[bool] = mapped_column(default=False)
    source_key: Mapped[str | None] = mapped_column(String, unique=True)
    # Soft deactivation: a task that already has notifications/FKs is never deleted,
    # so deleting a future slot or deactivating a plan keeps history and the report
    # denominator intact while the row stops counting as an open goal.
    cancelled_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    __table_args__ = (UniqueConstraint("elder_id", "local_date", "category", "slot_key"), CheckConstraint("category IN ('diet','exercise','medication')"))
class DailyGoalBatch(Base):
    """One row per (elder, local date, category) that has materialised goals.

    Presence of the row means "this day's goals for the category were generated at
    generated_at". It distinguishes "generated and nothing applicable" (row exists,
    expected=0) from "never generated" (no row) - a past date must never be
    back-filled from today's plan or settings.
    """
    __tablename__ = "daily_goal_batches"
    elder_id: Mapped[str] = mapped_column(ForeignKey("elder_profiles.id"), primary_key=True)
    local_date: Mapped[date] = mapped_column(primary_key=True)
    category: Mapped[str] = mapped_column(String, primary_key=True)
    generated_at: Mapped[datetime] = mapped_column(UTCDateTime)
    __table_args__ = (CheckConstraint("category IN ('diet','exercise','medication')"),)
class Checkin(Base):
    __tablename__ = "checkins"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("checkin"))
    elder_id: Mapped[str] = mapped_column(ForeignKey("elder_profiles.id"))
    type: Mapped[str] = mapped_column(String)
    local_date: Mapped[date] = mapped_column()
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime)
    task_id: Mapped[str | None] = mapped_column(ForeignKey("daily_tasks.id"))
    payload_json: Mapped[dict] = mapped_column(JSON)
    slot_key: Mapped[str | None] = mapped_column(String)
    version: Mapped[int] = mapped_column(default=1)
    revisions_json: Mapped[list] = mapped_column(JSON, default=list)
    cancelled_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    source: Mapped[str] = mapped_column(default="user")
    source_key: Mapped[str | None] = mapped_column(String, unique=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime)
    __table_args__ = (Index("uq_live_meal", "elder_id", "local_date", "slot_key", unique=True, sqlite_where=text("type='diet' AND cancelled_at IS NULL")), Index("uq_live_medication", "task_id", unique=True, sqlite_where=text("type='medication' AND cancelled_at IS NULL")), CheckConstraint("type IN ('diet','exercise','medication')"), CheckConstraint("type != 'medication' OR task_id IS NOT NULL"), CheckConstraint("type != 'diet' OR slot_key IS NOT NULL"), CheckConstraint("version >= 1"))
class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("notice"))
    elder_id: Mapped[str] = mapped_column(ForeignKey("elder_profiles.id"))
    source_key: Mapped[str] = mapped_column(String, unique=True)
    kind: Mapped[str] = mapped_column(String)
    title: Mapped[str] = mapped_column(String)
    text: Mapped[str] = mapped_column(String)
    audio_asset_id: Mapped[str | None] = mapped_column(ForeignKey("media_assets.id"))
    repeat_count: Mapped[int] = mapped_column(default=1)
    due_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    delivery_state: Mapped[str] = mapped_column(default="pending")
    task_state: Mapped[str] = mapped_column(default="open")
    push_state: Mapped[str] = mapped_column(default="unsupported")
    displayed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    answered_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    played_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    snoozed_until: Mapped[datetime | None] = mapped_column(UTCDateTime)
    proposal_id: Mapped[str | None] = mapped_column(ForeignKey("change_proposals.id"))
    related_task_id: Mapped[str | None] = mapped_column(ForeignKey("daily_tasks.id"))
    __table_args__ = (CheckConstraint("repeat_count BETWEEN 1 AND 3"), CheckConstraint("delivery_state IN ('pending','displayed','answered','played')"), CheckConstraint("task_state IN ('open','snoozed','handled','dismissed')"), CheckConstraint("push_state IN ('not_attempted','unsupported','sent','failed')"))
class NotificationEvent(Base):
    __tablename__ = "notification_events"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    notification_id: Mapped[str] = mapped_column(ForeignKey("notifications.id"))
    actor_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    event_type: Mapped[str] = mapped_column(String)
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime)
    payload_json: Mapped[dict] = mapped_column(JSON)
class Presence(Base):
    __tablename__ = "presence"
    elder_id: Mapped[str] = mapped_column(ForeignKey("elder_profiles.id"), primary_key=True)
    client_id: Mapped[str] = mapped_column(String, primary_key=True)
    active_until: Mapped[datetime] = mapped_column(UTCDateTime)


class SafetySignal(Base):
    __tablename__ = "safety_signals"
    id: Mapped[str] = mapped_column(String,primary_key=True,default=lambda:new_id("safety"))
    elder_id: Mapped[str] = mapped_column(ForeignKey("elder_profiles.id"))
    local_date: Mapped[date] = mapped_column()
    issue_key: Mapped[str] = mapped_column(String)
    payload: Mapped[dict] = mapped_column(JSON)
    fingerprint: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String)
    revision: Mapped[int] = mapped_column(default=1)
    detected_at: Mapped[datetime] = mapped_column(UTCDateTime)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime)
    history: Mapped[list] = mapped_column(JSON,default=list)
    __table_args__=(UniqueConstraint("elder_id","local_date","issue_key"),CheckConstraint("status IN ('active','resolved')"),CheckConstraint("revision >= 1"))

class SafetyAssessment(Base):
    __tablename__="safety_assessments"
    elder_id: Mapped[str] = mapped_column(ForeignKey("elder_profiles.id"),primary_key=True)
    local_date: Mapped[date] = mapped_column(primary_key=True)
    input_digest: Mapped[str] = mapped_column(String)
    model: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String)
    reviewed_at: Mapped[datetime] = mapped_column(UTCDateTime)
    __table_args__=(CheckConstraint("status IN ('reviewed','insufficient_data','unavailable')"),)
