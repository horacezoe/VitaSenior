"""Transaction-safe C primitives; C flows own orchestration, A owns composition.

read_snapshot -> RELEASE read UoW -> provider.plan -> new write UoW ->
record_turn -> caller.commit. No provider is called from a Session method.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import date

from pydantic import TypeAdapter, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts.bundle import ServiceBundle
from app.contracts.context import Actor
from app.core.clock import Clock, local_date
from app.core.errors import AppError
from app.core.ids import new_id
from app.models.agent import AgentAction as ActionRow, AgentTurn as TurnRow
from app.providers.planning import Plan, Snapshot, request_digest
from app.providers.mock_audio import Speech
from app.services.memory_service import MemoryService
from app.schemas.agent import (
    Action, ActionDecision, ActionResult, AgentTurn, AgentTurnWrite, MemoryEntry,
    MemoryChange, Providers, Reply,
)
from app.schemas.common import SourceRef
from app.schemas.health import (
    Checkin, CheckinWrite, DietPayload, ExercisePayload, MedicationPayload, DailyReport, DailyTask,
    MedicationPlanWrite, PlanUpdate, NotificationEvent,
)
from app.schemas.identity import Profile, ProfileUpdate, BindingCode, ChangeDecision


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
        # Notification resource checks are performed by the application using
        # A0 check_resource in BOTH the short read and fresh write UoWs. C never
        # reads B's ORM tables or equates notification_id with proposal_id.

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

        Application flows use the A0 read ports. Tests may supply explicit DTO
        fixtures; normal execution must never pass guessed or cached evidence.
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
                    snapshot: Snapshot, plan: Plan, *, speech: Speech | None = None) -> AgentTurn:
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
        for prepared in plan.actions:
            if prepared.action.type != 'record_medication':
                continue
            expected = prepared.payload.get('task_plan_version')
            current = self.services.medication.get_plan(tx, actor, prepared.payload['checkin']['payload']['plan_id'])
            if current.elder_id != request.elder_id or (expected is not None and current.version != expected):
                raise AppError(409, 'VERSION_CONFLICT', 'Medication plan changed while provider was running')
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
                if public.type not in {"create_binding_code", "query_report", "decide_change", "respond_notification"}:
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
        audio_asset_id = None
        if speech is not None and speech.text == reply:
            asset = self.services.media.register_generated(
                tx, actor, request.elder_id, content=speech.content, mime_type=speech.mime_type,
                purpose="agent_audio", duration_ms=speech.duration_ms)
            audio_asset_id = asset.asset_id
        response = AgentTurn(
            turn_id=row.id, conversation_id=row.conversation_id, transcript=plan.transcript or request.text or "",
            reply=Reply(text=reply, audio_asset_id=audio_asset_id), scene=plan.scene,
            avatar_state="speaking" if audio_asset_id else "idle", actions=public_actions,
            memory=MemoryChange(version=memory.version, changed=memory.version != snapshot.memory.version),
            providers=Providers(chat="mock", asr=plan.asr_provider, tts="mock" if audio_asset_id else "not_used"),
            degraded=[] if audio_asset_id else ["tts_unavailable"],
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
        try:
            if kind in {"record_diet", "record_exercise", "record_medication"}:
                body = TypeAdapter(CheckinWrite).validate_python(payload['checkin'])
                if kind != 'record_' + body.type:
                    raise AppError(422, "VALIDATION_ERROR", "Checkin type differs from action")
            elif kind == "update_profile":
                ProfileUpdate.model_validate(payload['update'])
            elif kind == "create_medication_plan":
                MedicationPlanWrite.model_validate(payload['plan'])
            elif kind == "update_medication_plan":
                PlanUpdate.model_validate(payload['update'])
            elif kind == "decide_change":
                ChangeDecision(decision=payload['decision'])
                if not payload.get('proposal_id'):
                    raise ValueError('proposal_id required')
            elif kind == "respond_notification":
                event = NotificationEvent.model_validate(payload['event'])
                if event.event_type not in {"handled", "snoozed", "dismissed"}:
                    raise ValueError('Only the actual player may send playback receipts')
                if not payload.get('notification_id'):
                    raise ValueError('notification_id required')
            elif kind not in {"create_binding_code", "query_report"}:
                raise AppError(501, "MODULE_NOT_IMPLEMENTED", "Tool is not implemented")
        except (KeyError, ValueError, ValidationError) as exc:
            raise AppError(422, "VALIDATION_ERROR", "Saved action is missing valid execution parameters") from exc

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
            if body.type == "medication":
                tasks = self.services.tasks.today(tx, actor, row.elder_id, local_date(body.occurred_at)).items
                target = next((t for t in tasks if t.task_id == body.task_id), None)
                if (target is None or target.cancelled or target.plan_id != body.payload.plan_id
                        or target.completion != 'pending'
                        or (payload.get('task_plan_version') is not None and target.plan_version != payload['task_plan_version'])):
                    raise AppError(409, 'VERSION_CONFLICT', 'Medication task changed; please verify the plan again')
                plan = self.services.medication.get_plan(tx, actor, body.payload.plan_id)
                if plan.elder_id != row.elder_id or plan.version != target.plan_version:
                    raise AppError(409, 'VERSION_CONFLICT', 'Medication plan changed after preparation')
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
        elif row.type in {"create_medication_plan", "update_medication_plan"}:
            create = row.type == "create_medication_plan"
            if create:
                body = MedicationPlanWrite.model_validate(payload['plan'])
                if amendments is not None:
                    if type(amendments) is not MedicationPlanWrite:
                        raise AppError(422, "VALIDATION_ERROR", "Amendment must be a complete medication plan")
                    body = amendments
                output = self.services.medication.apply_change(tx, actor, row.elder_id, "create", None, body, None)
            else:
                body = PlanUpdate.model_validate(payload['update'])
                plan = self.services.medication.get_plan(tx, actor, payload['target_id'])
                if plan.elder_id != row.elder_id or plan.version != body.expected_version:
                    raise AppError(409, "VERSION_CONFLICT", "Medication plan changed")
                if amendments is not None:
                    if type(amendments) is not PlanUpdate or amendments.expected_version != body.expected_version:
                        raise AppError(422, "VALIDATION_ERROR", "Amendment has a different type/version")
                    body = amendments
                output = self.services.medication.apply_change(tx, actor, row.elder_id, "update", payload['target_id'], body.patch, body.expected_version)
        elif row.type == "decide_change":
            if amendments is not None:
                raise AppError(422, "VALIDATION_ERROR", "Change decision has no amendments")
            proposal = self.services.changes.read(tx, actor, payload['proposal_id'])
            if proposal.elder_id != row.elder_id:
                raise AppError(404, "NOT_FOUND", "Proposal unavailable")
            output = self.services.changes.decide(tx, actor, proposal.proposal_id,
                                                  ChangeDecision(decision=payload['decision']), self.clock.now())
        elif row.type == "respond_notification":
            if amendments is not None:
                raise AppError(422, "VALIDATION_ERROR", "Notification event has no amendments")
            output = self.services.notifications.handle_event(tx, actor, payload['notification_id'],
                                                               NotificationEvent.model_validate(payload['event']), self.clock.now())
        else:
            raise AppError(501, "MODULE_NOT_IMPLEMENTED", "Tool is not implemented")
        if isinstance(output, (Checkin, Profile, DailyReport)) and output.elder_id != row.elder_id:
            raise AppError(502, "PROVIDER_ERROR", "Business port returned another elder's resource")
        return ActionResult(action_id=row.id, status="confirmed", result=output,
                            reply=Reply(text="已确认，业务服务已成功处理。"))
