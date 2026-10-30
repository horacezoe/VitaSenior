import asyncio
import logging
from collections.abc import Callable
from app.core.clock import Clock

log = logging.getLogger(__name__)
class Scanner:
    """F0 lifecycle only. No reminders, auto-apply, models or providers."""
    def __init__(self, clock: Clock, *, enabled: bool = False, interval: float = 5.0, tick_hook: Callable | None = None):
        self.clock, self.enabled, self.interval = clock, enabled, interval
        self.tick_hook = tick_hook
        self.task: asyncio.Task | None = None
        self.status = "stopped"
        self.last_tick_at = None
    def tick(self) -> None:
        now = self.clock.now()
        if self.tick_hook:
            self.tick_hook(now)
        self.last_tick_at = now
    async def _run(self):
        try:
            while True:
                self.tick()
                await asyncio.sleep(self.interval)
        except asyncio.CancelledError:
            raise
        except Exception:
            self.status = "failed"
            log.exception("Scanner failed")
    async def start(self):
        if self.enabled and self.task is None:
            self.status = "running"
            self.task = asyncio.create_task(self._run(), name="vitasenior-scanner")
    async def stop(self):
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
            self.task = None
        if self.status != "failed":
            self.status = "stopped"
