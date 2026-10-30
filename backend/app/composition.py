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
from app.services.task_service import TaskService
from app.services.report_service import ReportService
from app.services.memory_service import MemoryService
from app.services.media_service import MediaService
from app.services.history_service import HistoryService
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
    # C's MemoryService takes (clock, access) once backend/agent is merged; today's
    # stub takes no arguments, so the constructor call is the one edit to make then.
    memory = MemoryService()
    medication = MedicationService(clock, access=access, media=media, memory=memory)
    checkins = CheckinService(clock, access=access, memory=memory, media=media)
    reports = ReportService(clock, access=access, memory=memory)
    changes = ChangeService(clock, settings)
    notifications = NotificationService(clock, access=access, media=media, changes=changes)
    changes.bind(medication=medication, notifications=notifications, memory=memory)
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
        tasks=TaskService(),
        history=HistoryService(),
    )

def declared_capabilities() -> frozenset[str]:
    """Union of per-domain declarations. Each domain maintains its own file."""
    return identity_capabilities.CAPABILITIES | health_capabilities.CAPABILITIES | agent_capabilities.CAPABILITIES

def capabilities(operation_ids: Iterable[str]) -> dict[str, bool]:
    declared = declared_capabilities()
    return {op: op in declared for op in sorted(operation_ids)}

def providers() -> dict[str, str]:
    return dict(agent_capabilities.PROVIDERS)
