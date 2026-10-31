"""Operation IDs the health domain (B) has actually implemented AND verified.

B owns this file. Register an ID only after its endpoint passes a real-DB test.
"""

# Real default-composition HTTP checks cover these operations, including complete
# proposal speech, A's 60-second window/restart, and text-only speech fallback.
CAPABILITIES: frozenset[str] = frozenset({
    "PLAN01", "PLAN02", "PLAN03", "PLAN05", "SET01", "SET02", "TASK01",
    "REC01", "REC02", "REC03", "REC04", "DASH01", "CAL01", "REPORT01",
    "NOTI01", "NOTI02", "NOTI03", "NOTI04",
})
