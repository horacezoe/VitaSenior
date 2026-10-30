from app.core.clock import Clock
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

from app.contracts.bundle import ServiceBundle

def compose_identity(clock: "Clock") -> "IdentityService":
    return IdentityService(clock)

def compose() -> ServiceBundle:
    return ServiceBundle(access=AccessService(), binding=BindingService(), profile=ProfileService(), changes=ChangeService(), medication=MedicationService(), checkins=CheckinService(), notifications=NotificationService(), reports=ReportService(), memory=MemoryService(), media=MediaService())
