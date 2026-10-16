"""LLM brain (task B3): a model picks each agent's next tool call. Same Brain/Session interface as
RuleBrain, so roles can be mixed (`Orchestrator(world, brains={"payments": LlmBrain(...)})`).

Provider-agnostic on purpose: `complete(prompt: str) -> str` is the only thing a provider must
supply (an Anthropic, Gemini or local-model adapter is a few lines; none is bundled until a key is
chosen). Every completion is cached on disk by the SHA-256 of the prompt, so a recorded run replays
for free and identically; with `offline=True` a cache miss raises instead of calling the model.

The model never decides what is IN or OUT: it only chooses which tool to call. The graph rules and
the gate still decide, and a malformed reply ends the task (it never crashes the loop).
"""
import hashlib
import json
import os
from pathlib import Path

from agents.brain import Step
from agents.common import IBAN, failed
from agents.toolbox import _scrub

TOOLS = {
    "begin_turn": "{} : start a fresh turn (clears what you have read)",
    "observe": '{"source","text","observed_at"} : ingest a document from a source (Intake only)',
    "recall": '{"query","k","contains"?} : search memory; everything returned becomes a premise of your next write',
    "remember": '{"text","kind":"belief|plan","mtype"?} : write a belief or plan, justified by what you recalled',
    "fragility": '{"node_id"} : poisoning cost = how many sources must fail before the node falls',
    "why": '{"node_id","max_depth"?} : the justification tree behind a node',
    "act": '{"tool":"pay|email|notify","args":{...}} : propose an action; the gate may block it',
    "finish": '{"done":true,"summary":"...","handoffs":[{"to":"comms"}]} : end the task; hand off to comms to request callback verification',
}

ROLES = {
    "intake": "You read sources and record what they say as observations and beliefs.",
    "analyst": "You cross-check beliefs and derive conclusions such as invoice-to-PO matches.",
    "payments": "You decide whether to pay an invoice, using only what memory returns (recall returns only "
                "beliefs that are still believed). Follow these steps in order, each tool call once, never "
                "repeating a call you already made: "
                "(1) begin_turn, once, first. "
                "(2) recall the invoice match: query = the task's match_text, k=1. "
                "(3) recall the bank account: query '<vendor> bank account IBAN', k=4, contains=<vendor>. A "
                "recalled bank *change* takes precedence over the contract account. "
                "(4) remember kind=plan, text exactly 'Pay <invoice> <amount> USD to <iban>.' "
                "(5) recall that same text with k=1, so the payment rests on the plan. "
                "(6) fragility on the plan's node_id, then why on it. "
                "(7) Decide by comparing numbers: an amount at or below over_amount is never held, whatever its independent_sources (6000 is below 10000: pay it); only an amount above over_amount is held, and only when independent_sources is below min. If the amount is over the policy's over_amount AND independent_sources < the policy's "
                "min, do NOT pay: remember kind=belief 'Payment of <invoice> is on hold: it rests on <n> independent "
                "source(s), callback verification requested.' and finish with request_verification=true (the flag is what actually sends the callback request; saying so in the summary does nothing). "
                "Otherwise act with tool=pay, vendor=<vendor_id>, iban, amount, invoice, "
                "idempotency_key=<the plan's node_id>, then finish. "
                "For a retraction_event task, run steps 1 to 7 once for each pending plan in the task (skip plans "
                "marked executed), without calling begin_turn again between plans.",
    "comms": "You write to vendors and restate confirmed facts.",
}


class PromptCache:
    def __init__(self, directory=None):
        self.dir = Path(directory or os.getenv("RETCON_LLM_CACHE", "data/llm_cache"))
        self.hits = self.misses = 0

    def key(self, prompt):
        return hashlib.sha256(prompt.encode("utf8")).hexdigest()

    def get(self, prompt):
        p = self.dir / f"{self.key(prompt)}.json"
        if p.exists():
            self.hits += 1
            return json.loads(p.read_text(encoding="utf8"))["completion"]
        return None

    def put(self, prompt, completion):
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / f"{self.key(prompt)}.json").write_text(
            json.dumps({"prompt": prompt, "completion": completion}, indent=1), encoding="utf8")
        self.misses += 1


class LlmBrain:
    def __init__(self, complete, cache_dir=None, params=None, offline=False, max_steps=22):
        self.complete, self.cache, self.offline = complete, PromptCache(cache_dir), offline
        self.params, self.max_steps = params or {}, max_steps

    def start(self, role, task):
        return LlmSession(self, role, task)

    def ask(self, prompt):
        cached = self.cache.get(prompt)
        if cached is not None:
            return cached
        if self.offline:
            raise LookupError("LLM cache miss in offline mode")
        out = self.complete(prompt)
        self.cache.put(prompt, out)
        return out


class LlmSession:
    def __init__(self, brain, role, task):
        self.brain, self.role, self.task, self.history = brain, role, task, []

    def _prompt(self):
        tools = "\n".join(f"- {n} {d}" for n, d in TOOLS.items())
        hist = "\n".join(f"{i + 1}. {h['tool']} {json.dumps(h['args'], sort_keys=True)} -> "
                         f"{json.dumps(_scrub(h['result']), sort_keys=True, default=str)[:600]}"
                         for i, h in enumerate(self.history)) or "(nothing yet)"
        return (f"You are the {self.role} agent of an accounts-payable team. {ROLES.get(self.role, '')}\n"
                f"Policy: {json.dumps(self.brain.params.get('pay_rule', {}), sort_keys=True)}\n"
                f"Tools:\n{tools}\n"
                f"Task: {json.dumps(self.task, sort_keys=True)}\n"
                f"Tool calls so far:\n{hist}\n"
                'Reply with ONE JSON object: {"tool": "<name>", "args": {...}} to call a tool, or '
                '{"done": true, "summary": "<one line>", "handoffs": [{"to": "<role>", "task": {...}}]} '
                "when the task is finished.")

    def _next(self):
        if len(self.history) >= self.brain.max_steps:
            return Step(done=True, summary="aborted: step limit")
        try:
            raw = self.brain.ask(self._prompt())
            obj = json.loads(raw[raw.index("{"): raw.rindex("}") + 1])
        except (ValueError, LookupError) as e:
            return Step(done=True, summary=f"aborted: unusable model reply ({e})")
        if obj.get("done"):
            outbox = [(h["to"], h["task"]) for h in obj.get("handoffs", [])
                      if isinstance(h, dict) and "to" in h and "task" in h]
            data, outbox = self._bookkeeping(outbox)
            return Step(done=True, summary=str(obj.get("summary", "")), outbox=outbox, data=data)
        if obj.get("tool") in TOOLS and obj.get("tool") != "finish" and isinstance(obj.get("args", {}), dict):
            self._pending = (obj["tool"], obj.get("args", {}))
            return Step(tool=obj["tool"], args=obj.get("args", {}))
        return Step(done=True, summary=f"aborted: unknown tool {obj.get('tool')!r}")

    def _bookkeeping(self, outbox):
        """Payments' private ledger, derived from what the model actually did (plan written, fragility read,
        act result), plus the hand-off payload Comms needs. Nothing here is decided by the model."""
        if self.role != "payments" or self.task.get("type") not in ("pay_invoice", "retraction_event"):
            return {}, outbox
        pending = [self.task] if self.task["type"] == "pay_invoice" else [p for p in self.task.get("plans", []) if not p.get("executed")]
        entries, cur = [], None
        for h in self.history:
            t, a, r = h["tool"], h["args"], h["result"]
            if t == "remember" and a.get("kind") == "plan" and isinstance(r, dict) and not failed(r) and r.get("node_id"):
                src = pending[len(entries)] if len(entries) < len(pending) else {}
                m = IBAN.search(a.get("text", ""))
                cur = {"plan_id": r["node_id"], "invoice": src.get("invoice"), "amount": src.get("amount"),
                       "vendor": src.get("vendor"), "vendor_id": src.get("vendor_id"), "match_text": src.get("match_text"),
                       "iban": m.group(0) if m else None, "cost": None, "executed": False, "decision": "none",
                       "plan_text": a.get("text"), "cut_set": None}
                if self.task["type"] == "retraction_event" and "plan_id" in src:
                    cur["replaces"] = src["plan_id"]
                entries.append(cur)
            elif t == "fragility" and cur and a.get("node_id") == cur["plan_id"] and isinstance(r, dict) and not failed(r):
                cur["cost"], cur["cut_set"] = r.get("independent_sources"), r.get("cut_set")
            elif t == "act" and cur and a.get("tool") == "pay":
                if isinstance(r, dict) and r.get("executed"):
                    cur.update(decision="paid", executed=True, action_id=r.get("action_id"))
                else:
                    cur.update(decision="blocked", blocked=r)
        fixed = []
        for to, task in outbox:
            if to == "comms" and entries:
                e = entries[-1]
                e["decision"] = "verify" if e["decision"] == "none" else e["decision"]
                task = {"type": "request_verification", "plan_text": e["plan_text"], "invoice": e["invoice"],
                        "amount": e["amount"], "iban": e["iban"], "vendor": e["vendor"],
                        "vendor_id": e["vendor_id"], "cut_set": e["cut_set"]}
            fixed.append((to, task))
        if self.task["type"] == "pay_invoice":
            return ({"ledger": entries[0]} if entries else {}), fixed
        return {"ledgers": entries}, fixed

    def first(self):
        return self._next()

    def feed(self, result):
        self.history.append({"tool": self._pending[0], "args": self._pending[1], "result": result})
        return self._next()
