from datetime import datetime
from sqlalchemy import String, JSON, ForeignKey, UniqueConstraint, CheckConstraint, Index, text
from sqlalchemy.orm import Mapped, mapped_column
from app.core.db import Base, UTCDateTime
from app.core.ids import new_id

class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("user"))
    phone: Mapped[str] = mapped_column(String, unique=True)
    role: Mapped[str] = mapped_column(String)
    demo_id: Mapped[str] = mapped_column(String, index=True)
    __table_args__ = (CheckConstraint("role IN ('elder','child')"),)
class AuthChallenge(Base):
    __tablename__ = "auth_challenges"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("challenge"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    purpose: Mapped[str] = mapped_column(default="login")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    consumed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    attempts: Mapped[int] = mapped_column(default=0)
class AuthSession(Base):
    __tablename__ = "auth_sessions"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("session"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    token_hash: Mapped[str] = mapped_column(String, unique=True)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
class ElderProfile(Base):
    __tablename__ = "elder_profiles"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("elder"))
    owner_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), unique=True)
    profile_json: Mapped[dict] = mapped_column(JSON)
    reminder_settings_json: Mapped[dict] = mapped_column(JSON)
    onboarding_draft: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    onboarding_status: Mapped[str] = mapped_column(default="draft")
    version: Mapped[int] = mapped_column(default=1)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime)
    __table_args__ = (CheckConstraint("version >= 1"), CheckConstraint("onboarding_status IN ('draft','confirmed')"))
class FamilyBinding(Base):
    __tablename__ = "family_bindings"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("binding"))
    elder_id: Mapped[str] = mapped_column(ForeignKey("elder_profiles.id"))
    child_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    relationship: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(default="active")
    __table_args__ = (Index("uq_active_binding", "elder_id", "child_user_id", unique=True, sqlite_where=text("status='active'")), CheckConstraint("status IN ('active','revoked')"))
class BindingCode(Base):
    __tablename__ = "binding_codes"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("code"))
    code: Mapped[str] = mapped_column(String(4))
    elder_id: Mapped[str] = mapped_column(ForeignKey("elder_profiles.id"))
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    consumed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    active: Mapped[bool] = mapped_column(default=True)
    __table_args__ = (Index("uq_active_code", "code", unique=True, sqlite_where=text("active=1")), Index("uq_elder_active_code", "elder_id", unique=True, sqlite_where=text("active=1")), CheckConstraint("length(code)=4 AND code NOT GLOB '*[^0-9]*'"), CheckConstraint("active=0 OR (consumed_at IS NULL AND revoked_at IS NULL)"))
class MediaAsset(Base):
    __tablename__ = "media_assets"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("asset"))
    owner_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    elder_id: Mapped[str | None] = mapped_column(ForeignKey("elder_profiles.id"))
    purpose: Mapped[str] = mapped_column(String)
    mime_type: Mapped[str] = mapped_column(String)
    size_bytes: Mapped[int] = mapped_column()
    duration_ms: Mapped[int | None] = mapped_column()
    relative_path: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    __table_args__ = (CheckConstraint("size_bytes >= 0"),)
class ChangeProposal(Base):
    __tablename__ = "change_proposals"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("proposal"))
    elder_id: Mapped[str] = mapped_column(ForeignKey("elder_profiles.id"))
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    target_type: Mapped[str] = mapped_column(String)
    target_id: Mapped[str | None] = mapped_column(String)
    operation: Mapped[str] = mapped_column(String)
    base_version: Mapped[int | None] = mapped_column()
    patch: Mapped[dict] = mapped_column(JSON)
    before_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(default="pending_notice")
    notification_id: Mapped[str | None] = mapped_column(ForeignKey("notifications.id"))
    notified_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    auto_apply_at: Mapped[datetime | None] = mapped_column(UTCDateTime, index=True)
    applied_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    applied_by: Mapped[str | None] = mapped_column(String)
    conflict_reason: Mapped[str | None] = mapped_column(String)
    reason: Mapped[str] = mapped_column(default="")
    # A2 gap fix: proposals need a stable creation order for cursor pagination.
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    __table_args__ = (CheckConstraint("status IN ('pending_notice','awaiting_decision','applied','rejected','cancelled','conflicted')"), CheckConstraint("target_type IN ('profile','reminder_settings','medication_plan')"), CheckConstraint("operation IN ('create','update','deactivate')"), CheckConstraint("status != 'pending_notice' OR auto_apply_at IS NULL"))
class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("idem"))
    actor_id: Mapped[str] = mapped_column(String)
    method: Mapped[str] = mapped_column(String)
    path: Mapped[str] = mapped_column(String)
    key: Mapped[str] = mapped_column(String)
    request_hash: Mapped[str] = mapped_column(String)
    response_json: Mapped[dict] = mapped_column(JSON)
    status_code: Mapped[int] = mapped_column()
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    __table_args__ = (UniqueConstraint("actor_id", "method", "path", "key"),)
