"""Action gate (task A4): decides whether an action may execute, from the graph.

An action is allowed iff
  1. every premise of its justification is IN (the cascade flips an action OUT when support is lost), and
  2. the tool's policy is met: above the amount threshold, enough independent sources
     (`fragility_fn(action_id)` returns {"independent_sources": n}; Lane B's min-cut).

Decisions are plain dicts so the MCP layer, the Remediator and the UI all show the same reason.
"""
from gate.policy import policy_for

BLOCKED = "BLOCKED_BY_POLICY"  # contract error code


def _action(g, action_id):
    rows = g.query("MATCH (a:Mem:Action {id:$id}) RETURN a.status, a.tool, a.amount, a.executed",
                   {"id": action_id}).result_set
    if not rows:
        return None
    status, tool, amount, executed = rows[0]
    return {"id": action_id, "status": status, "tool": tool, "amount": amount, "executed": bool(executed)}


def retraction_reasons(g, node_ids):
    """Active retractions that flipped any of node_ids: {node_id: [(retraction_id, reason)]}."""
    out = {}
    for rid, reason, nid in g.query(
            "MATCH (r:Retraction {reinstated:false})-[:RETRACTED]->(n:Mem) WHERE n.id IN $ids "
            "RETURN r.id, r.reason, n.id ORDER BY r.id", {"ids": list(node_ids)}).result_set:
        out.setdefault(nid, []).append((rid, reason))
    return out


def check(g, action_id: str, fragility_fn=None) -> dict:
    """Gate decision: {allowed, code, reason, details, warnings}."""
    a = _action(g, action_id)
    if a is None:
        return {"allowed": False, "code": "NOT_FOUND", "reason": f"unknown action {action_id!r}",
                "details": {"action_id": action_id}, "warnings": []}
    warnings = []

    premises = g.query(
        "MATCH (p:Mem)-[:PREMISE_OF]->(:Justification)-[:JUSTIFIES]->(:Mem {id:$id}) "
        "RETURN DISTINCT p.id, p.status", {"id": action_id}).result_set
    out_premises = sorted(pid for pid, st in premises if st != "IN")
    if a["status"] != "IN" or out_premises:
        why = retraction_reasons(g, out_premises + [action_id])
        rids = sorted({r for pairs in why.values() for r, _ in pairs})
        reasons = sorted({txt for pairs in why.values() for _, txt in pairs if txt})
        text = "support was retracted"
        if out_premises:
            text = f"premise(s) {out_premises} are OUT"
        if rids:
            text += f" (retraction {', '.join(rids)}: {'; '.join(reasons)})"
        return {"allowed": False, "code": BLOCKED, "reason": text, "warnings": warnings,
                "details": {"reason_code": "PREMISE_RETRACTED", "action_id": action_id,
                            "out_premise_ids": out_premises, "retraction_ids": rids}}

    rule = policy_for(a["tool"]).get("independent_sources")
    if rule and a["amount"] is not None and a["amount"] > rule["over_amount"]:
        if fragility_fn is None:
            warnings.append("fragility unavailable: independent-source rule not enforced")
        else:
            res = fragility_fn(action_id) or {}
            if "error" in res:
                warnings.append(f"fragility error: {res['error'].get('message')}")
            else:
                n = res.get("independent_sources")
                if n is not None and n < rule["min"]:
                    return {"allowed": False, "code": BLOCKED, "warnings": warnings,
                            "reason": (f"{a['tool']} of {a['amount']} rests on {n} independent source(s); "
                                       f"policy needs at least {rule['min']} above {rule['over_amount']}"),
                            "details": {"reason_code": "INSUFFICIENT_INDEPENDENT_SOURCES",
                                        "action_id": action_id, "independent_sources": n,
                                        "required": rule["min"], "bound": res.get("bound")}}
    return {"allowed": True, "code": None, "reason": "all premises IN, policy met",
            "details": {"action_id": action_id}, "warnings": warnings}
