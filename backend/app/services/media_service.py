from sqlalchemy.orm import Session
from app.contracts.context import Actor
from app.schemas.identity import MediaAsset
from app.core.errors import unimplemented

class MediaService:
    def get_asset(self, tx: Session, actor: Actor, asset_id: str) -> MediaAsset:
        """F2 must check uploader/binding before signing a short-lived content URL."""
        unimplemented()
