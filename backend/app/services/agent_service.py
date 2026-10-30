"""C1 transaction-safe primitives; A0 owns HTTP orchestration and composition.

read_snapshot -> RELEASE read UoW -> provider.plan -> new write UoW ->
record_turn -> caller.commit. No provider is called from a Session method.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import date

from pydantic import TypeAdapter
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts.bundle import ServiceBundle
from app.contracts.context import Actor
from app.core.clock import Clock
from app.core.errors import AppError
from app.core.ids import new_id
from app.models.agent import AgentAction as ActionRow, AgentTurn as TurnRow
from app.providers.planning import Plan, Snapshot, request_digest
from app.services.memory_service import MemoryService
from app.schemas.agent import (
    Action, ActionDecision, ActionResult, AgentTurn, AgentTurnWrite, MemoryEntry,
    MemoryChange, Providers, Reply,
)
from app.schemas.common import SourceRef
from app.schemas.health import (
    Checkin, CheckinWrite, DietPayload, ExercisePayload, MedicationPayload, DailyReport, DailyTask,
)
from app.schemas.identity import Profile, ProfileUpdate, BindingCode


class AgentService:
    def __init__(self, clock: Clock, services: ServiceBundle, memory: MemoryService):
        if services.memory is not memory:
            raise ValueError("Use the same memory instance in AgentService and ServiceBundle")
        self.clock, self.services, self.memory = clock, services, memory

    def _access(self, tx, actor, elder_id):
        self.services.access.require_elder_access(tx, actor, elder_id, "self")

    def _references(self, tx, actor, request):
        self._access(tx, actor, request.elder_id)
        if request.conversation_id:
            foreign = tx.scalar(select(TurnRow.id).where(
                TurnRow.conversation_id == request.conversation_id,
                TurnRow.elder_id != request.elder_id))
            if foreign:
                raise AppError(403, "ELDER_ACCESS_DENIED", "Conversation is owned by another elder")
        for asset_id in [*request.image_asset_ids, *([request.audio_asset_id] if request.audio_asset_id else [])]:
            asset = self.services.media.get_asset(tx, actor, asset_id)
            image = asset_id in request.image_asset_ids
            accepted = {"image/jpeg", "image/png", "image/webp"} if image else {
                "audio/wav", "audio/x-wav", "audio/mpeg", "audio/mp3", "audio/webm", "audio/mp4"}
            if asset.mime_type not in accepted:
                raise AppError(415, "MEDIA_UNSUPPORTED", "Asset encoding category differs from its use")
        if request.context.pending_action_id:
            action = self._owned_action(tx, actor, request.context.pending_action_id)
            turn = tx.get(TurnRow, action.turn_id)
            if request.conversation_id and turn.conversation_id != request.conversation_id:
                raise AppError(404, "NOT_FOUND", "Action is not in this conversation")
        if request.context.notification_id:
            # No safe notification lookup port yet. Never confuse notification_id
            # with proposal_id or read B's table behind its service boundary.
            raise AppError(501, "MODULE_NOT_IMPLEMENTED", "A0 notification lookup port required")

    def replay(self, tx: Session, actor: Actor, request: AgentTurnWrite) -> AgentTurn | None:
        self._references(tx, actor, request)
        row = tx.scalar(select(TurnRow).where(TurnRow.elder_id == request.elder_id,
                                              TurnRow.client_turn_id == request.client_turn_id))
        if row is None:
            return None
        if row.actor_user_id != actor.user_id:
            raise AppError(403, "ELDER_ACCESS_DENIED", "Turn unavailable")
        if row.request_json != request.model_dump(mode="json"):
            raise AppError(409, "IDEMPOTENCY_CONFLICT", "client_turn_id reused with different input")
        return AgentTurn.model_validate(row.response_json)

    def read_snapshot(self, tx: Session, actor: Actor, request: AgentTurnWrite, *,
                      profile: Profile | None = None, tasks: Sequence[DailyTask] = (),
                      medication_slots: Mapping[str, str] | None = None) -> Snapshot:
        """Optional DTOs must come from A/B ports in this same short read UoW.

        On F1 baseline those read ports do not exist, so normal HTTP integration
        is deliberately deferred; module tests inject explicit DTO fixtures.
        """
        self._references(tx, actor, request)
        if profile is not None and profile.elder_id != request.elder_id:
            raise AppError(403, "ELDER_ACCESS_DENIED", "Profile snapshot mismatch")
        pending = select(ActionRow.id).join(TurnRow, TurnRow.id == ActionRow.turn_id).where(
            ActionRow.elder_id == request.elder_id, ActionRow.status == "pending",
            ActionRow.expires_at > self.clock.now())
        if request.conversation_id:
            pending = pending.where(TurnRow.conversation_id == request.conversation_id)
        return Snapshot(request.elder_id, self.clock.now(),
                        self.services.memory.context(tx, actor, request.elder_id),
                        profile, tuple(tasks), dict(medication_slots or {}),
                        tuple(tx.scalars(pending).all()))

    def record_turn(self, tx: Session, actor: Actor, request: AgentTurnWrite,
                    snapshot: Snapshot, plan: Plan) -> AgentTurn:
        """In a fresh write UoW; failure must roll back turn/actions/tool/memory."""
        old = self.replay(tx, actor, request)
        if old is not None:
            return old
        if snapshot.elder_id != request.elder_id or plan.request_hash != request_digest(request):
            raise AppError(409, "VERSION_CONFLICT", "Prepared plan does not match this request")
        memory = self.services.memory.context(tx, actor, request.elder_id)
        if memory.version != snapshot.memory.version:
            raise AppError(409, "VERSION_CONFLICT", "Memory changed while provider was running",
                           {"current_version": memory.version})
        row = TurnRow(elder_id=request.elder_id, actor_user_id=actor.user_id,
                      conversation_id=request.conversation_id or new_id("conversation"),
                      client_turn_id=request.client_turn_id, request_json=request.model_dump(mode="json"),
                      response_json={}, created_at=self.clock.now())
        tx.add(row)
        tx.flush()
        public_actions = []
        reply = plan.reply
        if plan.decision_action_id:
            if plan.decision_action_id not in snapshot.pending_action_ids:
                raise AppError(404, "NOT_FOUND", "Action was not part of this snapshot")
            result = self.decide(tx, actor, plan.decision_action_id, ActionDecision(decision="confirm"))
            old_action = tx.get(ActionRow, plan.decision_action_id)
            public_actions.append(TypeAdapter(Action).validate_python({**old_action.payload_json['public'], "status": result.status}))
            reply = "【模拟】" + result.reply.text
        for prepared in plan.actions:
            public = prepared.action
            payload = dict(prepared.payload)
            if payload.get("elder_id") != request.elder_id:
                raise AppError(403, "ELDER_ACCESS_DENIED", "Prepared action targets another elder")
            self._validate_payload(public.type, payload)
            action = ActionRow(id=public.action_id, turn_id=row.id, elder_id=request.elder_id,
                               type=public.type, status="pending", expires_at=public.expires_at,
                               payload_json={**payload, "public": TypeAdapter(Action).dump_python(public, mode="json", exclude_unset=True)})
            tx.add(action)
            tx.flush()
            if not public.requires_confirmation:
                if public.type not in {"create_binding_code", "query_report"}:
                    raise AppError(422, "VALIDATION_ERROR", "Writes require explicit confirmation")
                direct = self._execute(tx, actor, action, None)
                action.status = "confirmed"
                action.result_json = direct.model_dump(mode="json", exclude_unset=True)
                if isinstance(direct.result, BindingCode):
                    reply = f"【模拟】您的绑定码是{direct.result.code}，请仅分享给要绑定的家人。"
                elif isinstance(direct.result, DailyReport):
                    reply = "【模拟】" + direct.result.summary_text
            public_actions.append(public)
        if plan.preference:
            # Preference only comes from a validated provider plan for an explicit
            # statement; no memory inference from a single meal/photo.
            memory_entry = MemoryEntry(
                entry_id=new_id("memory"), kind="food_preference" if any(w in plan.preference for w in ["饮食", "吃", "菜", "辣", "豆", "米", "鱼"]) else "lifestyle",
                text=plan.preference, source_type="explicit_statement",
                source_ids=[SourceRef(type="agent_turn", id=row.id)],
                created_at=self.clock.now(), updated_at=self.clock.now(),
            )
            # Same-domain write helper, not an invented cross-domain port method.
            memory = self.memory.remember(tx, actor, request.elder_id, memory_entry)
        memory = self.services.memory.context(tx, actor, request.elder_id)
        response = AgentTurn(
            turn_id=row.id, conversation_id=row.conversation_id, transcript=request.text or "",
            reply=Reply(text=reply), scene=plan.scene, avatar_state="idle", actions=public_actions,
            memory=MemoryChange(version=memory.version, changed=memory.version != snapshot.memory.version),
            providers=Providers(chat="mock", asr="not_used", tts="not_used"),
            degraded=["tts_unavailable"],
        )
        row.response_json = response.model_dump(mode="json", exclude_unset=True)
        tx.flush()
        return response

    def _owned_action(self, tx, actor, action_id):
        row = tx.get(ActionRow, action_id)
        if row is None:
            raise AppError(404, "NOT_FOUND", "Action unavailable")
        try:
            self._access(tx, actor, row.elder_id)
        except AppError as exc:
            if exc.status == 403:
                raise AppError(404, "NOT_FOUND", "Action unavailable") from exc
            raise
        turn = tx.get(TurnRow, row.turn_id)
        if turn.actor_user_id != actor.user_id:
            raise AppError(404, "NOT_FOUND", "Action unavailable")
        return row

    def decide(self, tx: Session, actor: Actor, action_id: str, decision: ActionDecision) -> ActionResult:
        row = self._owned_action(tx, actor, action_id)
        decision_data = decision.model_dump(mode="json", exclude_unset=True)
        decision_data.setdefault("amendments", None)
        digest = hashlib.sha256(json.dumps(decision_data,
                                          sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        if row.status == "cancelled":
            if decision.decision == "cancel":
                return ActionResult.model_validate(row.result_json)
            raise AppError(409, "ACTION_CANCELLED", "Action was cancelled")
        if row.status == "confirmed":
            original = row.payload_json.get("decision_hash")
            if decision.decision != "confirm" or (original and original != digest):
                raise AppError(409, "IDEMPOTENCY_CONFLICT", "Confirmed action cannot be amended or cancelled")
            return ActionResult.model_validate(row.result_json)
        if row.expires_at <= self.clock.now() or row.status == "expired":
            raise AppError(409, "ACTION_EXPIRED", "Action expired; please start a new request")
        if decision.decision == "cancel":
            if decision.amendments is not None:
                raise AppError(422, "VALIDATION_ERROR", "Cancellation cannot contain amendments")
            result = ActionResult(action_id=row.id, status="cancelled", result=None,
                                  reply=Reply(text="已取消，没有执行该动作。"))
        else:
            result = self._execute(tx, actor, row, decision)
        # Last, after successful tool validation/execution. The caller owns commit.
        row.status = result.status
        row.result_json = result.model_dump(mode="json", exclude_unset=True)
        row.payload_json = {**row.payload_json, "decision_hash": digest}
        tx.flush()
        return result

    @staticmethod
    def _validate_payload(kind, payload):
        if kind in {"record_diet", "record_exercise", "record_medication"}:
            body = TypeAdapter(CheckinWrite).validate_python(payload['checkin'])
            if kind != 'record_' + body.type:
                raise AppError(422, "VALIDATION_ERROR", "Checkin type differs from action")
        elif kind == "update_profile":
            ProfileUpdate.model_validate(payload['update'])
        elif kind not in {"create_binding_code", "query_report"}:
            raise AppError(501, "MODULE_NOT_IMPLEMENTED", "Action requires an A0 tool port")

    def _execute(self, tx, actor, row, decision):
        payload = row.payload_json
        amendments = decision.amendments if decision else None
        self._validate_payload(row.type, payload)
        if row.type in {"record_diet", "record_exercise", "record_medication"}:
            body = TypeAdapter(CheckinWrite).validate_python(payload['checkin'])
            if amendments is not None:
                expected = {"diet": DietPayload, "exercise": ExercisePayload, "medication": MedicationPayload}[body.type]
                if type(amendments) is not expected:
                    raise AppError(422, "VALIDATION_ERROR", "Amendment does not match action type")
                if body.type == "medication" and (amendments.plan_id, amendments.slot_id) != (body.payload.plan_id, body.payload.slot_id):
                    raise AppError(403, "ELDER_ACCESS_DENIED", "Cannot change medication target")
                body = body.model_copy(update={"payload": amendments})
            if body.type == "diet":
                for asset_id in body.payload.image_asset_ids:
                    self.services.media.get_asset(tx, actor, asset_id)
            output = self.services.checkins.create_or_update(tx, actor, row.elder_id, body)
        elif row.type == "update_profile":
            body = ProfileUpdate.model_validate(payload['update'])
            if payload.get('target_id') != row.elder_id:
                raise AppError(403, "ELDER_ACCESS_DENIED", "Invalid profile target")
            if amendments is not None:
                if type(amendments) is not ProfileUpdate or amendments.expected_version != body.expected_version:
                    raise AppError(422, "VALIDATION_ERROR", "Profile amendment has a different version/type")
                body = amendments
            output = self.services.profile.update(tx, actor, row.elder_id, body.expected_version, body.patch)
        elif row.type == "create_binding_code":
            if amendments is not None:
                raise AppError(422, "VALIDATION_ERROR", "Binding code has no amendments")
            output = self.services.binding.issue_code(tx, actor, row.elder_id)
        elif row.type == "query_report":
            if amendments is not None:
                raise AppError(422, "VALIDATION_ERROR", "Report date is fixed in the action")
            output = self.services.reports.daily(tx, actor, row.elder_id, date.fromisoformat(payload['date']))
        else:
            raise AppError(501, "MODULE_NOT_IMPLEMENTED", "Tool is not implemented")
        if isinstance(output, (Checkin, Profile, DailyReport)) and output.elder_id != row.elder_id:
            raise AppError(502, "PROVIDER_ERROR", "Business port returned another elder's resource")
        return ActionResult(action_id=row.id, status="confirmed", result=output,
                            reply=Reply(text="已确认，业务服务已成功处理。"))
