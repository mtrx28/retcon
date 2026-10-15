"""Reference JTMS: a deliberately naive in-memory model of RETCON's semantics.

Independent of the Cypher implementation: it never cascades or re-derives. After any sequence of
distrust / reinstate operations the labelling is recomputed from scratch as the LEAST fixpoint:

    IN = observations not covered by an active retraction, then repeatedly add any conclusion that
         has a justification (>= 1 premise) whose premises are all IN.

Least fixpoint means circular support can never keep a node IN. The Cypher engine (retract then
re-derive, incrementally) must agree with this on every graph and operation sequence.
Graph format: docs/CONTRACT.md section 8.
"""
from datetime import datetime


def _ts(iso: str) -> int:
    return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp())


class RefJTMS:
    def __init__(self, spec: dict):
        self.obs = {o["id"]: (o["source"], _ts(o["observed_at"])) for o in spec["observations"]}
        self.justs = [(d["conclusion"]["id"], d["premises"]) for d in spec["derivations"]]
        self.justs += [(a["id"], a["premises"]) for a in spec["actions"]]
        self.nodes = set(self.obs) | {c for c, _ in self.justs}
        self.active: dict[str, tuple[str, int, int]] = {}

    def distrust(self, rid: str, source: str, t_from, t_to) -> None:
        f = t_from if isinstance(t_from, int) else _ts(t_from)
        t = t_to if isinstance(t_to, int) else _ts(t_to)
        self.active[rid] = (source, f, t)

    def reinstate(self, rid: str) -> None:
        self.active.pop(rid)

    def retracted_observations(self) -> set[str]:
        return {o for o, (src, at) in self.obs.items()
                if any(s == src and f <= at <= t for s, f, t in self.active.values())}

    def labelling(self) -> dict[str, str]:
        live = set(self.obs) - self.retracted_observations()
        changed = True
        while changed:
            changed = False
            for conclusion, premises in self.justs:
                if conclusion not in live and premises and all(p in live for p in premises):
                    live.add(conclusion)
                    changed = True
        return {n: ("IN" if n in live else "OUT") for n in self.nodes}
