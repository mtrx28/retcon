"""Agent orchestration (task B3): wires the world, runs tasks FIFO, hands work between agents, and
turns retractions into events the agents re-plan from.

    world = build_world(spec, graph_name="b3_run")          # in-process tools (transport="mcp" for real MCP)
    orch = Orchestrator(world)
    orch.ingest_until("2026-10-08T23:59:59Z")                # sources -> Intake -> Analyst/Comms -> Payments
    res = orch.distrust("coastal-portal", *window)           # operator action, logged like any tool call
    orch.dispatch_events(res["retraction_id"])               # Payments re-plans from surviving memory

Deterministic: FIFO queue, no clocks, no randomness. The tool-call log is `world.log`.
"""
import copy
import os
import time
from collections import deque
from dataclasses import dataclass, field

from agents.brain import RuleBrain
from agents.events import retraction_events
from agents.toolbox import LocalToolbox, McpToolbox, ToolCallLog
from core.actions import ActionService
from core.memory import MemoryService
from core.retrieve.embed import get_embedder
from data.bank import MockBank
from data.inbox import SandboxInbox
from data.load_fixture import load
from gate.executors import SandboxExecutor

MAX_STEPS = 24  # per task: a brain that loops is cut off, not trusted


@dataclass
class World:
    spec: dict
    graph: object
    memory: MemoryService
    actions: ActionService
    bank: MockBank
    inbox: SandboxInbox
    toolbox: object
    log: ToolCallLog
    _closers: list = field(default_factory=list)

    def close(self):
        for c in self._closers:
            c()


def build_world(spec, graph_name="b3_run", transport="local", embedder=None):
    """A tenant graph with sources and agents only (agents build the memory), plus sandbox services."""
    seed = copy.deepcopy(spec)
    seed["observations"], seed["derivations"], seed["actions"] = [], [], []
    graph = load(seed, graph_name=graph_name)
    embedder = embedder or get_embedder()
    memory = MemoryService(graph, embedder)
    bank, inbox = MockBank.from_spec(spec), SandboxInbox.from_spec(spec)
    inbox.inbound = []  # the inbox is read through Intake's sources, not preloaded
    executor = SandboxExecutor(bank, inbox)
    log = ToolCallLog()
    world = World(spec, graph, memory, None, bank, inbox, None, log)
    if transport == "local":
        from mcp_server import tools_memory
        world.actions = ActionService(graph, memory.capture, executor=executor,
                                      fragility_fn=lambda nid: tools_memory.fragility(nid))
        tools_memory.configure(memory)
        world.toolbox = LocalToolbox(graph, memory, world.actions, executor, log)
    elif transport == "mcp":
        # the real server, reached over a real MCP client; actions execute through the sandbox over HTTP
        from data.httpkit import serve
        from data.sandbox import build as build_sandbox
        from mcp_server.server import build
        router, svc = build_sandbox(spec)
        srv, url = serve(router)
        world.bank, world.inbox = svc["bank"], svc["inbox"]
        world.inbox.inbound = []
        os.environ["RETCON_SANDBOX_URL"] = url
        os.environ["RETCON_EMBEDDER"] = embedder.name
        server = build(graph=graph)
        # the server built its own MemoryService; agents and the world must share that one
        from mcp_server import tools_memory
        world.memory = tools_memory._service
        toolbox = McpToolbox(server, log)
        world.toolbox = toolbox
        world._closers += [toolbox.close, srv.shutdown]
    else:
        raise ValueError(f"unknown transport {transport!r}")
    return world


class Orchestrator:
    def __init__(self, world, brain=None, brains=None, pace=0.0):
        """`brain` is the default for every role; `brains` overrides per role (e.g. an LLM for payments)."""
        self.w = world
        self.pace = pace          # seconds to sleep after each task (live demos only)
        self.brain = brain or RuleBrain()
        self.brains = brains or {}
        self.queue = deque()
        self.ledger = {}          # plan_id -> Payments' private bookkeeping
        self.verifications = []   # verification requests sent, in order
        self.events = []          # every retraction event delivered
        self.results = []         # (role, task_type, summary)
        self._ingested = set()
        self._feed = sorted(world.spec["observations"], key=lambda o: (o["observed_at"], o["id"]))
        self._vendors = world.spec.get("vendors", [])

    # -- tasks -------------------------------------------------------------------------------
    def run_task(self, role, task):
        session = self.brains.get(role, self.brain).start(role, task)
        step, n = session.first(), 0
        while not step.done:
            n += 1
            if n > MAX_STEPS:
                self.results.append((role, task["type"], "aborted: step limit"))
                return None
            step = session.feed(self.w.toolbox.call(role, step.tool, step.args))
        self.results.append((role, task["type"], step.summary))
        if self.pace:
            time.sleep(self.pace)
        if step.data.get("ledger"):
            self.ledger[step.data["ledger"]["plan_id"]] = step.data["ledger"]
        for entry in step.data.get("ledgers", []):
            self.ledger[entry["plan_id"]] = entry
        if task["type"] == "request_verification":
            self.verifications.append({"invoice": task["invoice"], "vendor": task["vendor"],
                                       "sent": bool(step.data.get("action_id")), "action_id": step.data.get("action_id"),
                                       "plan_text": task["plan_text"]})
        for target, t in step.outbox:
            self.queue.append((target, t))
        return step

    def drain(self):
        while self.queue:
            self.run_task(*self.queue.popleft())

    # -- sources -> Intake ------------------------------------------------------------------
    def _vendor_for(self, text):
        for v in self._vendors:
            if v["name"] in text:
                return v
        return None

    def ingest_until(self, iso):
        """Feed every not-yet-seen observation dated <= iso to Intake, draining the hand-offs
        (Analyst, Comms, Payments) after each one so the order is deterministic."""
        for o in self._feed:
            if o["id"] in self._ingested or o["observed_at"] > iso:
                continue
            self._ingested.add(o["id"])
            v = self._vendor_for(o["text"])
            self.queue.append(("intake", {"type": "ingest", "source": o["source"], "text": o["text"],
                                          "observed_at": o["observed_at"],
                                          "vendor": v["name"] if v else None,
                                          "vendor_id": v["id"] if v else None}))
            self.drain()

    # -- retraction ---------------------------------------------------------------------------
    def distrust(self, source, t_from, t_to, operator="operator"):
        res = self.w.toolbox.call(operator, "distrust", {"source": source, "from_": t_from, "to": t_to})
        return res

    def dispatch_events(self, retraction_id):
        """Deliver the retraction to the agents that hold what flipped. Payments re-plans."""
        events = retraction_events(self.w.graph, retraction_id)
        self.events += events
        by_agent = {}
        for e in events:
            by_agent.setdefault(e["agent"], []).append(e)
        for agent in sorted(by_agent):
            plan_ids = sorted({p for e in by_agent[agent] for p in e["invalidated_plan_ids"]})
            if agent == "payments" and plan_ids:
                plans = [self.ledger[p] for p in plan_ids if p in self.ledger]
                self.queue.append(("payments", {"type": "retraction_event", "plans": plans,
                                                "event": by_agent[agent][0]}))
        self.drain()
        return events
