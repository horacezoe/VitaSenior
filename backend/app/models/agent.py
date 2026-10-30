from datetime import datetime
from sqlalchemy import String, JSON, ForeignKey, UniqueConstraint, CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.core.db import Base, UTCDateTime
from app.core.ids import new_id

class AgentTurn(Base):
    __tablename__ = "agent_turns"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("turn"))
    elder_id: Mapped[str] = mapped_column(ForeignKey("elder_profiles.id"))
    actor_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    conversation_id: Mapped[str] = mapped_column(String)
    client_turn_id: Mapped[str] = mapped_column(String)
    request_json: Mapped[dict] = mapped_column(JSON)
    response_json: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    __table_args__ = (UniqueConstraint("elder_id", "client_turn_id"),)
class AgentAction(Base):
    __tablename__ = "agent_actions"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("action"))
    turn_id: Mapped[str] = mapped_column(ForeignKey("agent_turns.id"))
    elder_id: Mapped[str] = mapped_column(ForeignKey("elder_profiles.id"))
    type: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(default="pending")
    payload_json: Mapped[dict] = mapped_column(JSON)
    result_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    __table_args__ = (CheckConstraint("status IN ('pending','confirmed','cancelled','expired')"),)
class MemoryDocument(Base):
    __tablename__ = "memory_documents"
    elder_id: Mapped[str] = mapped_column(ForeignKey("elder_profiles.id"), primary_key=True)
    version: Mapped[int] = mapped_column(default=1)
    entries_json: Mapped[list] = mapped_column(JSON, default=list)
    revisions_json: Mapped[list] = mapped_column(JSON, default=list)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime)
    __table_args__ = (CheckConstraint("version >= 1"),)
