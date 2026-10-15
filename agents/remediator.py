"""Remediator (task A4): wakes on a retraction and drafts the compensating action for every action
that already executed on a retracted belief. Nothing is sent without a human approval.

Deterministic templates, no LLM: the graph decides what needs compensating; an optional `phrase`
callable may reword the text. Drafts are :Remediation nodes:

  (Retraction)-[:TRIGGERED]->(Remediation)-[:COMPENSATES]->(Action)
  Remediation {id, kind, status draft|approved|executed|rejected|withdrawn|failed, title, payload(JSON),
               amount, reason, created_at, ...}

kind: bank_recall (pay) | correction_email (email/notify) | manual_review (anything else).
A draft whose action regains support (retraction reinstated) is withdrawn automatically.
"""
import hashlib
import json
import time

from core.errors import RetconError
from core.recall.recall_list import recall_list


def _rid(action_id, kind):
    return "rem_" + hashlib.sha1(f"{action_id}|{kind}".encode()).hexdigest()[:12]


def _kind_for(tool):
    return {"pay": "bank_recall", "email": "correction_email", "notify": "correction_email"}.get(
        tool, "manual_review")


def _draft(a, args, result, retraction_reason):
    kind = _kind_for(a["tool"])
    why = f"Executed on a retracted belief. {retraction_reason}".strip()
    if kind == "bank_recall":
        pid = (result or {}).get("payment_id")
        return kind, {
            "title": f"Recall payment of {a['amount']} ({a['action_id']})",
            "payload": {"method": "POST", "path": f"/bank/payments/{pid}/recall" if pid else None,
                        "payment_id": pid, "amount": a["amount"], "vendor": args.get("vendor"),
                        "reason": why,
                        "note": None if pid else "payment id not recorded for this action; recall by hand"}}
    if kind == "correction_email":
        return kind, {
            "title": f"Send correction for {a['action_id']}",
            "payload": {"to": args.get("to"), "subject": f"Correction: {args.get('subject', 'earlier message')}",
                        "body": f"Please disregard our earlier message. {why}"}}
    return kind, {"title": f"Review {a['tool']} action {a['action_id']}",
                  "payload": {"action_id": a["action_id"], "tool": a["tool"], "args": args, "reason": why}}


def remediate(g, retraction_id, phrase=None):
    """Create (or refresh) drafts for every executed action flipped by this retraction."""
    ret = g.query("MATCH (r:Retraction {id:$id}) RETURN r.reason", {"id": retraction_id}).result_set
    if not ret:
        raise RetconError("NOT_FOUND", f"retraction {retraction_id!r}", {"retraction_id": retraction_id})
    reason = ret[0][0] or ""
    now = int(time.time())
    out = []
    for a in recall_list(g, retraction_id):
        meta = g.query("MATCH (x:Mem:Action {id:$id}) RETURN x.args, x.result",
                       {"id": a["action_id"]}).result_set[0]
        args = json.loads(meta[0]) if meta[0] else {}
        result = json.loads(meta[1]) if meta[1] else {}
        kind, d = _draft(a, args, result, reason)
        if phrase:
            d["title"] = phrase(d["title"])
        rem_id = _rid(a["action_id"], kind)
        g.query(
            "MATCH (r:Retraction {id:$rid}), (x:Mem:Action {id:$aid}) "
            "MERGE (m:Remediation {id:$id}) "
            "ON CREATE SET m.kind=$kind, m.status='draft', m.title=$title, m.payload=$payload, "
            "              m.amount=$amount, m.reason=$reason, m.created_at=$now, m.retraction_id=$rid "
            "MERGE (r)-[:TRIGGERED]->(m) MERGE (m)-[:COMPENSATES]->(x) "
            "SET m.status = CASE WHEN m.status = 'withdrawn' THEN 'draft' ELSE m.status END",
            {"rid": retraction_id, "aid": a["action_id"], "id": rem_id, "kind": kind, "title": d["title"],
             "payload": json.dumps(d["payload"], default=str), "amount": a["amount"],
             "reason": reason, "now": now})
        out.append(rem_id)
    withdraw_stale(g)
    return [get(g, i) for i in out]


def withdraw_stale(g):
    """Drafts whose action is IN again (retraction reinstated) are no longer needed."""
    g.query("MATCH (m:Remediation {status:'draft'})-[:COMPENSATES]->(x:Mem:Action {status:'IN'}) "
            "SET m.status = 'withdrawn'")


_FIELDS = ("id", "kind", "status", "title", "payload", "amount", "reason", "retraction_id",
           "approved_by", "approved_at", "result", "error")


def _row_to_dict(row, action_id):
    d = dict(zip(_FIELDS, row))
    for k in ("payload", "result"):
        d[k] = json.loads(d[k]) if d[k] else None
    d["action_id"] = action_id
    return d


def get(g, rem_id):
    rows = g.query("MATCH (m:Remediation {id:$id}) OPTIONAL MATCH (m)-[:COMPENSATES]->(x:Mem) "
                   "RETURN m.id, m.kind, m.status, m.title, m.payload, m.amount, m.reason, "
                   "       m.retraction_id, m.approved_by, m.approved_at, m.result, m.error, x.id",
                   {"id": rem_id}).result_set
    if not rows:
        raise RetconError("NOT_FOUND", f"remediation {rem_id!r}", {"remediation_id": rem_id})
    return _row_to_dict(rows[0][:-1], rows[0][-1])


def list_remediations(g, status=None):
    withdraw_stale(g)
    rows = g.query("MATCH (m:Remediation) WHERE $st IS NULL OR m.status = $st "
                   "OPTIONAL MATCH (m)-[:COMPENSATES]->(x:Mem) "
                   "RETURN m.id, m.kind, m.status, m.title, m.payload, m.amount, m.reason, "
                   "       m.retraction_id, m.approved_by, m.approved_at, m.result, m.error, x.id "
                   "ORDER BY coalesce(m.amount, 0) DESC, m.id", {"st": status}).result_set
    return [_row_to_dict(r[:-1], r[-1]) for r in rows]


def approve(g, rem_id, operator, executor=None):
    """One human click. Executes the compensation if an executor is configured; otherwise records
    the approval and leaves it for whoever runs the executor."""
    withdraw_stale(g)
    cur = get(g, rem_id)
    if cur["status"] != "draft":
        raise RetconError("INVALID_ARGUMENT", f"remediation is {cur['status']}, not a draft",
                          {"remediation_id": rem_id, "status": cur["status"]})
    now = int(time.time())
    if executor is None:
        g.query("MATCH (m:Remediation {id:$id}) SET m.status='approved', m.approved_by=$op, m.approved_at=$now",
                {"id": rem_id, "op": operator, "now": now})
        return get(g, rem_id)
    try:
        res = executor.compensate(cur["kind"], cur["payload"])
    except Exception as e:  # noqa: BLE001
        g.query("MATCH (m:Remediation {id:$id}) SET m.error=$err", {"id": rem_id, "err": str(e)})
        raise RetconError("EXECUTION_FAILED", str(e), {"remediation_id": rem_id}) from None
    g.query("MATCH (m:Remediation {id:$id}) SET m.status='executed', m.approved_by=$op, "
            "m.approved_at=$now, m.result=$res, m.error=null",
            {"id": rem_id, "op": operator, "now": now, "res": json.dumps(res, default=str)})
    return get(g, rem_id)


def reject(g, rem_id, operator):
    cur = get(g, rem_id)
    if cur["status"] != "draft":
        raise RetconError("INVALID_ARGUMENT", f"remediation is {cur['status']}, not a draft",
                          {"remediation_id": rem_id, "status": cur["status"]})
    g.query("MATCH (m:Remediation {id:$id}) SET m.status='rejected', m.approved_by=$op, m.approved_at=$now",
            {"id": rem_id, "op": operator, "now": int(time.time())})
    return get(g, rem_id)
