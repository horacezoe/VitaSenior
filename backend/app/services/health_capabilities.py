"""Operation IDs the health domain (B) has actually implemented AND verified.

B owns this file. Register an ID only after its endpoint passes a real-DB test.
"""

# Real default-composition HTTP checks cover these operations, including A's
# media/identity and C's memory. NOTI03 remains gated until A replaces the proposal
# cue with a complete spoken change notice; a tone must not start auto-apply.
CAPABILITIES: frozenset[str] = frozenset({
    "PLAN01", "PLAN02", "PLAN03", "SET01", "SET02", "TASK01",
    "REC01", "REC02", "REC03", "REC04", "DASH01", "CAL01", "REPORT01",
    "NOTI01", "NOTI02", "NOTI04",
})
