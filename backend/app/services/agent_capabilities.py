"""Operation IDs and provider status the agent domain (C) has verified.

C owns this file: register an ID only after a real test, and report the actual
provider behind each modality (mock is a value, not a placeholder).
"""

# C2 implementation and explicit-DI HTTP tests cover these IDs. A must wire
# AgentService/providers and fix Runtime.providers enum BEFORE activating them.
C2_OPERATIONS: frozenset[str] = frozenset({'AI01', 'AI02', 'AGENT01', 'AGENT02', 'MEM01', 'MEM02', 'MEM03'})
CAPABILITIES: frozenset[str] = frozenset()

PROVIDERS: dict[str, str] = {
    "chat": "not_implemented",
    "asr": "not_implemented",
    "tts": "not_implemented",
}
