from dataclasses import dataclass
from typing import Literal
from app.schemas.enums import Role
from app.schemas.common import SourceRef

WriteScope = Literal["read", "self", "proposal", "child", "system"]

# Reserved identity for the server-side scanner that settles expired proposals.
# It is never issued by AUTH and never stored in the users table, so a client can
# never act as it. `role` is meaningless for this principal and exists only
# because Actor is a frozen two-field value; require_elder_access short-circuits on
# the reserved id before any role logic runs.
SYSTEM_USER_ID = "system"

@dataclass(frozen=True)
class Actor:
    user_id: str
    role: Role

@dataclass(frozen=True)
class ElderAccess:
    elder_id: str
    owner_user_id: str
    scope: WriteScope

SYSTEM_ACTOR = Actor(SYSTEM_USER_ID, Role.elder)
