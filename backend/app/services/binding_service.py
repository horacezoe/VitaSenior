"""A owns family binding.

Codes are four digits *with significant leading zeros*, globally unique among the
active ones, valid five minutes, revoked when re-issued, and consumed exactly once
inside the caller's write transaction. Expired/consumed/old codes never bind.
"""
import secrets
from datetime import timedelta
from sqlalchemy import select, update
from sqlalchemy.orm import Session
from app.contracts.context import Actor
from app.core.auth import require_elder_access
from app.core.clock import Clock, local_date
from app.core.errors import AppError
from app.models.identity import BindingCode as BindingCodeRow, ElderProfile, FamilyBinding, User
from app.schemas.identity import BindingCode, BindingPreview, BindingResult, ElderList
from app.services.identity_views import elder_summary, masked_phone

CODE_TTL_SECONDS = 300
PREVIEW_LIMIT = 12          # per child per minute (process-local, demo scale)
PREVIEW_WINDOW_SECONDS = 60

def _active_code(tx: Session, code: str) -> BindingCodeRow | None:
    return tx.scalar(select(BindingCodeRow).where(BindingCodeRow.code == code, BindingCodeRow.active == True))

def _raise_code_error(tx: Session, code: str, now) -> None:
    """Classify only after failing to find an active code: no silent success."""
    row = tx.scalar(select(BindingCodeRow).where(BindingCodeRow.code == code).order_by(BindingCodeRow.expires_at.desc()))
    if row is None:
        raise AppError(409, "BIND_CODE_INVALID", "绑定码不存在，请核对后重试")
    if row.consumed_at is not None:
        raise AppError(409, "BIND_CODE_CONSUMED", "绑定码已被使用")
    raise AppError(409, "BIND_CODE_INVALID", "绑定码已失效，请重新生成")

class BindingService:
    def __init__(self, clock: Clock, limiter=None):
        self.clock, self.limiter = clock, limiter

    def issue_code(self, tx: Session, actor: Actor, elder_id: str) -> BindingCode:
        require_elder_access(tx, actor, elder_id, "self")
        now = self.clock.now()
        # Re-issuing revokes the elder's previous active code in the same tx; the
        # partial unique indexes then allow exactly one active code per elder.
        tx.execute(update(BindingCodeRow).where(BindingCodeRow.elder_id == elder_id, BindingCodeRow.active == True).values(active=False, revoked_at=now))
        tx.flush()
        code = None
        for _ in range(200):
            candidate = f"{secrets.randbelow(10000):04d}"
            if _active_code(tx, candidate) is None:
                code = candidate
                break
        if code is None:
            raise AppError(429, "RATE_LIMITED", "暂无可用绑定码，请稍后重试", retryable=True)
        row = BindingCodeRow(code=code, elder_id=elder_id, expires_at=now + timedelta(seconds=CODE_TTL_SECONDS), active=True)
        tx.add(row)
        tx.flush()
        return BindingCode(code=code, expires_at=row.expires_at, display_text=f"绑定码 {code}，5 分钟内有效")

    def preview(self, tx: Session, actor: Actor, code: str) -> BindingPreview:
        if self.limiter is not None:
            self.limiter.check(f"bind-preview:{actor.user_id}", limit=PREVIEW_LIMIT, window_seconds=PREVIEW_WINDOW_SECONDS)
        now = self.clock.now()
        row = _active_code(tx, code)
        if row is None:
            _raise_code_error(tx, code, now)
        if row.expires_at <= now:
            raise AppError(409, "BIND_CODE_EXPIRED", "绑定码已过期，请让家人重新生成")
        elder = tx.get(ElderProfile, row.elder_id)
        owner = tx.get(User, elder.owner_user_id)
        bound = tx.scalar(select(FamilyBinding.id).where(
            FamilyBinding.elder_id == elder.id, FamilyBinding.child_user_id == actor.user_id, FamilyBinding.status == "active"))
        return BindingPreview(
            elder_display_name=(elder.profile_json or {}).get("display_name") or "老人",
            masked_identity=masked_phone(owner.phone),
            already_bound=bound is not None,
            expires_at=row.expires_at,
        )

    def consume(self, tx: Session, actor: Actor, code: str, relationship: str) -> BindingResult:
        now = self.clock.now()
        row = _active_code(tx, code)
        if row is None:
            _raise_code_error(tx, code, now)
        if row.expires_at <= now:
            raise AppError(409, "BIND_CODE_EXPIRED", "绑定码已过期，请让家人重新生成")
        existing = tx.scalar(select(FamilyBinding).where(
            FamilyBinding.elder_id == row.elder_id, FamilyBinding.child_user_id == actor.user_id, FamilyBinding.status == "active"))
        if existing is not None:
            # Same key replays via Idempotency; any other request is treated as consumed.
            raise AppError(409, "BIND_CODE_CONSUMED", "你已经与这位家人绑定")
        row.active = False
        row.consumed_at = now
        binding = FamilyBinding(elder_id=row.elder_id, child_user_id=actor.user_id, relationship=relationship)
        tx.add(binding)
        tx.flush()
        return BindingResult(binding_id=binding.id, elder_id=row.elder_id, relationship=relationship, status="active")

    def list_elders(self, tx: Session, actor: Actor) -> ElderList:
        today = local_date(self.clock.now())
        rows = tx.execute(select(ElderProfile, FamilyBinding).join(
            FamilyBinding, FamilyBinding.elder_id == ElderProfile.id).where(
            FamilyBinding.child_user_id == actor.user_id, FamilyBinding.status == "active")).all()
        return ElderList(items=[elder_summary(elder, binding, today) for elder, binding in rows])
