from dataclasses import dataclass
from typing import Protocol
from app.schemas.health import DailyReport, DailyInsights
from app.schemas.identity import Profile
from app.schemas.agent import MemoryDocument

@dataclass(frozen=True)
class ReportInput:
    profile: Profile
    memory: MemoryDocument
    report: DailyReport

class ReportWriter(Protocol):
    """Pure snapshot input; caller closes/commits the UoW before this slow call."""
    def generate(self, snapshot: ReportInput) -> DailyInsights: ...
