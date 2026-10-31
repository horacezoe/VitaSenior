"""Single assembly point. Business code never imports concrete services.

One shared clock/settings instance is handed to every service, and every cross
domain port is injected here. B's frozen flows additionally refuse to run when a
service does not hold the *application* clock (see health_flows.perform), so this
function is the single switch that makes the wired endpoints live.

A<->B notification/change reference cycle is broken by late binding: build the
change service, give it the notification port, then hand the change port back.
"""
from collections.abc import Iterable

from app.core.clock import Clock, SystemClock
from app.core.config import Settings
from app.services.identity_service import IdentityService
from app.services.access_service import AccessService
from app.services.binding_service import BindingService
from app.services.profile_service import ProfileService
from app.services.change_service import ChangeService
from app.services.medication_service import MedicationService
from app.services.health_service import CheckinService
from app.services.notification_service import NotificationService
from app.services.report_service import ReportService
from app.services.memory_service import MemoryService
from app.services.media_service import MediaService
from app.services import agent_capabilities, health_capabilities, identity_capabilities

from app.contracts.bundle import ServiceBundle

def compose_identity(clock: Clock) -> IdentityService:
    return IdentityService(clock)

def compose(clock: Clock | None = None, settings: Settings | None = None, limiter=None) -> ServiceBundle:
    """Build the bundle. clock/settings default only for isolated unit tests; the
    application always passes its own (app.state.clock / app.state.settings)."""
    clock, settings = clock or SystemClock(), settings or Settings()
    access = AccessService()
    media = MediaService(clock, settings)
    # C's MemoryService takes (clock, access) so its revisions use the same clock.
    memory = MemoryService(clock, access)
    medication = MedicationService(clock, access=access, media=media, memory=memory)
    checkins = CheckinService(clock, access=access, media=media, memory=memory)
    reports = ReportService(clock, access=access, memory=memory)
    changes = ChangeService(clock, settings)
    notifications = NotificationService(clock, access=access, media=media, changes=changes)
    changes.bind(medication=medication, notifications=notifications, memory=memory, media=media)
    return ServiceBundle(
        access=access,
        binding=BindingService(clock, limiter),
        profile=ProfileService(clock, settings),
        changes=changes,
        medication=medication,
        checkins=checkins,
        notifications=notifications,
        reports=reports,
        memory=memory,
        media=media,
        # B implements today's goal generation and the 14-day import on the health
        # service itself, so the narrow Task/History ports point at that instance
        # instead of a second implementation (B keeps his whitelist).
        tasks=checkins,
        history=checkins,
    )

def declared_capabilities() -> frozenset[str]:
    """Union of per-domain declarations. Each domain maintains its own file."""
    return identity_capabilities.CAPABILITIES | health_capabilities.CAPABILITIES | agent_capabilities.CAPABILITIES

def capabilities(operation_ids: Iterable[str]) -> dict[str, bool]:
    declared = declared_capabilities()
    return {op: op in declared for op in sorted(operation_ids)}

def build_agent_providers(settings: Settings | None = None):
    """The single seam for agent providers.

    All three modalities may be mock or real, each switched independently and each
    requiring its own credentials. The returned objects are exactly what the app
    serves with, and `providers()` reports those, so a mock can never be labelled
    real.
    """
    settings = settings or Settings()
    return _build_chat(settings), _build_asr(settings), _build_tts(settings)

def _build_asr(settings: Settings):
    from app.providers.mock_audio import MockASR
    if settings.asr_provider == "mock":
        return MockASR()
    from app.providers.real_audio import MiMoASR  # B owns this adapter
    return MiMoASR(api_key=settings.asr_api_key, base_url=settings.asr_base_url,
                   model=settings.asr_model)

def _build_chat(settings: Settings):
    from app.providers.mock_chat import MockUnderstanding
    if settings.chat_provider == "mock":
        return MockUnderstanding()
    from app.providers.real_understanding import RealUnderstanding  # C owns this adapter
    return RealUnderstanding(api_key=settings.chat_api_key, base_url=settings.chat_base_url,
                             model=settings.chat_model, timeout_seconds=settings.chat_timeout_seconds)

def _build_tts(settings: Settings):
    from app.providers.mock_audio import MockTTS
    if settings.tts_provider == "mock":
        return MockTTS()
    try:
        from app.providers import real_tts  # B owns this module
    except ImportError as exc:
        raise RuntimeError(
            "TTS_PROVIDER=real but app/providers/real_tts.py does not exist yet; "
            "keep TTS_PROVIDER=mock until B delivers the real provider") from exc
    return real_tts.build(settings)

def providers(settings: Settings | None = None) -> dict[str, str]:
    """Report what is actually wired. Never claim 'real' for a mock implementation."""
    settings = settings or Settings()
    return {"chat": settings.chat_provider, "asr": settings.asr_provider, "tts": settings.tts_provider}
