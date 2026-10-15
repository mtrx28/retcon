"""Payments agent policy (task B3 + B3+).

pay_invoice        recall the match belief and the vendor's bank account -> write a plan -> call
                   `fragility` and `why` on it. Over the policy amount with poisoning cost below the
                   minimum, it chooses *not* to pay and asks Comms for callback verification;
                   otherwise it calls the gated `act(pay)`. (B3+: the graph decides, via MCP tools.)
retraction_event   the agent's plans lost support. Re-plans every pending one from surviving memory:
                   only IN beliefs are recalled, so the account is the verified one. A plan whose
                   payment already executed is left to the Remediator (recall list), never re-paid.
"""
from agents.common import call, choose_iban, failed, ok_list


def _pay(task, params, replan=False):
    vendor, invoice, amount = task["vendor"], task["invoice"], task["amount"]
    yield call("begin_turn")
    yield call("recall", query=task["match_text"], k=1)
    bank = ok_list((yield call("recall", query=f"{vendor} bank account IBAN", k=4, contains=vendor)))
    iban = choose_iban(bank)
    if iban is None:
        return {"summary": f"{invoice}: no bank account on record, not planned", "data": {"decision": "none"}}

    plan_text = f"Pay {invoice} {amount} USD to {iban}."
    plan = yield call("remember", text=plan_text, kind="plan")
    if failed(plan):
        return {"summary": f"{invoice}: plan failed {plan['error']['code']}", "data": {"decision": "error"}}
    yield call("recall", query=plan_text, k=1)  # the plan enters context: the action rests on it
    frag = yield call("fragility", node_id=plan["node_id"])
    yield call("why", node_id=plan["node_id"], max_depth=6)
    cost = None if failed(frag) else frag.get("independent_sources")

    rule = params.get("pay_rule")  # None: no self-check, the gate alone decides
    entry = {"plan_id": plan["node_id"], "invoice": invoice, "amount": amount, "vendor": vendor,
             "vendor_id": task.get("vendor_id"), "match_text": task["match_text"], "iban": iban,
             "cost": cost, "executed": False}
    if rule and cost is not None and amount > rule["over_amount"] and cost < rule["min"]:
        note = (f"Payment of {invoice} is on hold: it rests on {cost} independent source(s), "
                f"callback verification requested.")
        yield call("remember", text=note, kind="belief")
        entry["decision"] = "verify"
        return {"summary": f"{invoice}: cost {cost} < {rule['min']}, verification requested"
                           + (" (re-planned)" if replan else ""),
                "ledger": entry,
                "outbox": [("comms", {"type": "request_verification", "plan_text": plan_text,
                                      "invoice": invoice, "amount": amount, "iban": iban, "vendor": vendor,
                                      "vendor_id": task.get("vendor_id"), "cut_set": frag.get("cut_set")})]}

    res = yield call("act", tool="pay", args={"vendor": task.get("vendor_id"), "iban": iban, "amount": amount,
                                              "invoice": invoice, "idempotency_key": plan["node_id"]})
    if failed(res) or not res.get("executed"):
        entry["decision"] = "blocked"
        entry["blocked"] = res
        return {"summary": f"{invoice}: gate blocked the payment", "ledger": entry}
    entry.update(decision="paid", executed=True, action_id=res["action_id"])
    return {"summary": f"{invoice}: paid {amount} to {iban}", "ledger": entry}


def policy(task, params):
    if task["type"] == "pay_invoice":
        return (yield from _pay(task, params))

    if task["type"] == "retraction_event":
        outbox, ledgers, notes = [], [], []
        for plan in task["plans"]:
            if plan.get("executed"):
                notes.append(f"{plan['invoice']}: already paid on a retracted belief; left to the Remediator")
                continue
            sub = yield from _pay({**plan, "type": "pay_invoice"}, params, replan=True)
            notes.append(sub["summary"])
            outbox += sub.get("outbox", [])
            if sub.get("ledger"):
                ledgers.append({**sub["ledger"], "replaces": plan["plan_id"]})
        return {"summary": "; ".join(notes) or "no pending plans to re-plan", "outbox": outbox,
                "ledgers": ledgers}
    return {"summary": f"payments has no policy for task {task['type']!r}"}
