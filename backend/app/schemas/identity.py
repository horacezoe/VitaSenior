from datetime import date
from typing import Literal, Annotated
from pydantic import BaseModel, Field, AwareDatetime, field_serializer, model_validator
from app.schemas.common import DTO
from app.schemas.enums import Role, ProposalStatus
from app.schemas.health import MedicationPlanWrite, MedicationPlan, PlanPatch, SettingsPatch, ReminderSettings, Notification, CalendarDay, Records, DailyTask, AttentionItem

class Account(DTO):
    phone: str = Field(pattern=r"^\d{11}$")
    role: Role
class User(Account):
    user_id: str
    demo_id: str
class CodeRequest(Account):
    pass
class CodeResponse(DTO):
    challenge_id: str
    expires_in: Literal[300] = 300
    demo_code: Literal["123456"] = "123456"
    is_mock: Literal[True] = True
class LoginRequest(Account):
    challenge_id: str
    code: str = Field(pattern=r"^\d{6}$")
class ElderSummary(DTO):
    elder_id: str
    display_name: str
    age: int | None
    conditions: list[str]
    binding_id: str | None
    relationship: str | None
class Me(DTO):
    user: User
    elder_id: str | None
    bound_elders: list[ElderSummary]
class LoginResponse(Me):
    access_token: str
    expires_at: AwareDatetime
class DemoWrite(DTO):
    scenario: Literal["diabetes_daily"] = "diabetes_daily"
class DemoExperience(DTO):
    demo_id: str
    scenario: Literal["diabetes_daily"]
    is_mock: Literal[True]
    elder_account: Account
    child_account: Account
    elder_id: str
    entry_url: str
    pair_entry_url: str
    history_days: Literal[14]
class ProfileFields(DTO):
    display_name: str = Field(min_length=1)
    birth_date: date | None = None
    sex: Literal["male", "female", "other", "unknown"] = "unknown"
    conditions: list[str] = Field(default_factory=list)
    allergies: list[str] = Field(default_factory=list)
    medical_notes: str = ""
class Profile(ProfileFields):
    elder_id: str
    version: int = Field(ge=1)
    onboarding_status: Literal["draft", "confirmed"]
    timezone: Literal["Asia/Hong_Kong"]
    source: Literal["community_mock", "user_confirmed", "demo_seed"]
    updated_at: AwareDatetime
class ProfilePatch(DTO):
    display_name: str | None = Field(default=None, min_length=1)
    birth_date: date | None = None
    sex: Literal["male", "female", "other", "unknown"] | None = None
    conditions: list[str] | None = None
    allergies: list[str] | None = None
    medical_notes: str | None = None
    @model_validator(mode="after")
    def valid_patch(self):
        if not self.model_fields_set:
            raise ValueError("empty patch")
        if any(getattr(self,k) is None for k in self.model_fields_set - {"birth_date"}):
            raise ValueError("only birth_date may be null")
        return self
class ProfileUpdate(DTO):
    expected_version: int = Field(ge=1)
    patch: ProfilePatch
class MatchWrite(DTO):
    sample_identity_key: str = Field(min_length=1)
    face_asset_id: str | None = None
class MatchResult(DTO):
    match_status: Literal["matched", "not_found"]
    draft_id: str
    profile_draft: ProfileFields
    medication_plan_drafts: list[MedicationPlanWrite]
    is_mock: Literal[True]
class ConfirmWrite(DTO):
    draft_id: str
    profile: ProfileFields
    medication_plans: list[MedicationPlanWrite]
    expected_version: int = Field(ge=1)
class BindingCode(DTO):
    code: str = Field(pattern=r"^\d{4}$")
    expires_at: AwareDatetime
    display_text: str
class BindingPreviewWrite(DTO):
    code: str = Field(pattern=r"^\d{4}$")
class BindingWrite(BindingPreviewWrite):
    relationship: str = Field(min_length=1, max_length=40)
class BindingPreview(DTO):
    elder_display_name: str
    masked_identity: str
    already_bound: bool
    expires_at: AwareDatetime
class BindingResult(DTO):
    binding_id: str
    elder_id: str
    relationship: str
    status: Literal["active"]
class ElderList(DTO):
    items: list[ElderSummary]
MediaPurpose = Literal["meal", "ingredient", "medicine", "face", "voice_message", "agent_audio", "document"]
class MediaAsset(DTO):
    asset_id: str
    purpose: MediaPurpose
    mime_type: str
    size_bytes: int = Field(ge=0)
    duration_ms: int | None
    content_url: str
    expires_at: AwareDatetime
class ProfileProposal(DTO):
    target_type: Literal["profile"]
    target_id: str
    operation: Literal["update"]
    base_version: int = Field(ge=1)
    patch: ProfilePatch
    reason: str = ""
class SettingsProposal(DTO):
    target_type: Literal["reminder_settings"]
    target_id: str
    operation: Literal["update"]
    base_version: int = Field(ge=1)
    patch: SettingsPatch
    reason: str = ""
class CreatePlanProposal(DTO):
    target_type: Literal["medication_plan"]
    target_id: None = None
    operation: Literal["create"]
    base_version: None = None
    patch: MedicationPlanWrite
    reason: str = ""
class UpdatePlanProposal(DTO):
    target_type: Literal["medication_plan"]
    target_id: str
    operation: Literal["update"]
    base_version: int = Field(ge=1)
    patch: PlanPatch
    reason: str = ""
class EmptyPatch(DTO):
    pass
class DeactivatePlanProposal(DTO):
    target_type: Literal["medication_plan"]
    target_id: str
    operation: Literal["deactivate"]
    base_version: int = Field(ge=1)
    patch: EmptyPatch
    reason: str = ""
PlanProposal = Annotated[CreatePlanProposal | UpdatePlanProposal | DeactivatePlanProposal, Field(discriminator="operation")]
ChangeProposalWrite = Annotated[ProfileProposal | SettingsProposal | PlanProposal, Field(discriminator="target_type")]
class ChangeProposal(DTO):
    proposal_id: str
    elder_id: str
    created_by: str
    target_type: Literal["profile", "reminder_settings", "medication_plan"]
    target_id: str | None
    operation: Literal["create", "update", "deactivate"]
    base_version: int | None
    patch: ProfilePatch | SettingsPatch | MedicationPlanWrite | PlanPatch | EmptyPatch
    before_snapshot: Profile | ReminderSettings | MedicationPlan | None
    status: ProposalStatus
    notification_id: str | None
    notified_at: AwareDatetime | None
    auto_apply_at: AwareDatetime | None
    applied_at: AwareDatetime | None
    applied_by: Literal["elder_accept", "timeout"] | None
    conflict_reason: str | None
    @field_serializer("patch")
    def _serialize_patch(self, value):
        # A patch is a *partial* replacement: serialize only the fields that were
        # actually submitted, otherwise a null-filled dump would re-validate as an
        # invalid ProfilePatch (only birth_date may be null).
        return value.model_dump(mode="json", exclude_unset=True) if isinstance(value, BaseModel) else value
class ChangeDecision(DTO):
    decision: Literal["accept", "reject"]
class EventResult(DTO):
    notification: Notification
    change_proposal: ChangeProposal | None = None
class RiskAssessment(DTO):
    status: Literal["not_configured"] = "not_configured"
    level: None = None
class Dashboard(DTO):
    elder: ElderSummary
    date: date
    completion: CalendarDay
    today_records: Records
    pending_tasks: list[DailyTask]
    attention_items: list[AttentionItem]
    recommendations: list[str]
    memory_summary: str
    provider_mode: Literal["mock"]
    risk_assessment: RiskAssessment
