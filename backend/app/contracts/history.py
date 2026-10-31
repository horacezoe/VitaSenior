"""Facts authorized by onboarding for the narrow history import port."""
from dataclasses import dataclass


@dataclass(frozen=True)
class DemoHistorySeed:
    template_key: str
    # Stable fixture plan key -> exact, unchanged plan imported in this transaction.
    plan_ids: dict[str, str]
