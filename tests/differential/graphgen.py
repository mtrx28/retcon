"""Hypothesis strategies: random scenario specs (docs/CONTRACT.md section 8) plus operation scripts.

Graphs deliberately include the hard cases: several justifications per conclusion (OR), multi-premise
justifications (AND), cycles and self-support, shared observations, actions on beliefs.
"""
from datetime import datetime, timedelta, timezone

from hypothesis import strategies as st

T0 = datetime(2026, 10, 1, tzinfo=timezone.utc)


def iso(day: int) -> str:
    return (T0 + timedelta(days=day)).strftime("%Y-%m-%dT%H:%M:%SZ")


SOURCES = ["s0", "s1", "s2"]
AGENTS = ["a0", "a1"]


@st.composite
def specs(draw, max_obs=8, max_derived=10, max_actions=3):
    n_obs = draw(st.integers(2, max_obs))
    n_der = draw(st.integers(1, max_derived))
    obs = [{"id": f"o{i}", "source": draw(st.sampled_from(SOURCES)),
            "observed_at": iso(draw(st.integers(0, 9))), "text": f"o{i}"} for i in range(n_obs)]
    derived_ids = [f"n{i}" for i in range(n_der)]
    obs_ids = [o["id"] for o in obs]
    derivations = []

    def add(concl, premises, agent):
        derivations.append({"id": f"d{len(derivations)}", "rule": "infer", "agent": agent,
                            "premises": premises,
                            "conclusion": {"id": concl, "kind": "belief", "text": concl}})

    # Grounded base: node i is first justified by earlier items only, as real justified writes are
    # (a premise must already exist). So the initial labelling is well-founded.
    for i, concl in enumerate(derived_ids):
        earlier = obs_ids + derived_ids[:i]
        premises = draw(st.lists(st.sampled_from(earlier), min_size=1, max_size=3, unique=True))
        add(concl, premises, draw(st.sampled_from(AGENTS)))
    # Extra justifications may point anywhere: alternatives (OR), cycles, self-support.
    pool = obs_ids + derived_ids
    for _ in range(draw(st.integers(0, 6))):
        premises = draw(st.lists(st.sampled_from(pool), min_size=1, max_size=3, unique=True))
        add(draw(st.sampled_from(derived_ids)), premises, draw(st.sampled_from(AGENTS)))
    actions = []
    for k in range(draw(st.integers(0, max_actions))):
        executed = draw(st.booleans())
        actions.append({"id": f"act{k}", "tool": "pay", "agent": "a0",
                        "amount": draw(st.integers(100, 50000)), "executed": executed,
                        "executed_at": iso(draw(st.integers(0, 9))) if executed else None,
                        "premises": draw(st.lists(st.sampled_from(derived_ids), min_size=1,
                                                  max_size=2, unique=True))})
    return {"tenant": "prop", "sources": [{"id": s, "kind": "portal", "trust": 0.5} for s in SOURCES],
            "agents": [{"id": a, "role": "x"} for a in AGENTS],
            "observations": obs, "derivations": derivations, "actions": actions}


@st.composite
def op_scripts(draw, max_ops=5):
    """List of ('distrust', source, day_from, day_to) | ('reinstate', k) where k picks an active one."""
    ops = []
    for _ in range(draw(st.integers(1, max_ops))):
        if draw(st.integers(0, 3)) == 0:
            ops.append(("reinstate", draw(st.integers(0, 10))))
        else:
            a = draw(st.integers(0, 9))
            b = draw(st.integers(a, 9))
            ops.append(("distrust", draw(st.sampled_from(SOURCES)), a, b))
    return ops
