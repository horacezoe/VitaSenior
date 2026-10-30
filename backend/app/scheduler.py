import asyncio
import logging
from collections.abc import Callable
from app.core.clock import Clock
from app.core.uow import UnitOfWork
from app.contracts.bundle import ServiceBundle


def scan_due(factory, services: ServiceBundle, now, *, scan_hook: Callable | None = None):
    """One short, caller-owned system transaction; no fabricated user actor.

    A wires the health-domain scan hook in composition, alongside the frozen
    ChangePort. Hooks must be deterministic DB work, never TTS/push/provider I/O.
    A failure rolls back both due proposals and newly enqueued reminders.
    """
    with UnitOfWork(factory) as uow:
        services.changes.apply_due(uow.session, now)
        if scan_hook:
            scan_hook(uow.session, now)
        uow.commit()

log = logging.getLogger(__name__)
class Scanner:
    """Single-process lifecycle with an injectable deterministic system tick."""
    def __init__(self, clock: Clock, *, enabled: bool = False, interval: float = 5.0,
                 tick_hook: Callable | None = None, factory=None,
                 services: ServiceBundle | None = None, scan_hook: Callable | None = None):
        self.clock, self.enabled, self.interval = clock, enabled, interval
        self.tick_hook = tick_hook
        self.factory, self.services, self.scan_hook = factory, services, scan_hook
        self.task: asyncio.Task | None = None
        self.status = "stopped"
        self.last_tick_at = None
    def tick(self) -> None:
        now = self.clock.now()
        if self.factory is not None and self.services is not None:
            scan_due(self.factory, self.services, now, scan_hook=self.scan_hook)
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
