"""Action service (task A4): `act(tool, args, agent)` with the gate behind it.

An action is a justified :Action node (same shape as Q1 beliefs): its premises are everything the
agent had in context, captured automatically, so a retraction reaches it through the cascade like
any other memory. `act` writes the node, asks the gate, and only then calls the executor.

    act -> {executed: bool, action_id, blocked_reason?: gate decision, result?: executor output}
"""
import hashlib
import json
import time

from core.errors import RetconError
from core.write.q1 import FLOW_CAP, ensure_agent
from gate import gate as gate_mod


def _digest(*parts):
    return hashlib.sha1("\x1f".join(parts).encode("utf8")).hexdigest()[:12]


class ActionService:
    def __init__(self, graph, capture, executor=None, fragility_fn=None):
        self.g, self.capture = graph, capture
        self.executor, self.fragility_fn = executor, fragility_fn

    # -- write -----------------------------------------------------------------------------
    def propose(self, tool, args, agent):
        """Write the Action node justified by the agent's captured context. Idempotent."""
        if not isinstance(args, dict):
            raise RetconError("INVALID_ARGUMENT", "args must be an object", {"args": args})
        premises = sorted(set(self.capture.context(agent)))
        if not premises:
            raise RetconError("INVALID_ARGUMENT",
                              "no premises: recall something first, so the action has a justification",
                              {"agent": agent})
        found = {r[0] for r in self.g.query("MATCH (p:Mem) WHERE p.id IN $ids RETURN p.id",
                                            {"ids": premises}).result_set}
        missing = [p for p in premises if p not in found]
        if missing:
            raise RetconError("NOT_FOUND", f"unknown premise ids: {missing}", {"missing_ids": missing})

        canon = json.dumps(args, sort_keys=True, default=str)
        aid = "act_" + _digest(tool, canon, agent, *premises)
        jid = "j_" + _digest(aid, *premises)
        amount = args.get("amount") if isinstance(args.get("amount"), (int, float)) else None
        ensure_agent(self.g, agent)
        self.g.query(
            "MATCH (a:Agent {id:$agent}) MATCH (p:Mem) WHERE p.id IN $premises "
            "WITH a, collect(p) AS ps, all(x IN collect(p) WHERE x.status = 'IN') AS live "
            "MERGE (m:Mem:Action {id:$aid}) "
            "ON CREATE SET m.tool=$tool, m.amount=$amount, m.args=$args, m.executed=false, "
            "              m.text=$text, m.agent=$agent, m.created_at=$now, "
            "              m.status = CASE WHEN live THEN 'IN' ELSE 'OUT' END "
            "MERGE (j:Justification {id:$jid}) ON CREATE SET j.rule='combine', j.agent=$agent, j.at=$now "
            "MERGE (j)-[:JUSTIFIES]->(m) MERGE (a)-[:HOLDS]->(m) "
            "WITH m, j, ps UNWIND ps AS p "
            "MERGE (p)-[:PREMISE_OF]->(j) "
            "MERGE (p)-[f:FLOW]->(m) SET f.cap = $cap "
            "MERGE (m)-[:DEPENDS_ON]->(p)",
            {"agent": agent, "premises": premises, "aid": aid, "jid": jid, "tool": tool,
             "amount": amount, "args": canon, "text": f"{tool} {canon}", "now": int(time.time()),
             "cap": FLOW_CAP})
        return aid

    # -- decide + execute --------------------------------------------------------------------
    def execute(self, action_id):
        row = self.g.query("MATCH (a:Mem:Action {id:$id}) RETURN a.tool, a.args, a.executed",
                           {"id": action_id}).result_set
        if not row:
            raise RetconError("NOT_FOUND", f"action {action_id!r}", {"action_id": action_id})
        tool, args_json, executed = row[0]
        if executed:
            return {"executed": True, "action_id": action_id, "already_executed": True}

        decision = gate_mod.check(self.g, action_id, self.fragility_fn)
        if not decision["allowed"]:
            self.g.query("MATCH (a:Mem:Action {id:$id}) SET a.gate_state = 'blocked', a.blocked_reason = $r",
                         {"id": action_id, "r": json.dumps(decision, default=str)})
            return {"executed": False, "action_id": action_id, "blocked_reason": decision}
        if self.executor is None:
            return {"executed": False, "action_id": action_id, "warnings": ["no executor configured"],
                    "blocked_reason": None}
        try:
            result = self.executor.execute(tool, json.loads(args_json or "{}"))
        except Exception as e:  # noqa: BLE001 - executor failures are reported, not raised
            return {"executed": False, "action_id": action_id,
                    "blocked_reason": {"allowed": True, "code": "EXECUTION_FAILED", "reason": str(e),
                                       "details": {}, "warnings": decision["warnings"]}}
        self.g.query("MATCH (a:Mem:Action {id:$id}) "
                     "SET a.executed = true, a.executed_at = $now, a.gate_state = 'released', "
                     "    a.result = $res, a.blocked_reason = null",
                     {"id": action_id, "now": int(time.time()), "res": json.dumps(result, default=str)})
        return {"executed": True, "action_id": action_id, "result": result,
                "warnings": decision["warnings"]}

    def act(self, tool, args, agent):
        return self.execute(self.propose(tool, args, agent))

    def pending(self):
        """Pending (not executed) actions with their current gate decision, for dashboards."""
        ids = [r[0] for r in self.g.query(
            "MATCH (a:Mem:Action {executed:false}) RETURN a.id ORDER BY coalesce(a.amount, 0) DESC").result_set]
        return [{"action_id": i, **gate_mod.check(self.g, i, self.fragility_fn)} for i in ids]
