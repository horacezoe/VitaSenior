"""Operation IDs this domain has actually implemented AND verified.

Do not flip an entry to true because code "looks done": the acceptance test for
that endpoint must pass against a real database first (see docs/协作/交接/A.md).
"""

CAPABILITIES: frozenset[str] = frozenset({
    "SYS01", "SYS02", "AUTH01", "AUTH02", "AUTH04",
    "DEMO01", "ONB01", "ONB02", "PROF01", "PROF02",
    "BIND01", "BIND02", "BIND03", "BIND04",
    "MEDIA01", "MEDIA02", "MEDIA03",
    # CHANGE01 and CHANGE04 are live now: B's enqueue/mark_proposal_handled and C's
    # MemoryPort.on_source_changed are merged, so the whole apply path runs.
    "CHANGE01", "CHANGE02", "CHANGE03", "CHANGE04",
})
