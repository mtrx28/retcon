"""Gate policy table (docs/CONTRACT.md section 7). Data, not logic: add a tool by adding an entry.

Every tool always needs all premises IN. `independent_sources` adds the poisoning-cost rule: above
`over_amount`, the action's min-cut (Lane B's `fragility`) must be at least `min`.
"""
POLICY = {
    "pay": {"independent_sources": {"over_amount": 10_000, "min": 2}},
    "email": {},
    "notify": {},
}
DEFAULT_POLICY: dict = {}


def policy_for(tool: str) -> dict:
    return POLICY.get(tool, DEFAULT_POLICY)
