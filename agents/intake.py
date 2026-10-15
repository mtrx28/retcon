"""Intake agent policy (task B3): reads sources, writes observations and the beliefs extracted from them.

Task:  {"type": "ingest", "source", "text", "observed_at", "vendor", "vendor_id"}
Tools: observe -> remember. The observation lands in Intake's context, so the belief is justified by
it automatically (agents never name parents). Hands bank changes and invoices to the Analyst.
"""
from agents.common import call, extract, failed


def policy(task, params):
    yield call("begin_turn")
    obs = yield call("observe", source=task["source"], text=task["text"], observed_at=task["observed_at"])
    if failed(obs):
        return {"summary": f"observe failed: {obs['error']['code']}"}
    ex = extract(task["text"])
    if ex is None:
        return {"summary": "observed; nothing to believe", "data": {"observation_id": obs["node_id"]}}
    outbox = []
    belief_id = None
    if ex["belief"]:
        args = {"text": ex["belief"], "kind": "belief"}
        if ex.get("mtype"):
            args["mtype"] = ex["mtype"]
        res = yield call("remember", **args)
        if failed(res):
            return {"summary": f"remember failed: {res['error']['code']}"}
        belief_id = res["node_id"]
        if ex["topic"] == "bank_change":
            outbox.append(("analyst", {"type": "review_bank_change", "belief_id": belief_id,
                                       "belief_text": ex["belief"], "iban": ex["iban"],
                                       "vendor": task.get("vendor"), "vendor_id": task.get("vendor_id")}))
    if ex["topic"] == "invoice":
        outbox.append(("analyst", {"type": "match_invoice", "invoice": ex["invoice"], "amount": ex["amount"],
                                   "invoice_text": task["text"], "vendor": task.get("vendor"),
                                   "vendor_id": task.get("vendor_id")}))
    return {"summary": f"observed and extracted {ex['topic']}", "outbox": outbox,
            "data": {"observation_id": obs["node_id"], "belief_id": belief_id}}
