"""Operation IDs this domain has actually implemented AND verified.

Do not flip an entry to true because code "looks done": the acceptance test for
that endpoint must pass against a real database first (see docs/协作/交接/A.md).
"""

CAPABILITIES: frozenset[str] = frozenset({
    "SYS01", "SYS02", "AUTH01", "AUTH02", "AUTH04",
    "DEMO01", "ONB01", "ONB02", "PROF01", "PROF02",
    "BIND01", "BIND02", "BIND03", "BIND04",
    "MEDIA01", "MEDIA02", "MEDIA03",
    # CHANGE01 is live now that B's NotificationPort.enqueue exists (verified by the
    # integration smoke). CHANGE04 stays false: applying still needs C's MemoryPort
    # for profile/settings targets and B's MedicationPort for plan targets.
    "CHANGE01", "CHANGE02", "CHANGE03",
})
