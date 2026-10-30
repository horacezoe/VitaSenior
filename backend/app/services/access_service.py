from sqlalchemy.orm import Session
from app.contracts.context import Actor, ElderAccess, WriteScope
from app.core.auth import require_elder_access
class AccessService:
    def require_elder_access(self, tx: Session, actor: Actor, elder_id: str, write_scope: WriteScope = "read") -> ElderAccess:
        return require_elder_access(tx, actor, elder_id, write_scope)
