"""Retraction events (CONTRACT section 6), derived from the graph.

The cascade records which nodes a retraction flipped (`RETRACTED {flipped}`), and agents are linked
to what they hold (`HOLDS`, written on authorship and on every recall). An event goes to each agent
holding a flipped belief, listing that agent's plans (and, additively, executed actions) the flip
invalidated downstream:

    {"retraction_id", "agent", "belief_id", "reason", "invalidated_plan_ids": [...],
     "invalidated_action_ids": [...]}      # last key is additive
"""


def retraction_events(g, retraction_id):
    row = g.query("MATCH (r:Retraction {id:$id}) RETURN r.reason", {"id": retraction_id}).result_set
    if not row:
        return []
    reason = row[0][0]
    holders = g.query(
        "MATCH (:Retraction {id:$id})-[e:RETRACTED]->(b:Belief) WHERE e.flipped = true "
        "MATCH (a:Agent)-[:HOLDS]->(b) RETURN b.id, a.id ORDER BY b.id, a.id", {"id": retraction_id}).result_set
    belief_ids = sorted({b for b, _ in holders})
    downstream = {}
    for b in belief_ids:
        rows = g.query(
            "MATCH (:Mem {id:$b})-[:PREMISE_OF|JUSTIFIES*1..40]->(x:Mem)<-[:RETRACTED]-(:Retraction {id:$id}) "
            "WHERE x:Plan OR x:Action RETURN DISTINCT x.id, x.agent, labels(x) ORDER BY x.id",
            {"b": b, "id": retraction_id}).result_set
        downstream[b] = rows
    events = []
    for b, agent in holders:
        plans = [x for x, who, lab in downstream[b] if who == agent and "Plan" in lab]
        actions = [x for x, who, lab in downstream[b] if who == agent and "Action" in lab]
        events.append({"retraction_id": retraction_id, "agent": agent, "belief_id": b, "reason": reason,
                       "invalidated_plan_ids": plans, "invalidated_action_ids": actions})
    return events
