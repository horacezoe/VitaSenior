from typing import Literal, Annotated
from pydantic import Field, AwareDatetime, model_validator
from app.schemas.common import DTO, SourceRef
from app.schemas.enums import ActionStatus, ActionType
from app.schemas.identity import MediaAsset, ProfilePatch, ProfileUpdate, ChangeDecision, BindingCode, Profile, ChangeProposal, EventResult, EmptyPatch
from app.schemas.health import DietPayload, ExercisePayload, MedicationPayload, MedicationPlanWrite, PlanUpdate, NotificationEvent, Checkin, MedicationPlan, DailyReport, Notification

class ASRWrite(DTO):
    elder_id: str
    audio_asset_id: str
    mock_fixture_id: str | None = None
class ASRResult(DTO):
    transcript: str
    language: str
    provider: str
    is_mock: bool
class TTSWrite(DTO):
    elder_id: str
    text: str = Field(min_length=1, max_length=5000)
    voice_id: str | None = None
class TTSResult(DTO):
    audio_asset: MediaAsset
    provider: str
    is_mock: bool
class TurnContext(DTO):
    notification_id: str | None = None
    pending_action_id: str | None = None
    scene: Literal["meal", "ingredient", "medicine", "document"] | None = None
class AgentTurnWrite(DTO):
    elder_id: str
    conversation_id: str | None = None
    client_turn_id: str = Field(min_length=1)
    text: str | None = Field(default=None, min_length=1)
    audio_asset_id: str | None = None
    image_asset_ids: list[str] = Field(default_factory=list, max_length=3)
    context: TurnContext = Field(default_factory=TurnContext)
    mock_fixture_id: str | None = None
    @model_validator(mode="after")
    def input_present(self):
        if not (self.text or self.audio_asset_id or self.image_asset_ids):
            raise ValueError("text, audio or images required")
        if self.image_asset_ids and not (self.text or self.audio_asset_id) and self.context.scene is None:
            raise ValueError("image-only input requires context.scene")
        return self
class Reply(DTO):
    text: str
    audio_asset_id: str | None = None
class MemoryChange(DTO):
    version: int = Field(ge=1)
    changed: bool
class Providers(DTO):
    chat: str
    asr: str
    tts: str
class RecordDietPreview(DietPayload):
    pass
class RecordExercisePreview(ExercisePayload):
    pass
class RecordMedicationPreview(MedicationPayload):
    task_id: str
class NotificationPreview(NotificationEvent):
    notification_id: str
class ChangePreview(ChangeDecision):
    proposal_id: str
class MemoryPreview(DTO):
    text: str
class ReportPreview(DTO):
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
class ActionBase(DTO):
    action_id: str
    status: ActionStatus
    requires_confirmation: bool
    expires_at: AwareDatetime
class DietAction(ActionBase):
    type: Literal["record_diet"]
    preview: RecordDietPreview
class ExerciseAction(ActionBase):
    type: Literal["record_exercise"]
    preview: RecordExercisePreview
class MedicationAction(ActionBase):
    type: Literal["record_medication"]
    preview: RecordMedicationPreview
class CreatePlanAction(ActionBase):
    type: Literal["create_medication_plan"]
    preview: MedicationPlanWrite
class UpdatePlanAction(ActionBase):
    type: Literal["update_medication_plan"]
    preview: PlanUpdate
class ProfileAction(ActionBase):
    type: Literal["update_profile"]
    preview: ProfileUpdate
class BindingAction(ActionBase):
    type: Literal["create_binding_code"]
    preview: EmptyPatch
class NotificationAction(ActionBase):
    type: Literal["respond_notification"]
    preview: NotificationPreview
class ChangeAction(ActionBase):
    type: Literal["decide_change"]
    preview: ChangePreview
class MemoryAction(ActionBase):
    type: Literal["update_memory"]
    preview: MemoryPreview
class ReportAction(ActionBase):
    type: Literal["query_report"]
    preview: ReportPreview
Action = Annotated[DietAction | ExerciseAction | MedicationAction | CreatePlanAction | UpdatePlanAction | ProfileAction | BindingAction | NotificationAction | ChangeAction | MemoryAction | ReportAction, Field(discriminator="type")]
class AgentTurn(DTO):
    turn_id: str
    conversation_id: str
    transcript: str
    reply: Reply
    scene: Literal["meal_checkin", "ingredient_advice", "exercise_checkin", "medication_checkin", "health_qa", "daily_query", "profile_update", "binding_code", "reminder_response", "memory_update", "clarify"]
    avatar_state: Literal["idle", "listening", "thinking", "speaking", "error"]
    actions: list[Action]
    memory: MemoryChange
    providers: Providers
    degraded: list[Literal["tts_unavailable", "asr_unavailable", "chat_unavailable"]]
class ActionDecision(DTO):
    decision: Literal["confirm", "cancel"]
    amendments: DietPayload | ExercisePayload | MedicationPayload | MedicationPlanWrite | PlanUpdate | ProfileUpdate | None = None
class MemoryEntry(DTO):
    entry_id: str
    kind: Literal["food_preference", "meal_routine", "lifestyle", "communication", "recent_concern"]
    text: str
    source_type: Literal["explicit_statement", "observed_pattern", "user_correction", "demo_seed"]
    source_ids: list[SourceRef]
    created_at: AwareDatetime
    updated_at: AwareDatetime
class MemoryDocument(DTO):
    elder_id: str
    version: int = Field(ge=1)
    updated_at: AwareDatetime
    entries: list[MemoryEntry]
    markdown: str
class MemoryUpdate(DTO):
    expected_version: int = Field(ge=1)
    text: str = Field(min_length=1)

class ActionResult(DTO):
    action_id: str
    status: ActionStatus
    result: Checkin | MedicationPlan | BindingCode | DailyReport | Profile | MemoryDocument | EventResult | ChangeProposal | Notification | SourceRef | None
    reply: Reply
