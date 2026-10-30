"""Shared read views for the identity domain (profile row -> DTO)."""
from datetime import date
from app.core.errors import AppError
from app.models.identity import ElderProfile, FamilyBinding
from app.schemas.identity import ElderSummary, Profile

TIMEZONE = "Asia/Hong_Kong"
SOURCES = {"community_mock", "user_confirmed", "demo_seed"}

def default_reminder_settings() -> dict:
    return {
        "meals": [{"slot": slot, "local_time": local_time, "enabled": True}
                  for slot, local_time in [("breakfast", "08:30"), ("lunch", "12:30"), ("dinner", "18:30")]],
        "exercise": {"enabled": True, "local_time": "17:00"},
        "daily_summary": {"enabled": True, "local_time": "20:30"},
        "voice_enabled": True,
    }

def profile_from_row(elder: ElderProfile) -> Profile:
    raw = dict(elder.profile_json or {})
    source = raw.get("source", "user_confirmed")
    birth = raw.get("birth_date")
    return Profile(
        elder_id=elder.id,
        version=elder.version,
        onboarding_status=elder.onboarding_status,
        display_name=raw.get("display_name") or "老人",
        birth_date=date.fromisoformat(birth) if birth else None,
        sex=raw.get("sex", "unknown"),
        conditions=list(raw.get("conditions") or []),
        allergies=list(raw.get("allergies") or []),
        medical_notes=raw.get("medical_notes", ""),
        timezone=TIMEZONE,
        source=source if source in SOURCES else "user_confirmed",
        updated_at=elder.updated_at,
    )

def age_of(birth: date | None, today: date) -> int | None:
    if birth is None:
        return None
    return today.year - birth.year - ((today.month, today.day) < (birth.month, birth.day))

def elder_summary(elder: ElderProfile, binding: FamilyBinding, today: date) -> ElderSummary:
    raw = dict(elder.profile_json or {})
    birth = raw.get("birth_date")
    birthday = date.fromisoformat(birth) if birth else None
    return ElderSummary(
        elder_id=elder.id,
        display_name=raw.get("display_name") or "老人",
        age=age_of(birthday, today),
        conditions=list(raw.get("conditions") or []),
        binding_id=binding.id,
        relationship=binding.relationship,
    )

def masked_phone(phone: str) -> str:
    return phone[:3] + "****" + phone[-4:] if len(phone) == 11 else "***"

def version_conflict(current: int) -> AppError:
    return AppError(409, "VERSION_CONFLICT", "内容已更新，请刷新后再提交", {"current_version": current})
