"""A owns media storage, quotas, ownership checks and short-lived tickets.

Bytes are stored under DATA_DIR/media; the absolute path never leaves the server.
Rows are registered in the caller's short write tx (a bounded local write, not an
external provider call). Provider-generated audio is produced outside any tx and
only *registered* here through `register_generated`.

MEDIA03 accepts either a Bearer actor or a signed ticket, so <audio>/<img> can load
content without an Authorization header.
"""
import hashlib
import hmac
from datetime import datetime, timezone
from pathlib import Path
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.contracts.context import Actor
from app.contracts.media import MediaContent
from app.core.auth import require_elder_access
from app.core.clock import Clock
from app.core.config import Settings
from app.core.errors import AppError
from app.core.ids import new_id
from app.models.identity import MediaAsset as MediaAssetRow
from app.schemas.identity import MediaAsset

IMAGE_PURPOSES = frozenset({"meal", "ingredient", "medicine", "face", "document"})
AUDIO_PURPOSES = frozenset({"voice_message", "agent_audio"})
IMAGE_MIME = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
AUDIO_MIME = {"audio/wav": ".wav", "audio/x-wav": ".wav", "audio/mpeg": ".mp3", "audio/webm": ".webm", "audio/mp4": ".m4a"}
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_AUDIO_BYTES = 15 * 1024 * 1024

def _normalize_mime(content_type: str | None) -> str:
    return (content_type or "").split(";")[0].strip().lower()

class MediaService:
    def __init__(self, clock: Clock, settings: Settings):
        self.clock, self.settings = clock, settings

    # ---- public port surface -------------------------------------------------

    def get_asset(self, tx: Session, actor: Actor, asset_id: str) -> MediaAsset:
        row = self._row(tx, asset_id)
        self._require_media_access(tx, actor, row)
        return self._view(row)

    def store_upload(self, tx: Session, actor: Actor, *, elder_id: str | None, purpose: str, filename: str, content_type: str, content: bytes) -> MediaAsset:
        if purpose not in IMAGE_PURPOSES | AUDIO_PURPOSES:
            raise AppError(415, "MEDIA_UNSUPPORTED", "Unsupported media purpose")
        if not content:
            raise AppError(422, "VALIDATION_ERROR", "Empty file")
        if elder_id is not None:
            require_elder_access(tx, actor, elder_id, "read")
        return self._persist(tx, owner_user_id=actor.user_id, elder_id=elder_id, purpose=purpose,
                             content_type=content_type, content=content, duration_ms=None)

    def register_generated(self, tx: Session, actor: Actor, elder_id: str, *, content: bytes, mime_type: str, purpose: str, duration_ms: int | None) -> MediaAsset:
        require_elder_access(tx, actor, elder_id, "self")
        if purpose not in AUDIO_PURPOSES:
            raise AppError(415, "MEDIA_UNSUPPORTED", "Generated media must be audio")
        return self._persist(tx, owner_user_id=actor.user_id, elder_id=elder_id, purpose=purpose,
                             content_type=mime_type, content=content, duration_ms=duration_ms)

    def open_content(self, tx: Session, actor: Actor | None, asset_id: str, *, ticket: str | None = None) -> MediaContent:
        row = self._row(tx, asset_id)
        if ticket is None:
            if actor is None:
                raise AppError(401, "UNAUTHENTICATED", "Bearer token or media ticket required")
            self._require_media_access(tx, actor, row)
        elif not self._verify_ticket(asset_id, ticket):
            # No existence oracle for a bad ticket.
            raise AppError(404, "NOT_FOUND", "Resource unavailable")
        path = self._absolute(row.relative_path)
        if not path.is_file():
            raise AppError(404, "NOT_FOUND", "Resource unavailable")
        return MediaContent(mime_type=row.mime_type, size_bytes=row.size_bytes, path=path)

    # ---- internals -----------------------------------------------------------

    def _row(self, tx: Session, asset_id: str) -> MediaAssetRow:
        row = tx.get(MediaAssetRow, asset_id)
        if row is None:
            raise AppError(404, "NOT_FOUND", "Resource unavailable")
        return row

    def _require_media_access(self, tx: Session, actor: Actor, row: MediaAssetRow) -> None:
        if row.owner_user_id == actor.user_id:
            return
        if row.elder_id is None:
            raise AppError(404, "NOT_FOUND", "Resource unavailable")
        try:
            require_elder_access(tx, actor, row.elder_id, "read")
        except AppError as exc:
            if exc.code == "ELDER_ACCESS_DENIED":
                raise AppError(404, "NOT_FOUND", "Resource unavailable") from exc
            raise

    def _persist(self, tx: Session, *, owner_user_id: str, elder_id: str | None, purpose: str,
                 content_type: str, content: bytes, duration_ms: int | None) -> MediaAsset:
        mime = _normalize_mime(content_type)
        if purpose in IMAGE_PURPOSES:
            allowed, limit, too_large = IMAGE_MIME, MAX_IMAGE_BYTES, "Images are limited to 10 MiB"
        else:
            allowed, limit, too_large = AUDIO_MIME, MAX_AUDIO_BYTES, "Audio is limited to 15 MiB"
        if mime not in allowed:
            raise AppError(415, "MEDIA_UNSUPPORTED", "Unsupported media type for this purpose", {"mime_type": mime})
        if len(content) > limit:
            raise AppError(413, "MEDIA_TOO_LARGE", too_large, {"max_bytes": limit})
        asset_id = new_id("asset")
        relative = Path("media") / f"{asset_id}{allowed[mime]}"
        absolute = self._absolute(relative)
        absolute.parent.mkdir(parents=True, exist_ok=True)
        absolute.write_bytes(content)
        row = MediaAssetRow(id=asset_id, owner_user_id=owner_user_id, elder_id=elder_id, purpose=purpose,
                            mime_type=mime, size_bytes=len(content), duration_ms=duration_ms,
                            relative_path=relative.as_posix(), created_at=self.clock.now())
        tx.add(row)
        tx.flush()
        return self._view(row)

    def _view(self, row: MediaAssetRow) -> MediaAsset:
        url, expires_at = self._ticket_url(row.id)
        return MediaAsset(asset_id=row.id, purpose=row.purpose, mime_type=row.mime_type, size_bytes=row.size_bytes,
                          duration_ms=row.duration_ms, content_url=url, expires_at=expires_at)

    def _absolute(self, relative: Path | str) -> Path:
        root = self.settings.data_dir.resolve()
        path = (root / Path(relative)).resolve()
        if root not in path.parents:
            raise AppError(404, "NOT_FOUND", "Resource unavailable")
        return path

    def _sign(self, asset_id: str, expires_at: int) -> str:
        mac = hmac.new(self.settings.media_ticket_secret.encode(), f"{asset_id}:{expires_at}".encode(), hashlib.sha256).hexdigest()
        return f"{expires_at}.{mac}"

    def _ticket_url(self, asset_id: str) -> tuple[str, datetime]:
        expires_at = int(self.clock.now().timestamp()) + self.settings.media_ticket_seconds
        url = f"{self.settings.public_base_url}/api/v1/media/{asset_id}/content?ticket={self._sign(asset_id, expires_at)}"
        return url, datetime.fromtimestamp(expires_at, timezone.utc)

    def _verify_ticket(self, asset_id: str, ticket: str) -> bool:
        expires_text, _, mac = ticket.partition(".")
        if not expires_text.isdigit() or not mac:
            return False
        expires_at = int(expires_text)
        if expires_at <= int(self.clock.now().timestamp()):
            return False
        # Compare the whole "<expires>.<mac>" string: the mac alone is shorter.
        return hmac.compare_digest(ticket, self._sign(asset_id, expires_at))
