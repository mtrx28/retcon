"""Guided demo backend (upgrade 1): lets a visitor run the real thing from the browser, with no terminal.

    POST /api/demo/start      {token}   run the seeded agent day into graph `demo_live` (background thread)
    GET  /api/demo/status               {phase: idle|running|ready|error, graph, tasks, error}
    POST /api/demo/ablation   {token}   same attack twice: graph on, graph off (graphs demo_abl_on / demo_abl_off)
    GET  /api/demo/ablation             {phase, result}

These run the same code as `python -m agents.demo` and `bench.harness.ablation`: real agents, real tools, real
FalkorDB. Graph names are fixed and nothing the visitor sends reaches a query. One job at a time (the agent tools
keep module-level configuration), and POSTs need the operator console's session token, so a page on another
origin cannot start a run.
"""
import os
import threading
import time

from core.errors import RetconError

GRAPH = "demo_live"
_JOB = threading.Lock()


class Demo:
    def __init__(self, ops):
        self.ops = ops
        self.day = {"phase": "idle", "graph": GRAPH, "tasks": 0, "error": None, "started": None}
        self.abl = {"phase": "idle", "result": None, "error": None}

    # -- helpers ------------------------------------------------------------------------------
    def _check(self, body):
        self.ops._need(body)                       # raises FORBIDDEN on a wrong or missing token

    def _busy(self):
        return self.day["phase"] == "running" or self.abl["phase"] == "running"

    # -- the agent day ------------------------------------------------------------------------
    def start(self, body):
        self._check(body)
        if self._busy():
            return dict(self.day)
        self.day.update(phase="running", tasks=0, error=None, started=time.time(), window=None)
        threading.Thread(target=self._run_day, daemon=True).start()
        return dict(self.day)

    def _run_day(self):
        with _JOB:
            try:
                from agents.demo import run_day
                os.environ.setdefault("RETCON_EMBEDDER", "hash")
                from agents.gemini import payments_brains
                brains = payments_brains("auto")           # recorded Gemini run when present, else live with a key, else rules
                self.day["brain"] = "gemini function calling (recorded transcript)" if brains else "rule-based"
                r = run_day(seed=7, retract=False, graph_name=GRAPH, pace=0.12, brains=brains)
                self.day["tasks"] = len(r["orch"].results)
                self.day["window"] = r["spec"]["window"]      # the compromised source and when: the operator's next move
                r["world"].close()
                self.day["phase"] = "ready"
            except Exception as e:  # noqa: BLE001 - report it to the page instead of dying silently
                self.day.update(phase="error", error=f"{type(e).__name__}: {e}")

    def status(self):
        return dict(self.day)

    # -- graph on vs graph off ----------------------------------------------------------------
    def start_ablation(self, body):
        self._check(body)
        if self._busy():
            return {"phase": self.abl["phase"], "result": self.abl["result"], "error": self.abl["error"]}
        self.abl.update(phase="running", result=None, error=None)
        threading.Thread(target=self._run_ablation, daemon=True).start()
        return {"phase": "running", "result": None, "error": None}

    def _run_ablation(self):
        with _JOB:
            try:
                from bench.harness.ablation import attacker_experiment
                os.environ.setdefault("RETCON_EMBEDDER", "hash")
                on = attacker_experiment(False, graph_name="demo_abl_on")
                off = attacker_experiment(True, graph_name="demo_abl_off")
                self.abl.update(phase="ready", result={"graph_on": on, "graph_off": off})
            except Exception as e:  # noqa: BLE001
                self.abl.update(phase="error", error=f"{type(e).__name__}: {e}")

    def ablation(self):
        return {"phase": self.abl["phase"], "result": self.abl["result"], "error": self.abl["error"]}


def mount(router, shell, ops):
    demo = Demo(ops)
    status = {"FORBIDDEN": 403}

    def guard(fn):
        def run(req):
            try:
                return 200, fn(req)
            except RetconError as e:
                return status.get(e.code, 400), e.as_payload()
        return run

    router.add("POST", "/api/demo/start", guard(lambda r: demo.start(r.json)))
    router.add("GET", "/api/demo/status", guard(lambda r: demo.status()))
    router.add("POST", "/api/demo/ablation", guard(lambda r: demo.start_ablation(r.json)))
    router.add("GET", "/api/demo/ablation", guard(lambda r: demo.ablation()))
    return demo
