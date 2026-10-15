"""Lane A MCP tools (docs/CONTRACT.md section 5): distrust, reinstate, why, recall_list, plus the
Remediator's list_remediations / approve_remediation / reject_remediation (task A4).

Plain functions over one tenant graph; `server.py` registers them. They never raise: failures come
back as the uniform {"error": {code, message, details}} payload from core/errors.py.

`distrust(mode="preview")` runs the retraction on a GRAPH.COPY fork and returns the diff without
touching the live graph (task A5).
"""
from core.errors import RetconError
from core.recall.recall_list import recall_list as _recall_list
from core.preview import preview as preview_mod
from core.retract import cascade
from core.retract.why import why as _why
from agents import remediator

_graph = None
_executor = None


def configure(graph, executor=None):
    """Inject the tenant graph these tools act on, and the executor that carries out approved
    compensations (gate.executors.SandboxExecutor / HttpExecutor). Without one, approvals are
    recorded but nothing is sent."""
    global _graph, _executor
    _graph, _executor = graph, executor


def _guard(fn):
    if _graph is None:
        return RetconError("NOT_CONFIGURED", "no tenant graph configured", {}).as_payload()
    try:
        return fn(_graph)
    except RetconError as e:
        return e.as_payload()


def distrust(source: str, from_: str, to: str, mode: str = "commit",
             operator: str = "mcp", reason: str | None = None):
    """Retract everything that rested only on `source` observations learned in [from_, to].

    `from_`/`to` are ISO 8601 timestamps (or epoch seconds). Nodes with independent support stay IN.
    Returns {retraction_id, flipped, flipped_ids, hops, blocked_action_ids, recall_list, latency_ms}.
    """
    if mode not in ("preview", "commit"):
        return RetconError("INVALID_ARGUMENT", "mode must be 'preview' or 'commit'", {"mode": mode}).as_payload()
    if mode == "preview":
        return _guard(lambda g: preview_mod.preview(g, source, from_, to, operator=operator, reason=reason))
    def go(g):
        res = cascade.distrust(g, source, from_, to, mode="commit", operator=operator, reason=reason)
        # The Remediator wakes on every retraction and drafts compensations (nothing is sent yet).
        res["remediations"] = remediator.remediate(g, res["retraction_id"])
        return res
    return _guard(go)


def reinstate(retraction_id: str):
    """Reverse a retraction exactly. Returns {restored_count}."""
    return _guard(lambda g: cascade.reinstate(g, retraction_id))


def why(node_id: str, max_depth: int = 12):
    """Justification tree for a memory node: its status, each justification (an AND of premises),
    and recursively every premise down to the observations and their sources."""
    return _guard(lambda g: _why(g, node_id, max_depth))


def recall_list(run: str | None = None):
    """Executed actions that lost support, largest amount first. `run` is a retraction id; omit it
    for all active (not reinstated) retractions."""
    def go(g):
        if run is None:
            ids = [r[0] for r in g.query(
                "MATCH (r:Retraction {reinstated:false}) RETURN r.id ORDER BY r.id").result_set]
        else:
            if not g.query("MATCH (r:Retraction {id:$id}) RETURN r.id", {"id": run}).result_set:
                raise RetconError("NOT_FOUND", f"retraction {run!r}", {"retraction_id": run})
            ids = [run]
        seen, out = set(), []
        for rid in ids:
            for a in _recall_list(g, rid):
                if a["action_id"] not in seen:
                    seen.add(a["action_id"])
                    out.append({**a, "retraction_id": rid})
        return sorted(out, key=lambda a: -(a["amount"] or 0))
    return _guard(go)


def list_remediations(status: str | None = None):
    """Drafted compensations (bank recalls, correction emails), largest amount first.
    `status` filters: draft | approved | executed | rejected | withdrawn."""
    return _guard(lambda g: remediator.list_remediations(g, status))


def approve_remediation(remediation_id: str, operator: str = "mcp"):
    """One human click: carry out the drafted compensation."""
    return _guard(lambda g: remediator.approve(g, remediation_id, operator, _executor))


def reject_remediation(remediation_id: str, operator: str = "mcp"):
    """Discard a drafted compensation."""
    return _guard(lambda g: remediator.reject(g, remediation_id, operator))
