"""A owns the child-proposal state machine (CHANGE01-04).

Invariants:
  * a child submit only writes the proposal + a notification; the target is untouched;
  * auto_apply_at stays null until the elder's device reports a *complete* playback,
    and only the server clock starts the 60-second window;
  * a repeated playback receipt never re-arms the deadline;
  * deciding/expiring races end in exactly one terminal state, and applying re-checks
    both the target version and that the child's binding is still active;
  * cross-domain writes (B medication, C memory invalidation) share the caller's tx,
    so an unimplemented port rolls the whole application back instead of marking it
    applied.
"""
from datetime import datetime, timedelta
import base64
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.contracts.context import Actor, SYSTEM_ACTOR
from app.core.auth import require_elder_access
from app.core.clock import Clock
from app.core.config import Settings
from app.core.errors import AppError
from app.models.identity import ChangeProposal as ChangeProposalRow, ElderProfile, FamilyBinding
from app.schemas.common import Page, SourceRef
from app.schemas.enums import Role
from app.schemas.health import MedicationPlan, MedicationPlanWrite, NotificationEnqueue, PlanPatch, ReminderSettings, SettingsPatch
from app.schemas.identity import ChangeDecision, ChangeProposal, ChangeProposalWrite, EmptyPatch, Profile, ProfilePatch
from app.services.identity_views import profile_from_row

WINDOW_SECONDS = 60
OPEN_STATES = ("pending_notice", "awaiting_decision")
TITLES = {
    ("profile", "update"): "孩子帮您更新了档案",
    ("reminder_settings", "update"): "孩子帮您调整了提醒时间",
    ("medication_plan", "create"): "孩子帮您新增了用药计划",
    ("medication_plan", "update"): "孩子帮您修改了用药计划",
    ("medication_plan", "deactivate"): "孩子帮您停用了用药计划",
}

class ChangeService:
    def __init__(self, clock: Clock, settings: Settings):
        self.clock, self.settings = clock, settings
        self.medication = None      # MedicationPort (B)
        self.notifications = None   # NotificationPort (B)
        self.memory = None          # MemoryPort (C)
        self.media = None           # MediaService (A, same domain) for announcement audio

    def bind(self, *, medication=None, notifications=None, memory=None, media=None) -> "ChangeService":
        """Late binding breaks the A<->B notification/change reference cycle.
        Only composition calls this; services never look each other up."""
        self.medication = medication or self.medication
        self.notifications = notifications or self.notifications
        self.memory = memory or self.memory
        self.media = media or self.media
        return self

    # ---- public port surface -------------------------------------------------

    def create(self, tx: Session, actor: Actor, elder_id: str, body: ChangeProposalWrite, now: datetime, *,
               notice=None) -> ChangeProposal:
        require_elder_access(tx, actor, elder_id, "child")
        self._validate_target(tx, elder_id, body)
        snapshot = self._snapshot(tx, actor, elder_id, body)
        row = ChangeProposalRow(
            elder_id=elder_id, created_by=actor.user_id, target_type=body.target_type,
            target_id=body.target_id, operation=body.operation, base_version=body.base_version,
            patch=body.patch.model_dump(mode="json", exclude_unset=True), before_snapshot=snapshot,
            status="pending_notice", reason=body.reason, created_at=now,
        )
        tx.add(row)
        tx.flush()  # notification FK needs the proposal id
        # The spoken notice was prepared OUTSIDE this write tx (see
        # identity_flows.create_change); here it is only registered, so the elder can
        # complete a real spoken playback. A tone would never be accepted as evidence.
        audio_asset_id = None
        if notice is not None:
            audio_asset_id = self.media.register_announcement(
                tx, elder_id, content=notice.audio.content, mime_type=notice.audio.mime_type,
                duration_ms=notice.audio.duration_ms).asset_id
        notification = self.notifications.enqueue(tx, actor, f"proposal:{row.id}", NotificationEnqueue(
            elder_id=elder_id, kind="profile_change", category="general",
            title=TITLES[(body.target_type, body.operation)],
            text=notice.text if notice is not None else TITLES[(body.target_type, body.operation)],
            audio_asset_id=audio_asset_id, repeat_count=1, due_at=now, proposal_id=row.id,
        ))
        # The port returns the Notification DTO (notification_id), not an ORM row.
        row.notification_id = notification.notification_id
        tx.flush()
        return self.view(row)

    def query(self, tx: Session, actor: Actor, elder_id: str, status, limit: int, cursor: str | None) -> Page[ChangeProposal]:
        require_elder_access(tx, actor, elder_id, "read")
        stmt = select(ChangeProposalRow).where(ChangeProposalRow.elder_id == elder_id)
        if status is not None:
            stmt = stmt.where(ChangeProposalRow.status == str(status))
        if cursor:
            created_at, proposal_id = self._decode_cursor(cursor)
            stmt = stmt.where((ChangeProposalRow.created_at < created_at) | (
                (ChangeProposalRow.created_at == created_at) & (ChangeProposalRow.id < proposal_id)))
        rows = tx.scalars(stmt.order_by(ChangeProposalRow.created_at.desc(), ChangeProposalRow.id.desc()).limit(limit + 1)).all()
        items = rows[:limit]
        next_cursor = self._encode_cursor(items[-1]) if len(rows) > limit else None
        return Page(items=[self.view(row) for row in items], next_cursor=next_cursor)

    def read(self, tx: Session, actor: Actor, proposal_id: str) -> ChangeProposal:
        row = self._row(tx, proposal_id)
        require_elder_access(tx, actor, row.elder_id, "read")
        return self.view(row)

    def decide(self, tx: Session, actor: Actor, proposal_id: str, decision: ChangeDecision, now: datetime) -> ChangeProposal:
        row = self._row(tx, proposal_id)
        require_elder_access(tx, actor, row.elder_id, "self")
        self._settle_if_due(tx, row, now)   # server time only: an expired window wins
        if row.status == "applied":
            raise AppError(409, "CHANGE_ALREADY_APPLIED", "提案已生效，请另提纠正")
        if row.status not in OPEN_STATES:
            raise AppError(409, "CHANGE_ALREADY_APPLIED", "提案已结束，不能再次处理")
        if decision.decision == "reject":
            row.status = "rejected"
            tx.flush()
            self._close_notification(tx, row)
            tx.flush()
            return self.view(row)
        return self._apply(tx, actor, row, now, applied_by="elder_accept")

    def mark_played(self, tx: Session, actor: Actor, proposal_id: str, now: datetime) -> ChangeProposal:
        row = self._row(tx, proposal_id)
        # Only the elder whose proposal it is may report a playback completion.
        require_elder_access(tx, actor, row.elder_id, "self")
        if row.status != "pending_notice":
            # Idempotent receipt: never re-arm an already started window.
            return self.view(row)
        row.status = "awaiting_decision"
        row.notified_at = now
        row.auto_apply_at = now + timedelta(seconds=WINDOW_SECONDS)
        tx.flush()
        return self.view(row)

    def apply_due(self, tx: Session, now: datetime) -> list[ChangeProposal]:
        """Server-side settlement entry. It runs as the reserved SYSTEM principal,
        never as a fabricated user: the audit column records applied_by="timeout"."""
        rows = tx.scalars(select(ChangeProposalRow).where(
            ChangeProposalRow.status == "awaiting_decision",
            ChangeProposalRow.auto_apply_at.is_not(None),
            ChangeProposalRow.auto_apply_at <= now,
        ).order_by(ChangeProposalRow.auto_apply_at)).all()
        settled = []
        for row in rows:
            settled.append(self._apply(tx, SYSTEM_ACTOR, row, now, applied_by="timeout"))
        return settled

    # ---- internals -----------------------------------------------------------

    def view(self, row: ChangeProposalRow) -> ChangeProposal:
        return ChangeProposal(
            proposal_id=row.id, elder_id=row.elder_id, created_by=row.created_by,
            target_type=row.target_type, target_id=row.target_id, operation=row.operation,
            base_version=row.base_version, patch=self._patch_model(row),
            before_snapshot=self._before_model(row), status=row.status,
            notification_id=row.notification_id, notified_at=row.notified_at,
            auto_apply_at=row.auto_apply_at, applied_at=row.applied_at,
            applied_by=row.applied_by, conflict_reason=row.conflict_reason,
        )

    def _row(self, tx: Session, proposal_id: str) -> ChangeProposalRow:
        row = tx.get(ChangeProposalRow, proposal_id)
        if row is None:
            raise AppError(404, "NOT_FOUND", "Resource unavailable")
        return row

    def _validate_target(self, tx: Session, elder_id: str, body: ChangeProposalWrite) -> None:
        if body.target_type in ("profile", "reminder_settings"):
            if body.target_id != elder_id or body.base_version is None:
                raise AppError(422, "VALIDATION_ERROR", "Proposal must target this elder with a base_version")
        elif body.operation != "create" and (not body.target_id or body.base_version is None):
            raise AppError(422, "VALIDATION_ERROR", "target_id and base_version are required")

    def _snapshot(self, tx: Session, actor: Actor, elder_id: str, body: ChangeProposalWrite):
        if body.operation == "create":
            return None
        elder = tx.get(ElderProfile, elder_id)
        if body.target_type == "profile":
            return profile_from_row(elder).model_dump(mode="json")
        if body.target_type == "reminder_settings":
            return self._settings_view(elder).model_dump(mode="json")
        return self.medication.get_plan(tx, actor, body.target_id).model_dump(mode="json")

    def _settings_view(self, elder: ElderProfile) -> ReminderSettings:
        raw = dict(elder.reminder_settings_json or {})
        return ReminderSettings(version=elder.version, meals=raw.get("meals", []),
                                exercise=raw["exercise"], daily_summary=raw["daily_summary"],
                                voice_enabled=raw.get("voice_enabled", True))

    def _patch_model(self, row: ChangeProposalRow):
        payload = dict(row.patch or {})
        if row.target_type == "profile":
            return ProfilePatch.model_validate(payload)
        if row.target_type == "reminder_settings":
            return SettingsPatch.model_validate(payload)
        if row.operation == "create":
            return MedicationPlanWrite.model_validate(payload)
        if row.operation == "update":
            return PlanPatch.model_validate(payload)
        return EmptyPatch()

    def _before_model(self, row: ChangeProposalRow):
        if row.before_snapshot is None:
            return None
        if row.target_type == "profile":
            return Profile.model_validate(row.before_snapshot)
        if row.target_type == "reminder_settings":
            return ReminderSettings.model_validate(row.before_snapshot)
        return MedicationPlan.model_validate(row.before_snapshot)

    def _settle_if_due(self, tx: Session, row: ChangeProposalRow, now: datetime) -> None:
        if row.status == "awaiting_decision" and row.auto_apply_at is not None and row.auto_apply_at <= now:
            self._apply(tx, SYSTEM_ACTOR, row, now, applied_by="timeout")

    def _apply(self, tx: Session, actor: Actor, row: ChangeProposalRow, now: datetime, *, applied_by: str) -> ChangeProposal:
        elder = tx.get(ElderProfile, row.elder_id)
        bound = tx.scalar(select(FamilyBinding.id).where(
            FamilyBinding.elder_id == row.elder_id,
            FamilyBinding.child_user_id == row.created_by,
            FamilyBinding.status == "active"))
        if bound is None:
            # A revoked binding must not silently write, even on timeout.
            return self._conflict(tx, row, "binding_revoked")
        if row.target_type == "profile":
            if row.base_version != elder.version:
                return self._conflict(tx, row, "version_changed")
            raw = dict(elder.profile_json or {})
            raw.update(dict(row.patch or {}))
            elder.profile_json = raw
            self._bump(elder, now)
            tx.flush()
            self.memory.on_source_changed(tx, actor, row.elder_id,
                                          SourceRef(type="profile", id=row.elder_id, version=elder.version))
        elif row.target_type == "reminder_settings":
            if row.base_version != elder.version:
                return self._conflict(tx, row, "version_changed")
            # B's frozen port owns the settings write: it bumps the profile version
            # and retires/re-times already generated future goals in the same tx, so
            # A must not touch reminder_settings_json or the version itself.
            self.medication.update_settings(tx, actor, row.elder_id, row.base_version, self._patch_model(row))
            tx.flush()
        else:
            # Frozen contract: create has no target to read and no expected version;
            # deactivate carries a null patch; only update reads+compares the plan.
            if row.operation == "create":
                self.medication.apply_change(tx, actor, row.elder_id, "create", None,
                                             self._patch_model(row), None)
            else:
                plan = self.medication.get_plan(tx, actor, row.target_id)
                if row.base_version != plan.version:
                    return self._conflict(tx, row, "version_changed")
                patch = None if row.operation == "deactivate" else self._patch_model(row)
                self.medication.apply_change(tx, actor, row.elder_id, row.operation, row.target_id,
                                             patch, row.base_version)
        row.status = "applied"
        row.applied_at = now
        row.applied_by = applied_by
        row.conflict_reason = None
        tx.flush()
        self._close_notification(tx, row)
        tx.flush()
        return self.view(row)

    def _conflict(self, tx: Session, row: ChangeProposalRow, reason: str) -> ChangeProposal:
        row.status = "conflicted"
        row.conflict_reason = reason
        tx.flush()
        self._close_notification(tx, row)
        tx.flush()
        return self.view(row)

    def _bump(self, elder: ElderProfile, now: datetime) -> None:
        elder.version += 1
        elder.updated_at = now

    def _close_notification(self, tx: Session, row: ChangeProposalRow) -> None:
        if row.notification_id:
            self.notifications.mark_proposal_handled(tx, row.notification_id)

    def _encode_cursor(self, row: ChangeProposalRow) -> str:
        raw = f"{row.created_at.isoformat()}|{row.id}".encode()
        # URL-safe: a raw "+00:00" offset would decode as a space in a query string.
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    def _decode_cursor(self, cursor: str) -> tuple[datetime, str]:
        try:
            raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode()
            created_at, _, proposal_id = raw.partition("|")
            return datetime.fromisoformat(created_at), proposal_id
        except (ValueError, UnicodeDecodeError) as exc:
            raise AppError(422, "VALIDATION_ERROR", "Invalid cursor") from exc
