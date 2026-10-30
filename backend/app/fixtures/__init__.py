"""Deterministic demo fixtures. No fixture is a medical recommendation.

Layout (A owns scheduling; B/C own their rows):
  history.py  - 14-day template of tasks/records B imports after ONB02
  identity.py - community sample profiles used by ONB01 match/not_found
"""
from app.fixtures.history import HISTORY_DAYS, history_template
from app.fixtures.identity import SAMPLE_PROFILES, match_sample

__all__ = ["HISTORY_DAYS", "history_template", "SAMPLE_PROFILES", "match_sample"]
