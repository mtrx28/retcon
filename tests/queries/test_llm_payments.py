"""Upgrade 5: the Payments agent chooses its tools through Gemini function calling. These tests never call the
API: they replay the committed transcript (data/llm_cache/payments) and check the mapping code."""
import json
from types import SimpleNamespace

import pytest

from agents import gemini
from agents.demo import run_day
from agents.gemini import _to_reply, payments_brains

pytestmark = pytest.mark.llm


def fc(name, **args):
    return SimpleNamespace(name=name, args=args)


def test_function_calls_map_to_brain_replies():
    assert json.loads(_to_reply(fc("recall", query="x", k=4.0))) == {"tool": "recall", "args": {"query": "x", "k": 4}}
    act = json.loads(_to_reply(fc("act", tool="pay", vendor="v1", iban="SYN-1", amount=10.0, invoice="I", idempotency_key="k")))
    assert act["tool"] == "act" and act["args"]["tool"] == "pay" and act["args"]["args"]["amount"] == 10.0
    done = json.loads(_to_reply(fc("finish", summary="held", request_verification=True)))
    assert done["done"] and done["handoffs"] == [{"to": "comms", "task": {}}]
    assert json.loads(_to_reply(fc("finish", summary="paid")))["handoffs"] == []


def test_modes_without_a_key(monkeypatch, tmp_path):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(gemini, "load_env", lambda *a, **k: None)
    assert payments_brains("rules") == {}
    assert payments_brains("auto", tmp_path) == {}                       # no transcript, no key: rule-based
    assert "payments" in payments_brains("auto")                         # the committed transcript replays offline
    assert "payments" in payments_brains("replay")


def test_committed_transcript_replays_the_whole_day(monkeypatch):
    """No key, no network: the recorded Gemini run reproduces the same day, and the gate/graph decide the rest."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(gemini, "load_env", lambda *a, **k: None)
    r = run_day(seed=7, graph_name="test_llm_replay", brains=payments_brains("replay"))
    try:
        pay = [s for role, kind, s in r["orch"].results if role == "payments"]
        assert not [s for s in pay if s.startswith("aborted")], pay
        paid = [(p["invoice"], p["amount"]) for p in r["world"].bank.payments]
        assert paid == [("INV-COASTAL-1", 6000), ("INV-V001-1", 6750)]     # same as the rule-based day
        held = {v["invoice"] for v in r["orch"].verifications}
        assert {"INV-COASTAL-2", "INV-V001-2"} <= held                      # large, single-source: held for callback
        d = r["distrust"]
        assert [(x["action_id"], x["amount"]) for x in d["recall_list"] if x["amount"]] == [("act_e1934ffef625", 6000)]
        assert any(x["kind"] == "bank_recall" for x in d["remediations"])
        # the model never wrote status: every payment tool call it made is in the log, and none was an unguarded payment
        acts = [e for e in r["world"].log.by_agent("payments") if e["tool"] == "act"]
        assert acts and all("executed" in e["result"] for e in acts)
    finally:
        r["world"].close()
