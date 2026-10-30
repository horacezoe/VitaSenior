"""Operation IDs the health domain (B) has actually implemented AND verified.

B owns this file. Register an ID only after its endpoint passes a real-DB test.
"""

# Services/flows have 57 business checks, using an explicitly injected bundle.
# The default composition and several shared ports are still pending A's work;
# keep production endpoints unavailable until those paths are actually verified.
CAPABILITIES: frozenset[str] = frozenset()
