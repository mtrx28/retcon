"""The front door (upgrade 1): the page a visitor sees first, and the data it shows.

    GET /                       the page
    GET /home/<file>            its static files
    GET /api/home/numbers       every figure on the page, read from the benchmark result files (never typed in)
    GET /api/home/compare       the five retraction rules run live on one real graph (accounts payable, 24 memories)

Nothing here is estimated or hard-coded: `numbers` reads bench/results/*.json (written by `python tasks.py bench`
and `python -m bench.harness.receipt`), and `compare` runs Lane A's five strategies on a fresh copy of the
fixture. A missing file means that figure is simply absent from the page.
"""
import json
import mimetypes
import threading
from pathlib import Path

from bench.api import STRATEGY_NAMES, metrics
from bench.harness.loader import load_batched
from bench.harness.runner import _apply, discover_strategies
from bench.harness.scenarios import build
from core.db import connect
from core.errors import RetconError
from data.httpkit import Raw

STATIC = Path(__file__).resolve().parent / "static"
RESULTS = Path(__file__).resolve().parents[2] / "bench" / "results"
_LOCK = threading.Lock()
_CACHE = {}


def _read(name):
    p = RESULTS / name
    return json.loads(p.read_text(encoding="utf8")) if p.exists() else None


def _results():
    """The most credible result set on disk: real-embedder (MiniLM) rows where they exist, topped up with the
    offline-embedder rows for scenarios MiniLM was not run on (the 10k graphs). Returns (rows, extra, label)."""
    base = _read("latest.json") or []
    mini = _read("latest.minilm.json") or []
    merged = {(r["scenario"], r["strategy"]): r for r in base}
    merged.update({(r["scenario"], r["strategy"]): r for r in mini})
    extra = (_read("latest.extra.json") or {}) | (_read("latest.minilm.extra.json") or {})
    return list(merged.values()), extra, ("minilm" if mini else None)


def numbers():
    rows, extra, label = _results()
    by = {(r["scenario"], r["strategy"]): r for r in rows if not r.get("error")}
    out = {"embedder": None, "receipt": _read("receipt.json")}
    vo = by.get(("ap_prec_1k", "vector_only")) or by.get(("ap_1k", "vector_only"))
    out["embedder"] = ((vo or {}).get("notes") or {}).get("embedder") or label
    # speed: how long the retraction takes as the graph grows
    speed = [{"scenario": s, "nodes": by[(s, "retcon")]["nodes"], "p50_ms": by[(s, "retcon")]["latency_ms"]["p50"],
              "windows": by[(s, "retcon")].get("windows", 1)}
             for s in ("ap_tiny", "ap_1k", "ap_10k") if (s, "retcon") in by]
    out["speed"] = speed
    # the precision table: one line per strategy
    table = []
    for st in STRATEGY_NAMES:
        r = by.get(("ap_prec_1k", st))
        if r:
            m = r["metrics"]
            table.append({"strategy": st, "residual": m["residual_contamination"], "collateral": m["collateral_loss"],
                          "wrong_actions": (m.get("wrongly_flagged_actions") or {}).get("count"),
                          "wrong_amount": (m.get("wrongly_flagged_actions") or {}).get("amount")})
    out["precision"] = table
    sci = by.get(("science", "retcon"))
    if sci:
        out["science"] = {"windows": sci.get("windows"), "nodes": sci["nodes"],
                          "contaminated": sci["metrics"]["counts"]["contaminated"],
                          "residual": sci["metrics"]["residual_contamination"],
                          "collateral": sci["metrics"]["collateral_loss"]}
    ab = extra.get("ablation") or (_read("latest.extra.json") or {}).get("ablation")
    if ab:
        out["ablation"] = {k: {"paid_attacker_after": ab[k]["paid_attacker_after_retraction"],
                               "amount_after": ab[k]["amount_to_attacker_after"],
                               "retracted": ab[k]["contaminated_retracted"], "of": ab[k]["contaminated_total"],
                               "clean_lost": ab[k]["clean_nodes_retracted"]} for k in ("graph_on", "graph_off")}
    conc = (extra.get("concurrency") or (_read("latest.extra.json") or {}).get("concurrency"))
    if conc:
        out["concurrency"] = {"max_writers": max(r["writers"] for r in conc),
                              "stale": sum(r["consistency"]["stale_in"] + r["consistency"]["stale_out"] for r in conc),
                              "error_rate": max(r["error_rate"] for r in conc),
                              "ops": sum(r["writers"] * r["ops_per_writer"] * 2 for r in conc)}
    return out


def _short(text, n=54):
    text = (text or "").strip()
    return text if len(text) <= n else text[: n - 1] + "…"


def compare():
    """Run the five rules on the fixture's real graph; cached, because it is deterministic."""
    with _LOCK:
        if "compare" in _CACHE:
            return _CACHE["compare"]
        sc = build("ap_tiny")
        spec, gt = sc.spec, sc.spec["ground_truth"]
        db = connect()
        tpl = load_batched(spec, db=db, graph_name="home_compare_tpl")
        results = {}
        try:
            strategies = discover_strategies()
            for name in STRATEGY_NAMES:
                if name not in strategies:
                    continue
                fork = tpl.copy("home_compare_run")
                try:
                    out, per_window, _, notes = _apply(strategies[name], fork, sc.windows)
                finally:
                    fork.delete()
                m = metrics(gt, out, spec["actions"])
                results[name] = {"out": sorted(out), "ms": round(sum(per_window), 1),
                                 "residual": m["residual_contamination"], "collateral": m["collateral_loss"],
                                 "counts": m["counts"], "notes": notes,
                                 "wrong_actions": (m.get("wrongly_flagged_actions") or {}).get("count", 0)}
        finally:
            tpl.delete()
        dead, live = set(gt["contaminated"]), set(gt["truly_supported"])
        nodes = [{"id": s["id"], "kind": "source", "label": s["id"], "trust": s["trust"]} for s in spec["sources"]]
        nodes += [{"id": o["id"], "kind": "observation", "label": _short(o["text"]), "source": o["source"],
                   "bad": o["id"] in dead} for o in spec["observations"]]
        seen = {}
        for d in spec["derivations"]:
            c = d["conclusion"]
            seen.setdefault(c["id"], {"id": c["id"], "kind": c["kind"], "label": _short(c["text"]), "bad": c["id"] in dead,
                                      "ways": 0})["ways"] += 1
        nodes += list(seen.values())
        nodes += [{"id": a["id"], "kind": "action", "label": f"{a['tool']} {a['amount']:,} ({'paid' if a['executed'] else 'pending'})",
                   "bad": a["id"] in dead, "ways": 1} for a in spec["actions"]]
        edges = [{"s": o["source"], "t": o["id"]} for o in spec["observations"]]
        edges += [{"s": p, "t": d["conclusion"]["id"], "j": d["id"]} for d in spec["derivations"] for p in d["premises"]]
        edges += [{"s": p, "t": a["id"], "j": f"j_{a['id']}"} for a in spec["actions"] for p in a["premises"]]
        w = sc.windows[0]
        _CACHE["compare"] = {"scenario": "ap_tiny", "window": {"source": w.source, "from": w.t_from, "to": w.t_to},
                             "nodes": nodes, "edges": edges, "strategies": results,
                             "total_bad": len(dead), "total_good": len(live)}
        return _CACHE["compare"]


def mount(router, shell=None):
    def guard(fn):
        def run(req):
            try:
                return 200, fn(req)
            except RetconError as e:
                return 400, e.as_payload()
            except Exception as e:  # noqa: BLE001 - a broken comparison must not take the page down
                return 500, {"error": {"code": "UNAVAILABLE", "message": f"{type(e).__name__}: {e}", "details": {}}}
        return run

    def page(req):
        return 200, Raw((STATIC / "index.html").read_bytes(), "text/html; charset=utf-8")

    def static(req, base=STATIC):
        p = (base / req.params["name"]).resolve()
        if base.resolve() not in p.parents or not p.is_file():
            return 404, {"error": {"code": "NOT_FOUND", "message": req.params["name"], "details": {}}}
        ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "application/json", "image/svg+xml"):
            ctype += "; charset=utf-8"
        return 200, Raw(p.read_bytes(), ctype)

    DOCS = {"MCP_CLIENT.md", "BENCH_FRAMING.md", "FRAGILITY.md"}

    def doc(req):
        name = req.params["name"]
        p = Path(__file__).resolve().parents[2] / "docs" / name
        if name not in DOCS or not p.is_file():
            return 404, {"error": {"code": "NOT_FOUND", "message": name, "details": {}}}
        return 200, Raw(p.read_bytes(), "text/plain; charset=utf-8")

    router.add("GET", "/", page)
    router.add("GET", "/docs/<name>", doc)
    router.add("GET", "/home/<name>", static)
    router.add("GET", "/home/assets/<name>", lambda req: static(req, STATIC / "assets"))   # credited pictures
    router.add("GET", "/api/home/numbers", guard(lambda r: numbers()))
    router.add("GET", "/api/home/compare", guard(lambda r: compare()))
