"""Analyst agent policy (task B3): cross-checks what Intake believes and derives conclusions.

review_bank_change  recall Intake's belief -> remember an analyst note (a `handoff` justification,
                    because the only premise was written by another agent) -> Comms.
match_invoice       recall the invoice and the open purchase orders -> remember "matches an open PO"
                    (an AND of two sources) -> Payments.
"""
from agents.common import call, failed, ok_list


def policy(task, params):
    yield call("begin_turn")
    if task["type"] == "review_bank_change":
        hits = ok_list((yield call("recall", query=task["belief_text"], k=1)))
        if not hits:
            return {"summary": "belief no longer in memory; nothing to review"}
        note = f"Analyst note: vendor bank updated to {task['iban']}."
        res = yield call("remember", text=note, kind="belief")
        if failed(res):
            return {"summary": f"remember failed: {res['error']['code']}"}
        return {"summary": "bank change reviewed",
                "outbox": [("comms", {"type": "confirm_vendor_bank", "note_text": note, "iban": task["iban"],
                                      "vendor": task.get("vendor"), "vendor_id": task.get("vendor_id")})],
                "data": {"belief_id": res["node_id"]}}

    if task["type"] == "match_invoice":
        inv = ok_list((yield call("recall", query=task["invoice_text"], k=1)))
        po = ok_list((yield call("recall", query=f"Purchase orders open for {task['vendor']}", k=1,
                                 contains=task["vendor"])))
        if not inv or not po or not po[0]["text"].startswith("Purchase orders"):
            return {"summary": "no open purchase order on record; invoice not matched"}
        match = f"{task['invoice']} ({task['amount']} USD) matches an open PO."
        res = yield call("remember", text=match, kind="belief")
        if failed(res):
            return {"summary": f"remember failed: {res['error']['code']}"}
        return {"summary": "invoice matched",
                "outbox": [("payments", {"type": "pay_invoice", "invoice": task["invoice"],
                                         "amount": task["amount"], "match_text": match,
                                         "vendor": task.get("vendor"), "vendor_id": task.get("vendor_id")})],
                "data": {"belief_id": res["node_id"]}}
    return {"summary": f"analyst has no policy for task {task['type']!r}"}
