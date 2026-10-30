"""Operation IDs and provider status the agent domain (C) has verified.

C owns this file: register an ID only after a real test, and report the actual
provider behind each modality (mock is a value, not a placeholder).
"""

CAPABILITIES: frozenset[str] = frozenset()

PROVIDERS: dict[str, str] = {
    "chat": "not_implemented",
    "asr": "not_implemented",
    "tts": "not_implemented",
}
