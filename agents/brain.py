"""The pluggable "brain" (task B3).

A brain turns a task into a sequence of tool calls. One task = one Session:

    session = brain.start(role, task)
    step = session.first()                 # Step(tool=..., args=...) or Step(done=True, ...)
    while not step.done:
        result = toolbox.call(...)
        step = session.feed(result)

RuleBrain (default): deterministic per-role policies written as generators; no key, no network,
same inputs -> same graph. LlmBrain (agents/llm_brain.py): same interface, a model picks the next
call, responses cached on disk. The graph rules, not the brain, decide what is IN or OUT.
"""
from dataclasses import dataclass, field


@dataclass
class Step:
    tool: str | None = None
    args: dict = field(default_factory=dict)
    done: bool = False
    summary: str = ""
    outbox: list = field(default_factory=list)   # [(role, task)] handed to other agents
    data: dict = field(default_factory=dict)     # policy bookkeeping returned to the orchestrator


class GeneratorSession:
    """Adapts `def policy(task, params): result = yield (tool, args) ... return {...}`."""

    def __init__(self, gen):
        self._gen = gen

    def first(self):
        return self._step(lambda: next(self._gen))

    def feed(self, result):
        return self._step(lambda: self._gen.send(result))

    @staticmethod
    def _done(ret):
        ret = ret or {}
        data = {k: v for k, v in ret.items() if k not in ("summary", "outbox", "data")}
        data.update(ret.get("data", {}))
        return Step(done=True, summary=ret.get("summary", ""), outbox=ret.get("outbox", []), data=data)

    def _step(self, advance):
        try:
            tool, args = advance()
        except StopIteration as e:
            return self._done(e.value)
        return Step(tool=tool, args=args)


class RuleBrain:
    def __init__(self, params=None):
        from gate.policy import policy_for
        self.params = {"pay_rule": policy_for("pay").get("independent_sources",
                                                        {"over_amount": 10_000, "min": 2})}
        self.params.update(params or {})

    def start(self, role, task):
        from agents import analyst, comms, intake, payments
        policies = {"intake": intake.policy, "analyst": analyst.policy,
                    "payments": payments.policy, "comms": comms.policy}
        if role not in policies:
            raise KeyError(f"no policy for role {role!r}")
        return GeneratorSession(policies[role](task, self.params))
