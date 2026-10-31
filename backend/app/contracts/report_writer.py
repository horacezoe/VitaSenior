from dataclasses import dataclass
from typing import Protocol
from app.schemas.health import DailyReport, DailyInsights, SafetySource
from app.schemas.identity import Profile
from app.schemas.agent import MemoryDocument

@dataclass(frozen=True)
class ReportInput:
    profile: Profile
    memory: MemoryDocument
    report: DailyReport
    safety_sources: tuple[SafetySource,...] = ()

class ReportWriter(Protocol):
    """Pure snapshot input; caller closes/commits the UoW before this slow call."""
    def generate(self, snapshot: ReportInput) -> DailyInsights: ...

def report_payload(snapshot):
    report=snapshot.report.model_dump(mode='json',exclude={'updated_at','insights','ai_status','person','anomalies','safety_review_status','reward_summary'})
    if 'completion' in report:report['completion'].pop('anomalies',None)
    return dict(profile=snapshot.profile.model_dump(mode='json',exclude={'updated_at'}),
        memory=snapshot.memory.model_dump(mode='json',exclude={'updated_at'}),report=report,
        safety_sources=[s.model_dump(mode='json') for s in getattr(snapshot,'safety_sources',())])

def report_digest(snapshot):
    import hashlib,json
    return hashlib.sha256(json.dumps(report_payload(snapshot),ensure_ascii=False,sort_keys=True).encode()).hexdigest()
