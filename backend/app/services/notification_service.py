from datetime import datetime
from sqlalchemy.orm import Session
from app.contracts.context import Actor
from app.core.clock import Clock
from app.core.errors import unimplemented
from app.schemas.health import NotificationEnqueue, NotificationEvent, Notification
from app.schemas.identity import EventResult

class NotificationService:
    """B owns notification delivery. A0/A2 only froze the signatures A needs.

    handle_event must own the full receipt semantics (presence, order, full repeat
    playback) and call the injected ChangePort.mark_played in the SAME tx.
    mark_proposal_handled is the small A2 hook so the proposal state machine can
    close the related notification without touching B's table.
    """

    def __init__(self, clock: Clock | None = None, changes=None):
        self.clock, self.changes = clock, changes

    def bind(self, *, changes=None) -> "NotificationService":
        if changes is not None:
            self.changes = changes
        return self

    def enqueue(self, tx: Session, actor: Actor, source_key: str, payload: NotificationEnqueue) -> Notification:
        unimplemented()

    def handle_event(self, tx: Session, actor: Actor, notification_id: str, event: NotificationEvent, now: datetime) -> EventResult:
        unimplemented()

    def mark_proposal_handled(self, tx: Session, notification_id: str) -> None:
        unimplemented()
