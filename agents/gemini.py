"""Gemini adapter for the LLM brain (upgrade 5): the Payments agent chooses its tools by Gemini function calling.

    payments_brains(mode)   -> {"payments": LlmBrain} or {} (rule-based), by mode:
        "rules"   never use a model (default for tests and the benchmark: RetconBench stays rule-based)
        "replay"  answer from the recorded transcript only; a cache miss ends the task, it never calls the API
        "live"    call Gemini (needs GEMINI_API_KEY), recording every call into the transcript
        "auto"    replay when a transcript is on disk; else live when a key is set; else rule-based

The transcript is `data/llm_cache/payments/` (one JSON file per call, keyed by the prompt's SHA-256) and is
committed, so a judge without a key replays the exact recorded run. Only the *choice of tool* comes from the
model: the graph decides what is IN or OUT, and the gate still blocks any payment that lacks independent
support. Data sent to Gemini is synthetic; nothing personal.
"""
import json
import os
import time
from pathlib import Path

from agents.llm_brain import LlmBrain

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "data" / "llm_cache" / "payments"
MODEL = os.getenv("RETCON_GEMINI_MODEL", "gemini-3.8-flash")
MIN_GAP_S = float(os.getenv("RETCON_GEMINI_GAP_S", "4"))        # stay under the free tier's requests per minute

_S, _N, _I = "STRING", "NUMBER", "INTEGER"


def _fn(name, desc, props=None, required=()):
    d = {"name": name, "description": desc}
    if props:
        d["parameters"] = {"type": "OBJECT", "properties": {k: {"type": t, "description": v} for k, (t, v) in props.items()},
                           "required": list(required)}
    return d


DECLARATIONS = [
    _fn("begin_turn", "Start a fresh turn. Clears what you have read, so call it first."),
    _fn("recall", "Search memory. Everything returned becomes a premise of your next write.",
        {"query": (_S, "what to look for"), "k": (_I, "how many results"), "contains": (_S, "optional text each hit must contain")},
        ["query"]),
    _fn("remember", "Write a belief or a plan, justified by what you recalled this turn.",
        {"text": (_S, "the statement"), "kind": (_S, "belief or plan")}, ["text", "kind"]),
    _fn("fragility", "Poisoning cost of a node: how many independent sources must fail before it falls.",
        {"node_id": (_S, "id returned by remember")}, ["node_id"]),
    _fn("why", "The justification tree behind a node.",
        {"node_id": (_S, "id returned by remember"), "max_depth": (_I, "default 6")}, ["node_id"]),
    _fn("act", "Propose an action. The gate may block it. For pay: vendor, iban, amount, invoice, idempotency_key.",
        {"tool": (_S, "pay, email or notify"), "vendor": (_S, "vendor id"), "iban": (_S, "bank account"),
         "amount": (_N, "amount in USD"), "invoice": (_S, "invoice id"), "idempotency_key": (_S, "the plan's node id")},
        ["tool"]),
    _fn("finish", "End the task.",
        {"summary": (_S, "one line saying what you decided"),
         "request_verification": ("BOOLEAN", "MUST be true whenever you held the payment: it is the only thing that makes Comms send the callback request")},
        ["summary"]),
]


def load_env(path=None):
    """Read KEY=VALUE lines from .env into the environment (never overrides, never printed)."""
    p = Path(path or ROOT / ".env")
    if p.exists():
        for line in p.read_text(encoding="utf8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                if v.strip():
                    os.environ.setdefault(k.strip(), v.strip())


def has_transcript(directory=None):
    d = Path(directory or CACHE)
    return d.is_dir() and any(d.glob("*.json"))


def _to_reply(call):
    """A Gemini function call -> the brain's JSON reply."""
    name, args = call.name, dict(call.args or {})
    if name == "finish":
        out = {"done": True, "summary": str(args.get("summary", "")), "handoffs": []}
        if args.get("request_verification"):
            out["handoffs"] = [{"to": "comms", "task": {}}]
        return json.dumps(out)
    if name == "act":
        tool = args.pop("tool", "pay")
        return json.dumps({"tool": "act", "args": {"tool": tool, "args": {k: v for k, v in args.items() if v is not None}}})
    return json.dumps({"tool": name, "args": {k: (int(v) if isinstance(v, float) and v.is_integer() and k in ("k", "max_depth") else v)
                                              for k, v in args.items()}})


class GeminiComplete:
    """`complete(prompt) -> str`: one forced function call per prompt."""

    def __init__(self, model=None):
        load_env()
        from google import genai
        from google.genai import types
        key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not key:
            raise RuntimeError("GEMINI_API_KEY is not set")
        self.types, self.model, self.client = types, model or MODEL, genai.Client(api_key=key)
        self.config = types.GenerateContentConfig(
            tools=[types.Tool(function_declarations=DECLARATIONS)],
            tool_config=types.ToolConfig(function_calling_config=types.FunctionCallingConfig(mode="ANY")),
            temperature=0.0)
        self.last = 0.0
        self.calls = 0

    def __call__(self, prompt):
        for attempt in range(6):
            wait = MIN_GAP_S - (time.time() - self.last)
            if wait > 0:
                time.sleep(wait)
            self.last = time.time()
            try:
                resp = self.client.models.generate_content(model=self.model, contents=prompt, config=self.config)
                calls = resp.function_calls or []
                if calls:
                    self.calls += 1
                    return _to_reply(calls[0])
                raise ValueError("no function call in the reply")
            except Exception as e:  # noqa: BLE001 - retry rate limits and overloads, surface everything else
                msg = str(e)
                fatal = msg.startswith(("400", "401", "403", "404"))          # bad request, key or model: retrying cannot help
                if attempt < 5 and not fatal:                                  # rate limits, overloads, dropped connections
                    time.sleep(8 * (attempt + 1))
                    continue
                raise


def payments_brains(mode="rules", cache_dir=None):
    """The `brains=` mapping for Orchestrator / run_day. Empty means: every role is rule-based."""
    load_env()
    if mode in (None, "", "rules", "off"):
        return {}
    d = Path(cache_dir or CACHE)
    if mode == "auto":
        mode = "replay" if has_transcript(d) else ("live" if os.getenv("GEMINI_API_KEY") else "rules")
        if mode == "rules":
            return {}
    if mode == "replay":
        return {"payments": LlmBrain(lambda p: (_ for _ in ()).throw(LookupError("replay only")), cache_dir=d, offline=True)}
    if mode == "live":
        return {"payments": LlmBrain(GeminiComplete(), cache_dir=d)}
    raise ValueError(f"unknown brain mode {mode!r}")
