"""RetconBench runner (task B7).

For each scenario: load the spec once into a template graph (batched loader), then for every strategy and
repeat take a private GRAPH.COPY, time `strategy.retract()` wall-clock around the call, and score the
returned `out_ids` with `bench.api.metrics`. The harness never reads node statuses, only what the
strategy returns (CONTRACT v1.4). A strategy that raises gets an `error` row; the run carries on.

Latency is wall-clock `retract()` time per call, in ms: p50/p95 are nearest-rank over `repeats` samples
(with few repeats p95 is just the slowest sample; report n alongside). Results are a JSON list of
`bench.api.record()` rows with an added `latency_ms` block.
"""
import importlib
import json
import math
import time
from pathlib import Path

from bench.api import STRATEGY_NAMES, RetractionResult, Window, metrics, record
from bench.harness.loader import load_batched
from core.db import connect


def percentile(samples, p):
    """Nearest-rank percentile, p in [0, 100]. Defined for any non-empty list (n=1 -> that sample)."""
    if not samples:
        return None
    xs = sorted(samples)
    k = max(1, math.ceil(p / 100 * len(xs)))
    return xs[k - 1]


def stats(samples):
    if not samples:
        return {"n": 0, "p50": None, "p95": None, "min": None, "max": None, "mean": None}
    return {"n": len(samples), "p50": round(percentile(samples, 50), 3), "p95": round(percentile(samples, 95), 3),
            "min": round(min(samples), 3), "max": round(max(samples), 3),
            "mean": round(sum(samples) / len(samples), 3)}


def discover_strategies():
    """Lane A's strategies from bench/baselines/<name>.py (class with `.name == <name>`), by contract
    name. Missing modules are simply absent, so the harness runs with whatever has landed."""
    found = {}
    for name in STRATEGY_NAMES:
        try:
            mod = importlib.import_module(f"bench.baselines.{name}")
        except ImportError:
            continue
        for obj in vars(mod).values():
            if isinstance(obj, type) and getattr(obj, "name", None) == name and hasattr(obj, "retract"):
                found[name] = obj()
                break
    return found


def _drop(client, name):
    try:
        client.select_graph(name).delete()
    except Exception:  # noqa: BLE001 - nothing to drop
        pass


def _apply(strategy, graph, windows):
    """Apply every window in order on one graph; union what the strategy reports."""
    out, per_window, engine, notes = set(), [], 0.0, {}
    for w in windows:
        t0 = time.perf_counter()
        res = strategy.retract(graph, w)
        per_window.append((time.perf_counter() - t0) * 1000)
        if not isinstance(res, RetractionResult):
            raise TypeError(f"{type(strategy).__name__}.retract must return RetractionResult")
        out |= set(res.out_ids)
        if res.engine_ms is not None:
            engine += res.engine_ms
        notes.update(res.notes or {})
    return out, per_window, (engine or None), notes


def run_scenario(scenario, strategies, repeats=3, db=None, prefix="bench", keep_template=False):
    """Rows for one scenario x every strategy. `strategies`: {name: Strategy}."""
    db = db or connect()
    tpl_name, run_name = f"{prefix}_{scenario.name}_tpl", f"{prefix}_{scenario.name}_run"
    t0 = time.perf_counter()
    tpl = load_batched(scenario.spec, db=db, graph_name=tpl_name)
    load_ms = (time.perf_counter() - t0) * 1000
    rows = []
    try:
        for name in STRATEGY_NAMES:
            if name not in strategies:
                continue
            strat, samples, walls, outs = strategies[name], [], [], []
            err, engine, notes = None, None, {}
            for _ in range(max(1, repeats)):
                _drop(db, run_name)
                try:
                    fork = tpl.copy(run_name)
                    out, per_window, engine, notes = _apply(strat, fork, scenario.windows)
                except Exception as e:  # noqa: BLE001 - one broken strategy must not end the run
                    err = f"{type(e).__name__}: {e}"
                    break
                finally:
                    _drop(db, run_name)
                samples.append(sum(per_window))
                walls += per_window
                outs.append(out)
            if err:
                rows.append({**record(scenario.info, name, None, None, error=err), "latency_ms": stats([])})
                continue
            res = RetractionResult(outs[0], engine, dict(notes))
            m = metrics(scenario.spec["ground_truth"], outs[0], scenario.spec["actions"])
            row = record(scenario.info, name, res, m, elapsed_ms=round(stats(samples)["p50"], 3), error=None)
            row["latency_ms"] = stats(samples)
            if len(scenario.windows) > 1:
                row["latency_per_window_ms"] = stats(walls)
                row["windows"] = len(scenario.windows)
            if any(o != outs[0] for o in outs[1:]):
                row["notes"] = {**row["notes"], "nondeterministic": True}
            row["load_ms"] = round(load_ms, 1)
            prof = scenario.spec.get("meta", {}).get("precision")
            if prof:
                row["profile"] = prof
            rows.append(row)
    finally:
        if not keep_template:
            _drop(db, tpl_name)
    return rows


def run_matrix(scenarios, strategies=None, repeats=3, db=None, prefix="bench", out=None, progress=None):
    """All scenarios x strategies. Writes `out` (JSON list) when given. Returns the rows."""
    strategies = strategies if strategies is not None else discover_strategies()
    db = db or connect()
    rows = []
    for sc in scenarios:
        if progress:
            progress(f"{sc.name}: {sc.nodes} nodes, {len(sc.windows)} window(s), {len(strategies)} strategies")
        rows += run_scenario(sc, strategies, repeats, db, prefix)
    if out:
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_text(json.dumps(rows, indent=1), encoding="utf8")
    return rows


def table(rows):
    """Plain-text results table (scenario x strategy), for the terminal and the README."""
    def f(x, pct=True):
        return "  n/a" if x is None else (f"{x * 100:5.1f}%" if pct else f"{x:7.1f}")
    head = f"{'scenario':<14}{'strategy':<19}{'residual':>9}{'collateral':>11}{'act.recall':>11}{'blocked':>9}{'p50 ms':>9}{'p95 ms':>9}"
    out = [head, "-" * len(head)]
    for r in rows:
        m, lat = r.get("metrics"), r.get("latency_ms") or {}
        if r.get("error"):
            out.append(f"{r['scenario']:<14}{r['strategy']:<19}ERROR {r['error'][:60]}")
            continue
        out.append(f"{r['scenario']:<14}{r['strategy']:<19}{f(m['residual_contamination']):>9}{f(m['collateral_loss']):>11}"
                   f"{f(m['action_recall']):>11}{f(m['blocked_recall']):>9}{f(lat.get('p50'), False):>9}{f(lat.get('p95'), False):>9}")
    return "\n".join(out)
