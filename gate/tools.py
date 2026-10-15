"""MCP `act` (docs/CONTRACT.md section 5): the gate sits behind this signature.

    act(tool, args, agent) -> {executed, action_id, blocked_reason?}

Owned by Lane A (gate/); Lane B's agent loop calls it like any other tool. It needs the same
PremiseCapture as the MemoryService so the action is justified by what the agent recalled.
"""
from core.errors import RetconError

_service = None


def configure(action_service):
    global _service
    _service = action_service


def act(tool: str, args: dict, agent: str):
    """Ask the gate and, if allowed, execute. A blocked action carries the reason (which premise is
    OUT and which retraction removed it, or the independent-source shortfall)."""
    if _service is None:
        return RetconError("NOT_CONFIGURED", "act is not configured", {}).as_payload()
    try:
        return _service.act(tool, args, agent)
    except RetconError as e:
        return e.as_payload()
