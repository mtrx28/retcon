"""Benchmark scenarios (CONTRACT v1.4 names): ap_tiny, ap_1k, ap_10k, ap_100k, science_tiny, science,
plus the precision scenarios ap_prec_1k, ap_prec_10k.

ap_1k / ap_10k: ONE compromised portal, one window. Contamination shrinks as the graph grows (one bad source
among many good ones).

ap_prec_*: the precision test. 5-10 poisoned vendors, each with its OWN window; roughly a third of the facts
the bad sources touched are also confirmed by a trusted source (callback log, signed contract), and many
payments are legitimate yet route partly through a bad source. A rule that flags everything downstream of a
bad source loses those correct facts and payments; a justification-aware rule must not.
`bench.harness.scenarios.profile(scenario)` reports what a scenario actually contains.

Several windows (science, ap_prec_*): the harness applies them in order to one graph and unions the
`out_ids` (a strategy still sees a single `Window` per call, as in bench/api.py).
"""
import json
from dataclasses import dataclass, field
from pathlib import Path

from bench.api import Window
from data.generator import generate, vendors_for_nodes

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "data" / "fixtures"
SIZES = {"ap_1k": 1_000, "ap_10k": 10_000, "ap_100k": 100_000}
INVOICES, EXECUTED, LAUNDER = 12, 6, 2


@dataclass
class Scenario:
    name: str
    domain: str
    spec: dict
    seed: int | None
    windows: list = field(default_factory=list)

    @property
    def nodes(self):
        s = self.spec
        return len(s["observations"]) + len({d["conclusion"]["id"] for d in s["derivations"]}) + len(s["actions"])

    @property
    def info(self):
        return {"name": self.name, "domain": self.domain, "nodes": self.nodes, "seed": self.seed}


def windows_of(spec):
    """Every Window to apply, in order: one per retracted paper (science `retractions`), one per poisoned
    portal (AP `windows`), else the single `spec["window"]`."""
    if spec.get("retractions"):
        return [Window(r["source"], r["from"], r["to"]) for r in spec["retractions"]]
    if spec.get("windows"):
        return [Window(w["source"], w["from"], w["to"]) for w in spec["windows"]]
    return [Window.from_spec(spec)]


def ap_generated(nodes, seed=7, launder_depth=LAUNDER, invoices=INVOICES, executed=EXECUTED):
    vendors = vendors_for_nodes(nodes, invoices, launder_depth)
    return generate(seed=seed, vendors=max(2, vendors), invoices=invoices, launder_depth=launder_depth,
                    poisoned=1, executed=min(executed, invoices))


PRECISION = {"ap_prec_1k": 1_000, "ap_prec_10k": 10_000}
CORROBORATED = 0.6   # stratified; measured share of touched beliefs that survive lands at about 35-40%


def ap_precision(nodes, seed=7, invoices=INVOICES, executed=EXECUTED, launder_depth=LAUNDER):
    vendors = max(12, vendors_for_nodes(nodes, invoices, launder_depth))
    poisoned = min(10, max(5, vendors // 3))
    return generate(seed=seed, vendors=vendors, invoices=invoices, launder_depth=launder_depth, poisoned=poisoned,
                    executed=min(executed, invoices), corroborated=CORROBORATED, staggered=True)


def profile(scenario):
    """What the scenario contains: poisoned vendors, distinct windows, corroborated share, legit payments."""
    from data.generator.scenario import precision_profile
    return precision_profile(scenario.spec) if scenario.spec.get("windows") else None


def build(name, seed=7):
    """Scenario by name. Raises FileNotFoundError for fixture-backed scenarios that are not on disk."""
    if name == "ap_tiny":
        spec, dom, seed = _fixture("ap_tiny.json"), "ap", None
    elif name in SIZES:
        spec, dom = ap_generated(SIZES[name], seed), "ap"
    elif name in PRECISION:
        spec, dom = ap_precision(PRECISION[name], seed), "ap"
    elif name in ("science", "science_tiny"):
        spec, dom, seed = _fixture(f"{name}.json"), "science", None
    elif name.startswith("ap_launder_d"):                    # laundering probe: depth in the name
        spec, dom = ap_generated(1_000, seed, launder_depth=int(name.rsplit("d", 1)[1])), "ap"
    else:
        raise KeyError(f"unknown scenario {name!r}")
    return Scenario(name, dom, spec, seed, windows_of(spec))


def _fixture(filename):
    p = FIXTURES / filename
    if not p.exists():
        raise FileNotFoundError(f"{p} not found (science: python tasks.py science)")
    return json.loads(p.read_text(encoding="utf8"))
