"""Private planning values. Public inputs/results always use shared schemas.

Snapshots contain DTOs read by the application through A/B ports; no provider
has a Session, an ORM object, or the power to commit a tool call.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, Literal

from pydantic import BaseModel, ConfigDict, Field, AwareDatetime

from app.schemas.agent import AgentTurnWrite, Action, MemoryDocument
from app.schemas.health import DailyTask
from app.schemas.identity import Profile


def request_digest(body: AgentTurnWrite) -> str:
    return hashlib.sha256(json.dumps(body.model_dump(mode="json"), sort_keys=True,
                                     ensure_ascii=False).encode()).hexdigest()


@dataclass(frozen=True)
class ImageInput:
    """Authorized immutable bytes; no path, media ticket, token or ORM object."""
    asset_id: str
    mime_type: str
    content: bytes


class ConversationDraft(BaseModel):
    """C-private, persisted in an existing turn; never an executable action.

    No model-authored IDs, dates, targets or permissions are accepted here.
    Expiry and occurrence time are fixed by the server on first input.
    """
    model_config = ConfigDict(extra='forbid')
    kind: Literal['diet', 'exercise', 'medication']
    occurred_at: AwareDatetime
    expires_at: AwareDatetime
    meal_slot: Literal['breakfast', 'lunch', 'dinner'] | None = None
    foods: list[str] = Field(default_factory=list, max_length=20)
    food_groups: list[Literal['vegetable', 'protein', 'staple', 'fruit', 'dairy', 'fat', 'other']] = Field(default_factory=list)
    image_asset_ids: list[str] = Field(default_factory=list, max_length=3)
    activity: str | None = None
    duration_minutes: int | None = Field(default=None, ge=1, le=1440)


@dataclass(frozen=True)
class Snapshot:
    elder_id: str
    now: datetime
    memory: MemoryDocument
    profile: Profile | None = None
    tasks: tuple[DailyTask, ...] = ()
    medication_slots: dict[str, str] = field(default_factory=dict)
    pending_action_ids: tuple[str, ...] = ()
    proposal_id: str | None = None
    images: tuple[ImageInput, ...] = ()
    conversation_id: str | None = None
    conversation_revision: str | None = None
    draft: ConversationDraft | None = None
    selected_action: PlannedAction | None = None
    active_action_id: str | None = None
    report_text: str | None = None
    medication_names: dict[str, str] = field(default_factory=dict)
    dialogue_history: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class PlannedAction:
    action: Action
    # Server-authored complete execution data, NOT the visual preview.
    payload: dict


@dataclass(frozen=True)
class Plan:
    request_hash: str
    scene: str
    reply: str
    actions: tuple[PlannedAction, ...] = ()
    preference: str | None = None
    decision_action_id: str | None = None
    transcript: str | None = None
    asr_provider: str = "not_used"
    chat_provider: str = "mock"
    decision_kind: Literal['confirm', 'cancel'] = 'confirm'
    supersede_action_id: str | None = None
    draft: ConversationDraft | None = None
    active_action_id: str | None = None


class UnderstandingProvider(Protocol):
    def plan(self, request: AgentTurnWrite, snapshot: Snapshot) -> Plan: ...
