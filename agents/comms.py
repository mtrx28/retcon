"""Comms agent policy (task B3): vendor-facing messages.

confirm_vendor_bank    restates the Analyst's note as a vendor confirmation. This is the third hop of a
                       claim being laundered through agents; the graph still traces it to its source.
request_verification   emails the vendor (through the gated `act`) asking for a callback to the number
                       on the signed contract. Justified by the plan and the contract bank belief, so a
                       retraction of the plan reaches the email and the Remediator can draft a correction.
"""
from agents.common import call, failed, ok_list


def policy(task, params):
    yield call("begin_turn")
    if task["type"] == "confirm_vendor_bank":
        hits = ok_list((yield call("recall", query=task["note_text"], k=1)))
        if not hits:
            return {"summary": "note no longer in memory"}
        res = yield call("remember", text=f"Comms note: vendor confirmed new bank {task['iban']}.", kind="belief")
        return {"summary": "vendor bank confirmation recorded",
                "data": {} if failed(res) else {"belief_id": res["node_id"]}}

    if task["type"] == "request_verification":
        yield call("recall", query=task["plan_text"], k=1)
        yield call("recall", query=f"Contract bank for {task['vendor']}", k=1, contains=task["vendor"])
        weak = ", ".join(task.get("cut_set") or []) or "one source"
        body = (f"We received an instruction to pay {task['invoice']} ({task['amount']} USD) to account "
                f"{task['iban']}. That instruction can be voided by a single source failing ({weak}). "
                f"Before paying we need you to confirm the account by calling the number on your signed "
                f"contract.")
        res = yield call("act", tool="email", args={
            "to": f"ar@{task['vendor_id']}.example.test", "subject": f"Callback verification: {task['invoice']}",
            "body": body})
        if failed(res) or not res.get("executed"):
            return {"summary": "verification request not sent", "data": {"blocked": res}}
        return {"summary": "verification request sent", "data": {"action_id": res["action_id"]}}
    return {"summary": f"comms has no policy for task {task['type']!r}"}
