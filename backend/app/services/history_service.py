"""Unified demo-history import entry (B implements; A schedules it).

A calls this once from ONB02 for a matched demo draft. B imports the 14-day
template rows from app/fixtures/history.py using demo_id as the source key, so a
repeated confirm or login imports nothing new.
"""
from sqlalchemy.orm import Session
from app.contracts.context import Actor
from app.core.errors import unimplemented
from app.contracts.history import DemoHistorySeed

class HistoryService:
    def import_demo_history(self, tx: Session, actor: Actor, elder_id: str, *, demo_id: str, days: int, seed: DemoHistorySeed | None = None) -> None:
        unimplemented()
