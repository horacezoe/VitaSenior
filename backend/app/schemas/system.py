from typing import Literal
from pydantic import AwareDatetime
from app.schemas.common import DTO

class Health(DTO):
    status: Literal["ok", "degraded"]
    database: Literal["ok", "unavailable"]
    scheduler: Literal["disabled", "running", "stopped", "failed"]
class Runtime(DTO):
    mode: Literal["demo"]
    providers: dict[str, Literal["not_implemented"]]
    capabilities: dict[str, bool]
    timezone: Literal["Asia/Hong_Kong"]
    server_time: AwareDatetime
