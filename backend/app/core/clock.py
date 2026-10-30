from datetime import datetime, timedelta, timezone, date
from typing import Protocol
from zoneinfo import ZoneInfo

UTC = timezone.utc
HK = ZoneInfo("Asia/Hong_Kong")
class Clock(Protocol):
    def now(self) -> datetime: ...

class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)

class FakeClock:
    def __init__(self, now: datetime):
        if now.tzinfo is None:
            raise ValueError("Clock requires an aware UTC timestamp")
        self._now = now.astimezone(UTC)
    def now(self) -> datetime:
        return self._now
    def advance(self, *, seconds: float = 0) -> None:
        self._now += timedelta(seconds=seconds)

def local_date(now: datetime) -> date:
    return now.astimezone(HK).date()
