from datetime import date
from typing import Annotated, Literal
from pydantic import Field, AwareDatetime, model_validator
from app.schemas.common import DTO
from app.schemas.enums import Category, MealSlot, DeliveryState, TaskState, PushState, NotificationKind, EventType

LocalTime = Annotated[str, Field(pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")]
class FixedSlot(DTO):
    slot_id: str = Field(min_length=1)
    local_time: LocalTime
class AfterMealSlot(DTO):
    slot_id: str = Field(min_length=1)
    meal_slot: MealSlot
    delay_minutes: int = Field(ge=0, le=240)
class FixedSchedule(DTO):
    mode: Literal["fixed"]
    slots: list[FixedSlot] = Field(min_length=1)
class AfterMealSchedule(DTO):
    mode: Literal["after_meal"]
    slots: list[AfterMealSlot] = Field(min_length=1)
Schedule = Annotated[FixedSchedule | AfterMealSchedule, Field(discriminator="mode")]

class MedicationPlanWrite(DTO):
    name: str = Field(min_length=1)
    dose_display: str = Field(min_length=1)
    schedule: Schedule
    start_date: date
    end_date: date | None = None
    medicine_asset_id: str | None = None
    notes: str = ""
    @model_validator(mode="after")
    def valid_schedule(self):
        if len({s.slot_id for s in self.schedule.slots}) != len(self.schedule.slots):
            raise ValueError("slot_id must be unique within a plan")
        if self.end_date and self.end_date < self.start_date:
            raise ValueError("end_date precedes start_date")
        return self
class MedicationPlan(MedicationPlanWrite):
    plan_id: str
    elder_id: str
    version: int = Field(ge=1)
    active: bool
    updated_at: AwareDatetime
class PlanPatch(DTO):
    name: str | None = Field(default=None, min_length=1)
    dose_display: str | None = Field(default=None, min_length=1)
    schedule: Schedule | None = None
    start_date: date | None = None
    end_date: date | None = None
    medicine_asset_id: str | None = None
    notes: str | None = None
    @model_validator(mode="after")
    def nonempty(self):
        if not self.model_fields_set:
            raise ValueError("patch must not be empty")
        for k in self.model_fields_set - {"end_date", "medicine_asset_id"}:
            if getattr(self, k) is None:
                raise ValueError(f"{k} cannot be null")
        if self.schedule and len({s.slot_id for s in self.schedule.slots}) != len(self.schedule.slots):
            raise ValueError("duplicate slot_id")
        return self
class PlanUpdate(DTO):
    expected_version: int = Field(ge=1)
    patch: PlanPatch
class PlanList(DTO):
    items: list[MedicationPlan]
class TimedReminder(DTO):
    enabled: bool
    local_time: LocalTime
class MealReminder(TimedReminder):
    slot: MealSlot
class SettingsPatch(DTO):
    meals: list[MealReminder] | None = None
    exercise: TimedReminder | None = None
    daily_summary: TimedReminder | None = None
    voice_enabled: bool | None = None
    @model_validator(mode="after")
    def valid_patch(self):
        if not self.model_fields_set or any(getattr(self,k) is None for k in self.model_fields_set):
            raise ValueError("patch must be nonempty with non-null fields")
        if self.meals is not None and len({m.slot for m in self.meals}) != len(self.meals):
            raise ValueError("duplicate meal slot")
        return self
class ReminderSettings(DTO):
    version: int = Field(ge=1)
    meals: list[MealReminder]
    exercise: TimedReminder
    daily_summary: TimedReminder
    voice_enabled: bool
class SettingsUpdate(DTO):
    expected_version: int = Field(ge=1)
    patch: SettingsPatch
class DailyTask(DTO):
    task_id: str
    date: date
    category: Category
    slot_key: str
    plan_id: str | None
    plan_version: int | None
    title: str
    dose_display: str | None
    due_at: AwareDatetime | None
    waiting_for_meal: bool
    completion: Literal["pending", "completed", "not_taken"]
    checkin_ids: list[str]
    # A cancelled goal keeps its row for history but no longer counts as open.
    cancelled: bool = False
class TaskList(DTO):
    date: date
    items: list[DailyTask]
class DietPayload(DTO):
    meal_slot: MealSlot
    foods: list[Annotated[str, Field(min_length=1)]] = Field(min_length=1)
    food_groups: list[Literal["vegetable", "protein", "staple", "fruit", "dairy", "fat", "other"]] = Field(default_factory=list)
    image_asset_ids: list[str] = Field(default_factory=list)
    notes: str = ""
    suggestions: list[str] = Field(default_factory=list)
class ExercisePayload(DTO):
    activity: str = Field(min_length=1)
    duration_minutes: int = Field(ge=1, le=1440)
    notes: str = ""
class MedicationPayload(DTO):
    plan_id: str
    slot_id: str
    intake_status: Literal["taken", "not_taken"]
    notes: str = ""
class DietWrite(DTO):
    type: Literal["diet"]
    occurred_at: AwareDatetime
    payload: DietPayload
    task_id: str | None = None
class ExerciseWrite(DTO):
    type: Literal["exercise"]
    occurred_at: AwareDatetime
    payload: ExercisePayload
    task_id: str | None = None
class MedicationWrite(DTO):
    type: Literal["medication"]
    occurred_at: AwareDatetime
    payload: MedicationPayload
    task_id: str = Field(min_length=1)
CheckinWrite = Annotated[DietWrite | ExerciseWrite | MedicationWrite, Field(discriminator="type")]
class CheckinUpdate(DTO):
    expected_version: int = Field(ge=1)
    occurred_at: AwareDatetime | None = None
    payload: DietPayload | ExercisePayload | MedicationPayload
class Checkin(DTO):
    checkin_id: str
    elder_id: str
    type: Category
    local_date: date
    occurred_at: AwareDatetime
    task_id: str | None
    payload: DietPayload | ExercisePayload | MedicationPayload
    version: int = Field(ge=1)
    source: Literal["user", "agent_confirmed", "demo_seed"]
    created_at: AwareDatetime
    updated_at: AwareDatetime
    cancelled: bool
class CancelledCheckin(DTO):
    checkin_id: str
    cancelled: Literal[True]
    version: int = Field(ge=1)
class ProgressCount(DTO):
    completed: int = Field(ge=0)
    expected: int = Field(ge=0)
    applicable: bool
class Progress(DTO):
    diet: ProgressCount
    exercise: ProgressCount
    medication: ProgressCount
class CalendarDay(DTO):
    date: date
    state: Literal["complete", "partial", "unrecorded", "future"]
    color: Literal["green", "yellow", "gray"] | None
    is_today: bool
    progress: Progress
class Calendar(DTO):
    month: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    days: list[CalendarDay]
class Records(DTO):
    diet: list[Checkin]
    exercise: list[Checkin]
    medication: list[Checkin]
class AttentionItem(DTO):
    id: str
    kind: Literal["record_missing", "record_not_taken", "pending_confirmation", "family_concern"]
    title: str
    detail: str
    source_ids: list[str]
    can_remind: bool
class DailyReport(DTO):
    elder_id: str
    date: date
    completion: CalendarDay
    records: Records
    summary_text: str
    attention_items: list[AttentionItem]
    updated_at: AwareDatetime
class PresenceWrite(DTO):
    client_id: str = Field(min_length=1)
    visible: bool
class Presence(DTO):
    active_until: AwareDatetime | None
    server_time: AwareDatetime
class Notification(DTO):
    notification_id: str
    elder_id: str
    kind: NotificationKind
    title: str
    text: str
    audio_asset_id: str | None
    repeat_count: int = Field(ge=1, le=3)
    due_at: AwareDatetime
    delivery_state: DeliveryState
    task_state: TaskState
    push_state: PushState
    displayed_at: AwareDatetime | None
    answered_at: AwareDatetime | None
    played_at: AwareDatetime | None
    proposal_id: str | None
    related_task_id: str | None
class NotificationEvent(DTO):
    event_id: str = Field(min_length=1)
    event_type: EventType
    snooze_minutes: int | None = Field(default=None, ge=1, le=120)
    @model_validator(mode="after")
    def snooze(self):
        if (self.event_type == EventType.snoozed) != (self.snooze_minutes is not None):
            raise ValueError("snooze_minutes required only for snoozed")
        return self
class FamilyReminderWrite(DTO):
    category: Literal["diet", "exercise", "medication", "general"]
    template_id: str | None = None
    text: str | None = Field(default=None, min_length=1)
    audio_asset_id: str | None = None
    repeat_count: int = Field(default=1, ge=1, le=3)
    related_task_id: str | None = None
    @model_validator(mode="after")
    def content(self):
        if not (self.template_id or self.text or self.audio_asset_id):
            raise ValueError("template, text or audio is required")
        return self
class NotificationEnqueue(FamilyReminderWrite):
    elder_id: str
    kind: NotificationKind
    title: str
    due_at: AwareDatetime
    proposal_id: str | None = None
