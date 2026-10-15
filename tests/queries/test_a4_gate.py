"""A4 acceptance: gate blocks the pending payment with a reason, the executed payment is on the
recall list ranked by amount, and a draft compensation awaits approval (nothing sent until a human
approves)."""
import asyncio
import copy
import json
from pathlib import Path

import pytest
from mcp.client.client import Client

from agents import remediator
from core.actions import ActionService
from core.retract.cascade import distrust, reinstate
from core.write.capture import PremiseCapture
from data.bank import MockBank
from data.inbox import SandboxInbox
from data.load_fixture import load
from gate.executors import SandboxExecutor
from mcp_server import tools_retract
from mcp_server.server import build

pytestmark = pytest.mark.a4

ROOT = Path(__file__).resolve().parents[2]
BASE = json.loads((ROOT / "data" / "fixtures" / "ap_tiny.json").read_text(encoding="utf8"))
W = BASE["window"]


def spec_with_extra_actions():
    s = copy.deepcopy(BASE)
    s["actions"] += [
        {"id": "act_pay_3", "tool": "pay", "agent": "payments", "amount": 5000, "executed": True,
         "executed_at": "2026-10-08T09:00:00Z", "premises": ["plan_pay_1"]},          # tainted, smaller
        {"id": "act_pay_4", "tool": "pay", "agent": "payments", "amount": 91000, "executed": True,
         "executed_at": "2026-10-08T10:00:00Z", "premises": ["b_inv1_ok"]},           # clean, biggest
        {"id": "act_mail_1", "tool": "email", "agent": "comms", "amount": 0, "executed": True,
         "executed_at": "2026-10-08T11:00:00Z", "premises": ["b_bank_echo_comms"]},   # tainted email
    ]
    return s


class Recorder:
    """Executor that records calls so tests can prove nothing left the building."""

    def __init__(self):
        self.executed, self.compensated = [], []

    def execute(self, tool, args):
        self.executed.append((tool, args))
        return {"payment_id": f"rec_{len(self.executed)}"}

    def compensate(self, kind, payload):
        self.compensated.append((kind, payload))
        return {"ok": True}


@pytest.fixture()
def g():
    return load(spec_with_extra_actions(), graph_name="a4_gate")


def do_distrust(g):
    return distrust(g, W["source"], W["from"], W["to"])


def test_pending_payment_is_blocked_with_a_reason(g):
    ex = Recorder()
    svc = ActionService(g, PremiseCapture(), executor=ex)
    do_distrust(g)
    out = svc.execute("act_pay_2")
    assert out["executed"] is False
    r = out["blocked_reason"]
    assert r["code"] == "BLOCKED_BY_POLICY"
    assert r["details"]["reason_code"] == "PREMISE_RETRACTED"
    assert r["details"]["out_premise_ids"] == ["plan_pay_2"]
    assert r["details"]["retraction_ids"] == ["ret_0001"]
    assert "coastal-portal" in r["reason"]
    assert ex.executed == []  # blocked means it never reached the executor


def test_recall_list_is_ranked_by_amount_and_excludes_clean_actions(g):
    res = do_distrust(g)
    assert [a["action_id"] for a in res["recall_list"]] == ["act_pay_1", "act_pay_3", "act_mail_1"]
    assert [a["amount"] for a in res["recall_list"]] == [18400, 5000, 0]
    assert "act_pay_4" not in {a["action_id"] for a in res["recall_list"]}  # independent support
    assert res["blocked_action_ids"] == ["act_pay_2"]


def test_drafts_await_approval_and_nothing_is_sent(g):
    ex = Recorder()
    tools_retract.configure(g, ex)
    res = tools_retract.distrust(W["source"], W["from"], W["to"])
    drafts = res["remediations"]
    assert [(d["action_id"], d["kind"], d["status"]) for d in drafts] == [
        ("act_pay_1", "bank_recall", "draft"),
        ("act_pay_3", "bank_recall", "draft"),
        ("act_mail_1", "correction_email", "draft")]
    assert drafts[0]["amount"] == 18400 and "retracted" in drafts[0]["payload"]["reason"]
    assert drafts[0]["retraction_id"] == res["retraction_id"]
    assert ex.executed == [] and ex.compensated == []
    # Same retraction again is idempotent: same drafts, same ids.
    again = remediator.remediate(g, res["retraction_id"])
    assert [d["id"] for d in again] == [d["id"] for d in drafts]


def test_full_loop_pay_retract_recall_through_the_bank(g):
    bank, inbox = MockBank({"coastal": "IBAN-ON-FILE"}), SandboxInbox()
    capture = PremiseCapture()
    svc = ActionService(g, capture, executor=SandboxExecutor(bank, inbox))
    capture.record("payments", ["b_inv1_ok", "b_bank_echo_analyst"])  # the agent recalled these
    paid = svc.act("pay", {"vendor": "coastal", "iban": "IBAN-FRAUD", "amount": 7000,
                           "invoice": "INV-1001"}, "payments")
    assert paid["executed"] and paid["result"]["payment_id"] == "pay_0001"
    assert bank.get("pay_0001")["status"] == "executed"

    tools_retract.configure(g, SandboxExecutor(bank, inbox))
    res = tools_retract.distrust(W["source"], W["from"], W["to"])
    mine = next(d for d in res["remediations"] if d["payload"].get("payment_id") == "pay_0001")
    assert mine["kind"] == "bank_recall" and mine["payload"]["path"] == "/bank/payments/pay_0001/recall"

    done = tools_retract.approve_remediation(mine["id"], "dennis")
    assert done["status"] == "executed" and done["approved_by"] == "dennis"
    assert bank.get("pay_0001")["status"] == "recalled"
    again = tools_retract.approve_remediation(mine["id"], "dennis")  # one click, once
    assert again["error"]["code"] == "INVALID_ARGUMENT"


def test_act_is_idempotent_and_needs_premises(g):
    cap = PremiseCapture()
    svc = ActionService(g, cap, executor=Recorder())
    with pytest.raises(Exception) as e:
        svc.act("pay", {"amount": 1}, "payments")
    assert e.value.code == "INVALID_ARGUMENT"
    cap.record("payments", ["b_inv1_ok"])
    a = svc.act("pay", {"vendor": "v", "amount": 100}, "payments")
    b = svc.act("pay", {"vendor": "v", "amount": 100}, "payments")
    assert a["action_id"] == b["action_id"] and b.get("already_executed")


@pytest.mark.parametrize("sources,allowed,warn", [(1, False, False), (2, True, False), (None, True, True)])
def test_independent_source_policy_over_10k(g, sources, allowed, warn):
    ex = Recorder()
    fn = None if sources is None else (lambda aid: {"independent_sources": sources, "bound": "exact"})
    cap = PremiseCapture()
    cap.record("payments", ["b_inv1_ok"])
    out = ActionService(g, cap, executor=ex, fragility_fn=fn).act(
        "pay", {"vendor": "v", "amount": 25000}, "payments")
    assert out["executed"] is allowed
    if not allowed:
        d = out["blocked_reason"]["details"]
        assert (d["reason_code"], d["independent_sources"], d["required"]) == (
            "INSUFFICIENT_INDEPENDENT_SOURCES", 1, 2)
        assert ex.executed == []
    assert bool(out.get("warnings")) is warn


def test_small_payments_skip_the_cost_rule(g):
    cap = PremiseCapture()
    cap.record("payments", ["b_inv1_ok"])
    out = ActionService(g, cap, executor=Recorder(), fragility_fn=lambda a: {"independent_sources": 1}).act(
        "pay", {"vendor": "v", "amount": 10000}, "payments")  # not over 10k
    assert out["executed"] is True


def test_reinstating_withdraws_drafts(g):
    res = do_distrust(g)
    remediator.remediate(g, res["retraction_id"])
    assert {d["status"] for d in remediator.list_remediations(g)} == {"draft"}
    reinstate(g, res["retraction_id"])
    assert {d["status"] for d in remediator.list_remediations(g)} == {"withdrawn"}
    rem = remediator.list_remediations(g)[0]
    with pytest.raises(Exception) as e:
        remediator.approve(g, rem["id"], "dennis", Recorder())
    assert e.value.code == "INVALID_ARGUMENT"
    # Retract again: the same drafts come back to life instead of duplicating.
    res2 = do_distrust(g)
    again = remediator.remediate(g, res2["retraction_id"])
    assert {d["status"] for d in again} == {"draft"}
    assert len(remediator.list_remediations(g)) == len(again)


def test_reject_and_approve_without_executor(g):
    tools_retract.configure(g, None)
    res = tools_retract.distrust(W["source"], W["from"], W["to"])
    ids = [d["id"] for d in res["remediations"]]
    assert tools_retract.reject_remediation(ids[0], "dennis")["status"] == "rejected"
    rec = tools_retract.approve_remediation(ids[1], "dennis")
    assert rec["status"] == "approved"  # recorded, but no executor configured so nothing was sent
    assert [d["status"] for d in tools_retract.list_remediations("draft")] == ["draft"]


def test_mcp_surface(g, monkeypatch):
    monkeypatch.setenv("RETCON_MEMORY", "0")

    async def go():
        async with Client(build(graph=g)) as c:
            names = {t.name for t in (await c.list_tools()).tools}
            res = json.loads((await c.call_tool("distrust", {
                "source": W["source"], "from_": W["from"], "to": W["to"]})).content[0].text)
            drafts = [json.loads(x.text) for x in (await c.call_tool("list_remediations", {})).content]
            return names, res, drafts
    names, res, drafts = asyncio.run(go())
    assert {"list_remediations", "approve_remediation", "reject_remediation"} <= names
    assert len(res["remediations"]) == 3 and len(drafts) == 3


def test_act_is_registered_with_memory_and_gated_end_to_end(g, monkeypatch):
    """Through the real server: recall (Lane B) fills the premise capture, act (Lane A) is gated."""
    monkeypatch.setenv("RETCON_EMBEDDER", "hash")
    from core.retrieve import q2
    from core.retrieve.embed import HashEmbedder
    q2.ensure_vector_index(g)
    q2.embed_graph(g, HashEmbedder())
    from gate import tools as gate_tools

    async def go():
        srv = build(graph=g)
        gate_tools._service.executor = Recorder()
        async with Client(srv) as c:
            names = {t.name for t in (await c.list_tools()).tools}
            await c.call_tool("recall", {"query": "invoice INV-1001 purchase order", "agent": "payments"})
            ok = json.loads((await c.call_tool("act", {
                "tool": "pay", "args": {"vendor": "v", "amount": 900}, "agent": "payments"})).content[0].text)
            return names, ok
    names, ok = asyncio.run(go())
    assert "act" in names and "recall" in names
    assert ok["executed"] is True and ok["action_id"].startswith("act_")
