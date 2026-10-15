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


def observe(source, text, observed_at, agent="intake"):
    """Additive (B3): ingest one observation from a Source. `observed_at` is ISO 8601 or epoch seconds.
    The observation lands in the agent's context, so the next `remember` is justified by it."""
    return _guard(lambda: _service.observe(source, text, observed_at, agent))


def begin_turn(agent):
    """Additive (B3): start a fresh turn; the agent's captured context is cleared."""
    def run():
        _service.begin_turn(agent)
        return {"ok": True}
    return _guard(run)


def recall(query, agent, k=8, contains=None):
    """`contains` (additive, B3): keep only memories whose text includes this substring, so an agent
    can scope retrieval to one entity (a vendor) before anything is captured as a premise."""
    return _guard(lambda: _service.recall(query, agent, k, contains))


def fragility(node_id):
    """Contract shape {independent_sources, bound}; `cut_set` (the sources to compromise, for the radar UI)
    and `flow_upper_bound` are additive."""
    def run():
        f = _fragility(_service.g, node_id)
        return {k: f[k] for k in ("independent_sources", "bound", "cut_set", "flow_upper_bound")}
    return _guard(run)
