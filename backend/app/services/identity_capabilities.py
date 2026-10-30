"""Operation IDs this domain has actually implemented AND verified.

Do not flip an entry to true because code "looks done": the acceptance test for
that endpoint must pass against a real database first (see docs/协作/交接/A.md).
"""

CAPABILITIES: frozenset[str] = frozenset({
    "SYS01", "SYS02", "AUTH01", "AUTH02", "AUTH04",
})
