"""Lane B MCP tools: remember, recall (act and fragility land in B3/B5).

Plain functions with the contract signatures from docs/CONTRACT.md section 5; registering them
with the MCP server is a one-liner each once the server exists. They never raise: failures come
back as the uniform {"error": {...}} payload.
"""
from core.errors import RetconError

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


def remember(text, kind, agent):
    def run():
        r = _service.remember(text, kind, agent)
        return {"node_id": r["node_id"], "premise_ids": r["premise_ids"]}
    return _guard(run)


def recall(query, agent, k=8):
    return _guard(lambda: _service.recall(query, agent, k))
