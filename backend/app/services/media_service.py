from sqlalchemy.orm import Session
from app.contracts.context import Actor
from app.contracts.media import MediaContent
from app.core.clock import Clock
from app.core.config import Settings
from app.core.errors import unimplemented
from app.schemas.identity import MediaAsset

class MediaService:
    """A owns media storage, quotas, ownership checks and short-lived tickets.
    Files are written outside the DB write tx; only the row is registered in-tx."""

    def __init__(self, clock: Clock, settings: Settings):
        self.clock, self.settings = clock, settings

    def get_asset(self, tx: Session, actor: Actor, asset_id: str) -> MediaAsset:
        unimplemented()

    def store_upload(self, tx: Session, actor: Actor, *, elder_id: str | None, purpose: str, filename: str, content_type: str, content: bytes) -> MediaAsset:
        unimplemented()

    def open_content(self, tx: Session, actor: Actor | None, asset_id: str, *, ticket: str | None = None) -> MediaContent:
        unimplemented()

    def register_generated(self, tx: Session, actor: Actor, elder_id: str, *, content: bytes, mime_type: str, purpose: str, duration_ms: int | None) -> MediaAsset:
        unimplemented()
