from dataclasses import dataclass
from typing import Literal
from app.schemas.enums import Role
from app.schemas.common import SourceRef

WriteScope = Literal["read", "self", "proposal", "child"]
@dataclass(frozen=True)
class Actor:
    user_id: str
    role: Role

@dataclass(frozen=True)
class ElderAccess:
    elder_id: str
    owner_user_id: str
    scope: WriteScope
