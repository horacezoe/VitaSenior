from app.contracts.safety import SafetyPort
from dataclasses import dataclass
from app.contracts.ports import (
    AccessPort, BindingPort, ProfilePort, ChangePort, MedicationPort, CheckinPort,
    NotificationPort, TaskPort, ReportPort, MemoryPort, MediaPort, HistoryPort,
)

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
    # Added by A0 (shared adaptation). Defaults keep older test doubles working;
    # composition always supplies the real (stub) implementations.
    tasks: TaskPort
    history: HistoryPort

    safety: SafetyPort | None = None
