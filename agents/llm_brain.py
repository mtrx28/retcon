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

TOOLS = {
    "begin_turn": "{} : start a fresh turn (clears what you have read)",
    "observe": '{"source","text","observed_at"} : ingest a document from a source (Intake only)',
    "recall": '{"query","k","contains"?} : search memory; everything returned becomes a premise of your next write',
    "remember": '{"text","kind":"belief|plan","mtype"?} : write a belief or plan, justified by what you recalled',
    "fragility": '{"node_id"} : poisoning cost = how many sources must fail before the node falls',
    "why": '{"node_id","max_depth"?} : the justification tree behind a node',
    "act": '{"tool":"pay|email|notify","args":{...}} : propose an action; the gate may block it',
}

ROLES = {
    "intake": "You read sources and record what they say as observations and beliefs.",
    "analyst": "You cross-check beliefs and derive conclusions such as invoice-to-PO matches.",
    "payments": "You decide whether to pay. Before paying call fragility and why on your plan; if the "
                "poisoning cost is below the policy minimum for a large payment, request verification "
                "instead of paying.",
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
    def __init__(self, complete, cache_dir=None, params=None, offline=False, max_steps=14):
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
                         f"{json.dumps(h['result'], sort_keys=True, default=str)[:600]}"
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
            return Step(done=True, summary=str(obj.get("summary", "")), outbox=outbox)
        if obj.get("tool") in TOOLS and isinstance(obj.get("args", {}), dict):
            self._pending = (obj["tool"], obj.get("args", {}))
            return Step(tool=obj["tool"], args=obj.get("args", {}))
        return Step(done=True, summary=f"aborted: unknown tool {obj.get('tool')!r}")

    def first(self):
        return self._next()

    def feed(self, result):
        self.history.append({"tool": self._pending[0], "args": self._pending[1], "result": result})
        return self._next()
