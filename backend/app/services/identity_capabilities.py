"""Operation IDs this domain has actually implemented AND verified.

Do not flip an entry to true because code "looks done": the acceptance test for
that endpoint must pass against a real database first (see docs/协作/交接/A.md).
"""

CAPABILITIES: frozenset[str] = frozenset({
    "SYS01", "SYS02", "AUTH01", "AUTH02", "AUTH04",
    "DEMO01", "ONB01", "ONB02", "PROF01", "PROF02",
    "BIND01", "BIND02", "BIND03", "BIND04",
    "MEDIA01", "MEDIA02", "MEDIA03",
    # CHANGE01/CHANGE04 stay false: submitting a proposal needs B's
    # NotificationPort.enqueue and applying one needs B's MedicationPort /
    # C's MemoryPort. The state machine is implemented and tested with doubles;
    # registering them now would advertise an endpoint that still answers 501.
    "CHANGE02", "CHANGE03",
})
