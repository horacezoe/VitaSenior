from datetime import datetime
from typing import Generic, TypeVar, Literal
from pydantic import BaseModel, ConfigDict, Field, AwareDatetime

class DTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

class SourceRef(DTO):
    type: Literal["checkin", "agent_turn", "profile"]
    id: str
    version: int | None = Field(default=None, ge=1)

class Meta(DTO):
    request_id: str
    server_time: AwareDatetime
    replaced: bool | None = None

T = TypeVar("T")
class Envelope(DTO, Generic[T]):
    data: T
    meta: Meta

class ErrorDetail(DTO):
    code: str
    message: str
    details: dict[str, object] = Field(default_factory=dict)
    retryable: bool = False

class ErrorEnvelope(DTO):
    error: ErrorDetail
    meta: Meta

class Page(DTO, Generic[T]):
    items: list[T]
    next_cursor: str | None = None
