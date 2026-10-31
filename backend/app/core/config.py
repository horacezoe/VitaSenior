from dataclasses import dataclass, field
from pathlib import Path
import os

@dataclass(frozen=True)
class Settings:
    data_dir: Path = field(default_factory=lambda: Path(os.getenv("DATA_DIR", "data")))
    safety_review_enabled: bool = field(default_factory=lambda: os.getenv("SAFETY_REVIEW_ENABLED", "false").lower() == "true")
    scanner_enabled: bool = field(default_factory=lambda: os.getenv("SCANNER_ENABLED", "false").lower() == "true")
    cors_origins: tuple[str, ...] = field(default_factory=lambda: tuple(filter(None, os.getenv("CORS_ORIGINS", "http://localhost:5173").split(","))))
    app_env: str = field(default_factory=lambda: os.getenv("APP_ENV", "demo"))
    public_base_url: str = field(default_factory=lambda: os.getenv("PUBLIC_BASE_URL", "http://localhost:8000"))
    app_timezone: str = field(default_factory=lambda: os.getenv("APP_TIMEZONE", "Asia/Hong_Kong"))
    chat_provider: str = field(default_factory=lambda: os.getenv("CHAT_PROVIDER", "mock"))
    # Real understanding (C's adapter). Empty by default so a normal start stays
    # mock; CHAT_PROVIDER=real refuses to boot unless all three are set.
    chat_api_key: str = field(default_factory=lambda: os.getenv("CHAT_API_KEY", ""))
    chat_base_url: str = field(default_factory=lambda: os.getenv("CHAT_BASE_URL", ""))
    chat_model: str = field(default_factory=lambda: os.getenv("CHAT_MODEL", ""))
    chat_timeout_seconds: float = 20.0
    asr_provider: str = field(default_factory=lambda: os.getenv("ASR_PROVIDER", "mock"))
    # Real ASR (B's adapter). Same policy as chat/TTS: empty by default and
    # ASR_PROVIDER=real refuses to boot unless the three connection fields are set.
    asr_api_key: str = field(default_factory=lambda: os.getenv("ASR_API_KEY", ""))
    asr_base_url: str = field(default_factory=lambda: os.getenv("ASR_BASE_URL", ""))
    asr_model: str = field(default_factory=lambda: os.getenv("ASR_MODEL", ""))
    tts_provider: str = field(default_factory=lambda: os.getenv("TTS_PROVIDER", "mock"))
    # Real speech (B's adapter). Same policy as chat: empty by default, and
    # TTS_PROVIDER=real refuses to boot unless the three connection fields are set.
    tts_api_key: str = field(default_factory=lambda: os.getenv("TTS_API_KEY", ""))
    tts_base_url: str = field(default_factory=lambda: os.getenv("TTS_BASE_URL", ""))
    tts_model: str = field(default_factory=lambda: os.getenv("TTS_MODEL", ""))
    tts_voice: str = field(default_factory=lambda: os.getenv("TTS_VOICE", ""))
    tts_timeout_seconds: float = 20.0
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
        if self.asr_provider not in {"mock", "real"}:
            raise ValueError("ASR_PROVIDER must be 'mock' or 'real'")
        if self.asr_provider == "real" and not all((self.asr_api_key, self.asr_base_url, self.asr_model)):
            raise ValueError("ASR_PROVIDER=real requires ASR_API_KEY, ASR_BASE_URL and ASR_MODEL")
        if self.chat_provider not in {"mock", "real"}:
            raise ValueError("CHAT_PROVIDER must be 'mock' or 'real'")
        if self.chat_provider == "real" and not all((self.chat_api_key, self.chat_base_url, self.chat_model)):
            raise ValueError("CHAT_PROVIDER=real requires CHAT_API_KEY, CHAT_BASE_URL and CHAT_MODEL")
        if self.tts_provider not in {"mock", "real"}:
            raise ValueError("TTS_PROVIDER must be 'mock' or 'real'")
        if self.tts_provider == "real" and not all((self.tts_api_key, self.tts_base_url, self.tts_model)):
            raise ValueError("TTS_PROVIDER=real requires TTS_API_KEY, TTS_BASE_URL and TTS_MODEL")
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
