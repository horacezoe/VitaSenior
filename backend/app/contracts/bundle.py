from dataclasses import dataclass
from app.contracts.ports import AccessPort, BindingPort, ProfilePort, ChangePort, MedicationPort, CheckinPort, NotificationPort, ReportPort, MemoryPort, MediaPort

@dataclass(frozen=True)
class ServiceBundle:
    access: AccessPort
    binding: BindingPort
    profile: ProfilePort
    changes: ChangePort
    medication: MedicationPort
    checkins: CheckinPort
    notifications: NotificationPort
    reports: ReportPort
    memory: MemoryPort
    media: MediaPort
