"""Automatic premise capture (task B1).

Agents never declare parents. Everything retrieved into an agent's context is recorded here, and
the next write by that agent is justified by exactly that context. This over-approximates
dependence (it can only cause extra retraction, never a missed one), which is the safe direction.

Context persists across writes inside one turn; `begin_turn` clears it. Each agent has its own.
"""


class PremiseCapture:
    def __init__(self):
        self._ctx = {}

    def record(self, agent, ids):
        ctx = self._ctx.setdefault(agent, [])
        for i in ids:
            if i not in ctx:
                ctx.append(i)

    def context(self, agent):
        return list(self._ctx.get(agent, []))

    def begin_turn(self, agent):
        self._ctx[agent] = []
