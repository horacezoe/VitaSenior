"""A's frozen factory handshake; the MiMo HTTP/audio implementation lives in real_audio."""
from app.core.config import Settings
from app.providers.mock_audio import TTSProvider
from app.providers.real_audio import MiMoTTS as AudioMiMoTTS


class MiMoTTS(AudioMiMoTTS):
    name = "real"

    def __init__(self, *, api_key: str, base_url: str, model: str,
                 voice: str | None = None, timeout: float = 20.0, transport=None):
        root = "https://api.xiaomimimo.com/v1"
        if not isinstance(base_url, str) or base_url.rstrip("/") != root:
            raise ValueError("MiMo TTS requires the official HTTPS API root")
        super().__init__(api_key=api_key, model=model, voice=voice or "mimo_default",
                         timeout_seconds=timeout, connect_timeout_seconds=min(5.0, timeout),
                         transport=transport)
        self.base_url, self.timeout = root, timeout


def build(settings: Settings) -> TTSProvider:
    return MiMoTTS(api_key=settings.tts_api_key, base_url=settings.tts_base_url,
                   model=settings.tts_model, voice=settings.tts_voice or None,
                   timeout=settings.tts_timeout_seconds)
