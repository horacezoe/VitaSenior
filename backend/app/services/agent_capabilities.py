"""Operation IDs and provider status the agent domain (C) has verified.

C owns this file in normal work; A activated the batch below after finishing the
A-owned wiring (app.state.agent/agent_chat/agent_asr/agent_tts) and relaxing the
Runtime.providers enum so a mock provider can be reported as a real value.
"""

# C2 HTTP flows, verified end to end on integration/f1: mock understanding plans
# an action, the confirmation executes through B's CheckinPort into a real
# checkin, and memory read/update/delete use C's real MemoryService.
C2_OPERATIONS: frozenset[str] = frozenset({'AI01', 'AI02', 'AGENT01', 'AGENT02', 'MEM01', 'MEM02', 'MEM03'})
CAPABILITIES: frozenset[str] = C2_OPERATIONS

PROVIDERS: dict[str, str] = {
    "chat": "mock",
    "asr": "mock",
    "tts": "mock",
}
