"""Lane B MCP tools: remember, recall, fragility (act lands with B3/A4).

Plain functions with the contract signatures from docs/CONTRACT.md section 5; registering them
with the MCP server is a one-liner each once the server exists. They never raise: failures come
back as the uniform {"error": {...}} payload.
"""
from core.errors import RetconError
from core.fragility import fragility as _fragility

_service = None


def configure(service):
    """Inject the MemoryService (one per tenant graph)."""
    global _service
    _service = service


def _guard(fn):
    try:
        return fn()
    except RetconError as e:
        return e.as_payload()


def remember(text, kind, agent, mtype=None):
    """`mtype` is the optional contract v1.1 argument: episodic | semantic | procedural."""
    def run():
        r = _service.remember(text, kind, agent, mtype=mtype)
        return {"node_id": r["node_id"], "premise_ids": r["premise_ids"]}
    return _guard(run)


def recall(query, agent, k=8):
    return _guard(lambda: _service.recall(query, agent, k))


def fragility(node_id):
    """Contract shape {independent_sources, bound}; `cut_set` (the sources to compromise, for the radar UI)
    and `flow_upper_bound` are additive."""
    def run():
        f = _fragility(_service.g, node_id)
        return {k: f[k] for k in ("independent_sources", "bound", "cut_set", "flow_upper_bound")}
    return _guard(run)
