from typing import Literal
from pydantic import AwareDatetime
from app.schemas.common import DTO

class Health(DTO):
    status: Literal["ok", "degraded"]
    database: Literal["ok", "unavailable"]
    scheduler: Literal["disabled", "running", "stopped", "failed"]
class Runtime(DTO):
    mode: Literal["demo"]
    # Per-modality status: a mock provider is a real, running implementation and
    # must be reportable; "not_implemented" stays for a modality with no provider.
    providers: dict[str, Literal["mock", "real", "not_implemented"]]
    capabilities: dict[str, bool]
    timezone: Literal["Asia/Hong_Kong"]
    server_time: AwareDatetime
