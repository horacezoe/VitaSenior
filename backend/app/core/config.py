from dataclasses import dataclass, field
from pathlib import Path
import os

@dataclass(frozen=True)
class Settings:
    data_dir: Path = field(default_factory=lambda: Path(os.getenv("DATA_DIR", "data")))
    scanner_enabled: bool = field(default_factory=lambda: os.getenv("SCANNER_ENABLED", "false").lower() == "true")
    cors_origins: tuple[str, ...] = field(default_factory=lambda: tuple(filter(None, os.getenv("CORS_ORIGINS", "http://localhost:5173").split(","))))
    app_env: str = field(default_factory=lambda: os.getenv("APP_ENV", "demo"))
    public_base_url: str = field(default_factory=lambda: os.getenv("PUBLIC_BASE_URL", "http://localhost:8000"))
    app_timezone: str = field(default_factory=lambda: os.getenv("APP_TIMEZONE", "Asia/Hong_Kong"))
    chat_provider: str = field(default_factory=lambda: os.getenv("CHAT_PROVIDER", "mock"))
    asr_provider: str = field(default_factory=lambda: os.getenv("ASR_PROVIDER", "mock"))
    tts_provider: str = field(default_factory=lambda: os.getenv("TTS_PROVIDER", "mock"))
    web_push_enabled: bool = field(default_factory=lambda: os.getenv("WEB_PUSH_ENABLED", "false").lower() == "true")
    database_url: str | None = field(default_factory=lambda: os.getenv("DATABASE_URL") or None)
    session_hours: int = 48
    challenge_seconds: int = 300
    scanner_interval: float = 5.0
    # Media tickets: short-lived HMAC links so <audio>/<img> can load bytes without
    # an Authorization header. The default is a demo-only value; set
    # MEDIA_TICKET_SECRET in any shared/demo deployment.
    media_ticket_seconds: int = 300
    media_ticket_secret: str = field(default_factory=lambda: os.getenv("MEDIA_TICKET_SECRET", "dev-only-media-ticket-secret"))
    def __post_init__(self):
        if self.app_env not in {"development", "demo", "test"}:
            raise ValueError("F0 supports development/demo/test environments only")
        if self.app_timezone != "Asia/Hong_Kong":
            raise ValueError("Business timezone is frozen to Asia/Hong_Kong")
        if self.chat_provider != "mock" or self.asr_provider != "mock":
            raise ValueError("F2 allows real providers only for TTS; chat/ASR must stay mock")
        if self.tts_provider not in {"mock", "real"}:
            raise ValueError("TTS_PROVIDER must be 'mock' or 'real'")
        if self.web_push_enabled:
            raise ValueError("Web Push is not implemented in F0")
        if self.scanner_interval <= 0:
            raise ValueError("scanner_interval must be positive")
        if not (30 <= self.media_ticket_seconds <= 3600):
            raise ValueError("media_ticket_seconds must be within 30..3600")
        if len(self.media_ticket_secret) < 16:
            raise ValueError("media_ticket_secret must be at least 16 characters")

    @property
    def media_dir(self) -> Path:
        return self.data_dir / "media"
