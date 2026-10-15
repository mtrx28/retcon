"""Q6: executed actions that lost support, and pending actions that are now blocked."""


def recall_list(g, retraction_id: str) -> list[dict]:
    """Executed actions flipped OUT by this retraction, largest amount first."""
    rows = g.query(
        "MATCH (:Retraction {id:$rid})-[:RETRACTED]->(act:Action) "
        "WHERE act.executed = true "
        "OPTIONAL MATCH (ag:Agent)-[:HOLDS]->(act) "
        "RETURN act.id, act.tool, act.amount, act.executed_at, ag.id "
        "ORDER BY coalesce(act.amount, 0) DESC, act.executed_at",
        {"rid": retraction_id}).result_set
    return [{"action_id": r[0], "tool": r[1], "amount": r[2], "executed_at": r[3], "agent": r[4]}
            for r in rows]


def blocked_actions(g, retraction_id: str) -> list[str]:
    """Pending (not executed) actions flipped OUT by this retraction."""
    rows = g.query(
        "MATCH (:Retraction {id:$rid})-[:RETRACTED]->(act:Action) "
        "WHERE act.executed = false RETURN act.id ORDER BY coalesce(act.amount, 0) DESC",
        {"rid": retraction_id}).result_set
    return [r[0] for r in rows]
