"""Dependency-free SVG charts for RetconBench (task B7): drop straight into the README and the blog.

Every chart is a self-contained SVG with its own light/dark palette (prefers-color-scheme), labelled
axes and a legend, so it reads without surrounding text. Values are plotted as given: no smoothing,
no truncated axes; ratios are shown 0-100%.

    bars_by_strategy(rows, "residual_contamination", title)    scenario groups x strategy bars
    laundering_lines(curve)                                    residual vs restatement depth
    latency_bars(rows)                                         p50 with p95 whisker per scenario x strategy
    concurrency_lines(sweep)                                   p50/p95 read+write latency vs writers
    ablation_bars(on, off, sweep)                              attacker payments, graph on vs off
    write_all(rows, extra, concurrency, directory)             the set used by the README
"""
from pathlib import Path
from xml.sax.saxutils import escape

from bench.api import STRATEGY_NAMES

W, H, M = 760, 380, {"l": 64, "r": 24, "t": 48, "b": 70}
LABEL = {"delete_source": "delete source", "vector_only": "vector only", "edge_invalidation": "edge invalidation",
         "coarse_taint": "coarse taint", "retcon": "RETCON"}
# index-stable colours; RETCON is the strong accent
COLORS = {"delete_source": ("#8a94a3", "#9aa5b4"), "vector_only": ("#d9822b", "#f0a050"),
          "edge_invalidation": ("#b4488d", "#d878b4"), "coarse_taint": ("#2e7fb5", "#5aa8dc"),
          "retcon": ("#0f8a62", "#35c79a")}

STYLE = """<style>
 :root{--bg:#fff;--ink:#17202a;--muted:#5b6776;--grid:#e3e7ec}
 @media (prefers-color-scheme:dark){:root{--bg:#10161d;--ink:#e6ebf1;--muted:#9aa7b6;--grid:#252f3a}}
 text{font-family:ui-sans-serif,system-ui,Segoe UI,Roboto,Arial,sans-serif;fill:var(--ink)}
 .m{fill:var(--muted)} .g{stroke:var(--grid)} .ax{stroke:var(--muted)}
 .c-delete_source{--c:%s}.c-vector_only{--c:%s}.c-edge_invalidation{--c:%s}.c-coarse_taint{--c:%s}.c-retcon{--c:%s}
 .f{fill:var(--c)} .s{stroke:var(--c);fill:none}
 @media (prefers-color-scheme:dark){.c-delete_source{--c:%s}.c-vector_only{--c:%s}.c-edge_invalidation{--c:%s}.c-coarse_taint{--c:%s}.c-retcon{--c:%s}}
</style>""" % (tuple(COLORS[n][0] for n in STRATEGY_NAMES) + tuple(COLORS[n][1] for n in STRATEGY_NAMES))


def _svg(title, body, width=W, height=H, desc=""):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}" '
            f'role="img" aria-label="{escape(title)}"><title>{escape(title)}</title><desc>{escape(desc)}</desc>{STYLE}'
            f'<rect width="100%" height="100%" fill="var(--bg)"/>'
            f'<text x="{M["l"]}" y="26" font-size="15" font-weight="600">{escape(title)}</text>{body}</svg>')


def _axes(ymax, ylabel, fmt, plot_w, plot_h, ticks=5):
    out = [f'<text x="14" y="{M["t"] + plot_h / 2}" font-size="11" class="m" '
           f'transform="rotate(-90 14 {M["t"] + plot_h / 2})" text-anchor="middle">{escape(ylabel)}</text>']
    for i in range(ticks + 1):
        v = ymax * i / ticks
        y = M["t"] + plot_h - plot_h * i / ticks
        out.append(f'<line x1="{M["l"]}" x2="{M["l"] + plot_w}" y1="{y:.1f}" y2="{y:.1f}" class="g"/>')
        out.append(f'<text x="{M["l"] - 8}" y="{y + 4:.1f}" font-size="11" class="m" text-anchor="end">{fmt(v)}</text>')
    out.append(f'<line x1="{M["l"]}" x2="{M["l"]}" y1="{M["t"]}" y2="{M["t"] + plot_h}" class="ax"/>')
    return "".join(out)


def _legend(names, y):
    x, out = M["l"], []
    for n in names:
        out.append(f'<g class="c-{n}"><rect x="{x}" y="{y}" width="12" height="12" class="f" rx="2"/></g>'
                   f'<text x="{x + 17}" y="{y + 10}" font-size="12">{escape(LABEL.get(n, n))}</text>')
        x += 24 + 7 * len(LABEL.get(n, n))
    return "".join(out)


def _nice_max(v):
    if v <= 0:
        return 1.0
    for step in (1, 2, 2.5, 5, 10):
        for mag in (0.001, 0.01, 0.1, 1, 10, 100, 1000, 10000):
            if v <= step * mag:
                return step * mag
    return v


def bars_by_strategy(rows, metric, title, pct=True):
    scen = list(dict.fromkeys(r["scenario"] for r in rows))
    strat = [n for n in STRATEGY_NAMES if any(r["strategy"] == n for r in rows)]
    val = {(r["scenario"], r["strategy"]): (r["metrics"] or {}).get(metric) for r in rows if not r.get("error")}
    ymax = 1.0 if pct else _nice_max(max([v for v in val.values() if v is not None] or [1]))
    pw, ph = W - M["l"] - M["r"], H - M["t"] - M["b"]
    fmt = (lambda v: f"{v * 100:.0f}%") if pct else (lambda v: f"{v:g}")
    body = [_axes(ymax, "share of nodes" if pct else metric, fmt, pw, ph)]
    gw = pw / max(1, len(scen))
    bw = min(34, (gw * 0.8) / max(1, len(strat)))
    for gi, sc in enumerate(scen):
        x0 = M["l"] + gi * gw + (gw - bw * len(strat)) / 2
        for si, st in enumerate(strat):
            v = val.get((sc, st))
            x = x0 + si * bw
            if v is None:
                body.append(f'<text x="{x + bw / 2:.1f}" y="{M["t"] + ph - 6}" font-size="10" class="m" text-anchor="middle">n/a</text>')
                continue
            h = ph * (v / ymax)
            body.append(f'<g class="c-{st}"><rect x="{x + 1:.1f}" y="{M["t"] + ph - h:.1f}" width="{bw - 2:.1f}" '
                        f'height="{max(h, 0.8):.1f}" class="f" rx="2"><title>{escape(LABEL[st])}: {fmt(v)}</title></rect></g>')
            body.append(f'<text x="{x + bw / 2:.1f}" y="{M["t"] + ph - h - 4:.1f}" font-size="10" text-anchor="middle">{fmt(v)}</text>')
        body.append(f'<text x="{M["l"] + gi * gw + gw / 2:.1f}" y="{M["t"] + ph + 20}" font-size="12" text-anchor="middle">{escape(sc)}</text>')
    body.append(_legend(strat, H - 28))
    return _svg(title, "".join(body), desc=f"{metric} per strategy and scenario; lower is better"
                if metric in ("residual_contamination", "collateral_loss") else f"{metric}; higher is better")


def laundering_lines(curve):
    depths, res = curve["depths"], curve["residual"]
    strat = [n for n in STRATEGY_NAMES if n in res]
    pw, ph = W - M["l"] - M["r"], H - M["t"] - M["b"]
    body = [_axes(1.0, "residual contamination (lower is better)", lambda v: f"{v * 100:.0f}%", pw, ph)]
    xs = [M["l"] + pw * (i / max(1, len(depths) - 1)) for i in range(len(depths))]
    for x, d in zip(xs, depths):
        body.append(f'<text x="{x:.1f}" y="{M["t"] + ph + 20}" font-size="12" text-anchor="middle">{d}</text>')
    body.append(f'<text x="{M["l"] + pw / 2}" y="{M["t"] + ph + 40}" font-size="12" class="m" text-anchor="middle">'
                f'restatement hops between the compromised portal and the payment</text>')
    for st in strat:
        pts = [(x, M["t"] + ph - ph * v) for x, v in zip(xs, res[st]) if v is not None]
        if not pts:
            continue
        dash = "" if st == "retcon" else ' stroke-dasharray="1 0"'
        body.append(f'<g class="c-{st}"><polyline points="{" ".join(f"{x:.1f},{y:.1f}" for x, y in pts)}" class="s" '
                    f'stroke-width="{3 if st == "retcon" else 2}"{dash}/>'
                    + "".join(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.5" class="f"/>' for x, y in pts) + "</g>")
    body.append(_legend(strat, H - 28))
    return _svg("Laundering resistance: contamination left after retraction", "".join(body),
                desc="residual contamination versus number of restatement hops")


def latency_bars(rows):
    scen = list(dict.fromkeys(r["scenario"] for r in rows))
    strat = [n for n in STRATEGY_NAMES if any(r["strategy"] == n for r in rows)]
    lat = {(r["scenario"], r["strategy"]): r["latency_ms"] for r in rows if not r.get("error") and r.get("latency_ms")}
    top = max([l["p95"] for l in lat.values() if l.get("p95") is not None] or [1])
    ymax = _nice_max(top * 1.1)
    pw, ph = W - M["l"] - M["r"], H - M["t"] - M["b"]
    body = [_axes(ymax, "retraction latency (ms, wall clock)", lambda v: f"{v:g}", pw, ph)]
    gw = pw / max(1, len(scen))
    bw = min(34, (gw * 0.8) / max(1, len(strat)))
    for gi, sc in enumerate(scen):
        x0 = M["l"] + gi * gw + (gw - bw * len(strat)) / 2
        for si, st in enumerate(strat):
            l = lat.get((sc, st))
            if not l or l.get("p50") is None:
                continue
            x = x0 + si * bw
            h50, h95 = ph * l["p50"] / ymax, ph * l["p95"] / ymax
            body.append(f'<g class="c-{st}"><rect x="{x + 1:.1f}" y="{M["t"] + ph - h50:.1f}" width="{bw - 2:.1f}" '
                        f'height="{max(h50, 0.8):.1f}" class="f" rx="2"><title>{escape(LABEL[st])} p50 {l["p50"]} ms, '
                        f'p95 {l["p95"]} ms (n={l["n"]})</title></rect>'
                        f'<line x1="{x + bw / 2:.1f}" x2="{x + bw / 2:.1f}" y1="{M["t"] + ph - h95:.1f}" '
                        f'y2="{M["t"] + ph - h50:.1f}" class="s" stroke-width="2"/></g>')
        body.append(f'<text x="{M["l"] + gi * gw + gw / 2:.1f}" y="{M["t"] + ph + 20}" font-size="12" text-anchor="middle">{escape(sc)}</text>')
    body.append(_legend(strat, H - 28))
    body.append(f'<text x="{W - M["r"]}" y="26" font-size="11" class="m" text-anchor="end">bar = p50, whisker = p95</text>')
    return _svg("Retraction latency by graph size", "".join(body), desc="p50 and p95 retraction latency per strategy and scenario")


def concurrency_lines(sweep):
    xs_n = [r["writers"] for r in sweep]
    series = {"read p50": [r["read_ms"]["p50"] for r in sweep], "read p95": [r["read_ms"]["p95"] for r in sweep],
              "write p50": [r["write_ms"]["p50"] for r in sweep], "write p95": [r["write_ms"]["p95"] for r in sweep]}
    top = max(v for vs in series.values() for v in vs if v is not None)
    ymax = _nice_max(top * 1.1)
    pw, ph = W - M["l"] - M["r"], H - M["t"] - M["b"]
    body = [_axes(ymax, "latency per operation (ms)", lambda v: f"{v:g}", pw, ph)]
    xs = [M["l"] + pw * (i / max(1, len(xs_n) - 1)) for i in range(len(xs_n))]
    for x, n in zip(xs, xs_n):
        body.append(f'<text x="{x:.1f}" y="{M["t"] + ph + 20}" font-size="12" text-anchor="middle">{n}</text>')
    body.append(f'<text x="{M["l"] + pw / 2}" y="{M["t"] + ph + 40}" font-size="12" class="m" text-anchor="middle">'
                f'concurrent writer agents (a cascade runs mid-test)</text>')
    style = {"read p50": ("c-coarse_taint", ""), "read p95": ("c-coarse_taint", "4 3"),
             "write p50": ("c-retcon", ""), "write p95": ("c-retcon", "4 3")}
    lx = M["l"]
    for name, vs in series.items():
        cls, dash = style[name]
        pts = [(x, M["t"] + ph - ph * v / ymax) for x, v in zip(xs, vs) if v is not None]
        body.append(f'<g class="{cls}"><polyline points="{" ".join(f"{x:.1f},{y:.1f}" for x, y in pts)}" class="s" '
                    f'stroke-width="2.4" {"stroke-dasharray=%s" % chr(34) + dash + chr(34) if dash else ""}/>'
                    + "".join(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.2" class="f"/>' for x, y in pts) + "</g>")
        body.append(f'<g class="{cls}"><rect x="{lx}" y="{H - 28}" width="12" height="12" class="f" rx="2"/></g>'
                    f'<text x="{lx + 17}" y="{H - 18}" font-size="12">{name}</text>')
        lx += 112
    err = max(r["error_rate"] for r in sweep)
    body.append(f'<text x="{W - M["r"]}" y="26" font-size="11" class="m" text-anchor="end">'
                f'max error rate {err * 100:.1f}% over {sum(r["writers"] * r["ops_per_writer"] * 2 for r in sweep)} ops</text>')
    return _svg("Latency under concurrent writers", "".join(body), desc="read and write latency percentiles versus writer count")


def ablation_bars(on, off, sweep=None):
    """Attacker payments after the retraction (count) and clean nodes destroyed, graph on vs graph off."""
    groups = [("graph on", on), ("graph off", off)]
    pw, ph = W - M["l"] - M["r"], H - M["t"] - M["b"]
    keys = [("paid_attacker_after_retraction", "payments to the attacker after retraction", "retcon"),
            ("contaminated_missed", "contaminated nodes still retrievable", "vector_only"),
            ("clean_nodes_retracted", "clean nodes wrongly retracted", "delete_source")]
    vals = []
    for label, r in groups:
        row = dict(r)
        row["contaminated_missed"] = r["contaminated_total"] - r["contaminated_retracted"]
        vals.append((label, row))
    ymax = _nice_max(max(max(row[k] for k, _, _ in keys) for _, row in vals) * 1.15 or 1)
    body = [_axes(ymax, "count", lambda v: f"{v:g}", pw, ph)]
    gw = pw / 2
    bw = 44
    for gi, (label, row) in enumerate(vals):
        x0 = M["l"] + gi * gw + (gw - bw * len(keys)) / 2
        for ki, (k, _, cls) in enumerate(keys):
            v = row[k]
            h = ph * v / ymax
            x = x0 + ki * bw
            body.append(f'<g class="c-{cls}"><rect x="{x + 2:.1f}" y="{M["t"] + ph - h:.1f}" width="{bw - 4}" '
                        f'height="{max(h, 0.8):.1f}" class="f" rx="2"/></g>'
                        f'<text x="{x + bw / 2:.1f}" y="{M["t"] + ph - h - 5:.1f}" font-size="12" text-anchor="middle">{v}</text>')
        body.append(f'<text x="{M["l"] + gi * gw + gw / 2:.1f}" y="{M["t"] + ph + 20}" font-size="13" text-anchor="middle">{label}</text>')
    lx = M["l"]
    for k, text, cls in keys:
        body.append(f'<g class="c-{cls}"><rect x="{lx}" y="{H - 28}" width="12" height="12" class="f" rx="2"/></g>'
                    f'<text x="{lx + 17}" y="{H - 18}" font-size="11">{escape(text)}</text>')
        lx += 20 + 6.3 * len(text)
    return _svg("Same agents, same attack: graph on vs graph off", "".join(body),
                desc="attacker payments, missed contamination and collateral, with and without the graph")


def write_all(rows, extra=None, concurrency=None, directory="bench/results/charts"):
    d = Path(directory)
    d.mkdir(parents=True, exist_ok=True)
    out = {}
    out["residual.svg"] = bars_by_strategy(rows, "residual_contamination",
                                           "Residual contamination after retraction (lower is better)")
    out["collateral.svg"] = bars_by_strategy(rows, "collateral_loss",
                                             "Collateral loss: supported nodes wrongly retracted (lower is better)")
    out["action_recall.svg"] = bars_by_strategy(rows, "action_recall",
                                                "Action recall: executed contaminated actions flagged (higher is better)")
    out["latency.svg"] = latency_bars(rows)
    extra = extra or {}
    if "laundering" in extra:
        out["laundering.svg"] = laundering_lines(extra["laundering"])
    if "ablation" in extra:
        a = extra["ablation"]
        out["graph_off.svg"] = ablation_bars(a["graph_on"], a["graph_off"], a.get("sweep"))
    if concurrency:
        out["concurrency.svg"] = concurrency_lines(concurrency)
    for name, svg in out.items():
        (d / name).write_text(svg, encoding="utf8")
    return sorted(out)
