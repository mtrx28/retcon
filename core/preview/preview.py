"""Counterfactual preview (task A5): run the retraction on a GRAPH.COPY fork and show the diff.

    preview(g, source, from, to) -> same payload as `distrust` (mode commit) plus
        mode="preview", preview=True, diff=[{id, kind, from, to, hop}]

The live graph is never written: not a node, not a Retraction, not a Remediation. The fork is
deleted whatever happens. `retraction_id` is the id a commit would receive right now, and
`remediations` are the drafts a commit would create (ids are content-derived, so they match).
"""
from agents import remediator
from core.errors import RetconError
from core.retract import cascade

KIND = {"Observation": "observation", "Belief": "belief", "Plan": "plan", "Action": "action"}


def _drop(client, name):
    try:
        client.select_graph(name).delete()
    except Exception:  # noqa: BLE001 - nothing to drop
        pass


def preview(g, source: str, t_from, t_to, operator: str = "preview", reason: str | None = None) -> dict:
    predicted = cascade._next_retraction_id(g)
    fork_name = f"{g.name}_preview_{predicted}"
    _drop(g.client, fork_name)
    try:
        fork = g.copy(fork_name)                       # GRAPH.COPY
    except Exception as e:  # noqa: BLE001
        raise RetconError("PREVIEW_FAILED", f"could not fork graph: {e}", {"graph": g.name}) from None
    try:
        res = cascade.distrust(fork, source, t_from, t_to, mode="commit", operator=operator, reason=reason)
        res["remediations"] = remediator.remediate(fork, res["retraction_id"])
        kinds = {r[0]: r[1] for r in fork.query(
            "MATCH (x:Mem) WHERE x.id IN $ids RETURN x.id, labels(x)", {"ids": res["flipped_ids"]}).result_set}
        hop_of = {i: h for h, ids in res["hops"].items() for i in ids}
        res["diff"] = [{"id": i, "kind": next((KIND[k] for k in kinds.get(i, []) if k in KIND), "mem"),
                        "from": "IN", "to": "OUT", "hop": hop_of.get(i, 0)} for i in res["flipped_ids"]]
    finally:
        _drop(g.client, fork_name)
    res["mode"], res["preview"] = "preview", True
    res["retraction_id"] = predicted
    return res
