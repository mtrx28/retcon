"""UI shell server (task B6a): static page + JSON API over the tenant graphs in FalkorDB.

    python -m ui.shell.server [--port 8200] [--graph tenant_northwind]

    GET /                         the page
    GET /api/graphs               [{name, ...}] every graph in this FalkorDB
    GET /api/graph?graph=&limit=  full snapshot {version, nodes, edges, counts, truncated}
    GET /api/delta?graph=&since=  changes after a version (nodes, edges, updates) or {reset: true}
    GET /api/node?graph=&id=      details + justification tree (why) + fragility
    GET /api/retractions?graph=   audit trail
Errors use the contract shape {"error": {code, message, details}}. Read-only: the shell never writes.
"""
import argparse
import mimetypes
import os
import time
from pathlib import Path

from core.db import connect
from core.errors import RetconError
from core.fragility import fragility
from core.retract.why import why
from data.httpkit import Raw, Router, serve
from gate.policy import policy_for
from ui.shell import graphdata

STATIC = Path(__file__).resolve().parent / "static"
RADAR = Path(__file__).resolve().parents[1] / "radar"       # B6b: served at /static/radar.js
STATIC_DIRS = (STATIC, RADAR)
KINDS = {"plan": "Plan", "action": "Action", "belief": "Belief"}
DEFAULT_GRAPH = os.getenv("RETCON_TENANT", "northwind")


def _err(status, code, message, **details):
    return status, {"error": {"code": code, "message": message, "details": details}}


class Shell:
    def __init__(self, db=None, default_graph=None, limit=3000, min_interval=0.3):
        """`min_interval`: at most one graph re-read per this many seconds, however many clients poll."""
        self.db = db or connect()
        self.default_graph = default_graph
        self.limit = limit
        self.min_interval = min_interval
        self._watchers = {}
        self._frag_cache = {}

    # -- helpers ---------------------------------------------------------------------------
    def graph_names(self):
        # tenant graphs first, then the rest (demo and test graphs)
        return sorted(self.db.list_graphs(), key=lambda n: (not n.startswith("tenant_"), n))

    def _resolve(self, name):
        names = self.graph_names()
        if not name:
            name = self.default_graph or (f"tenant_{DEFAULT_GRAPH}" if f"tenant_{DEFAULT_GRAPH}" in names
                                          else (names[0] if names else None))
        if name not in names:
            raise RetconError("NOT_FOUND", f"no graph named {name!r}", {"graph": name, "available": names})
        return name

    def watcher(self, name):
        name = self._resolve(name)
        if name not in self._watchers:
            self._watchers[name] = graphdata.Watcher(self.db.select_graph(name), self.limit, self.min_interval)
        return name, self._watchers[name]

    def fragility_table(self, name, w, kinds, limit):
        """Poisoning cost of the live (IN) nodes of the given kinds, cheapest-to-poison first. Cached
        per graph version, so a polling radar costs nothing while the graph is quiet."""
        w.refresh()
        key = (name, w.version, tuple(kinds), limit)
        hit = self._frag_cache.get(key)
        if hit is not None:
            return hit
        labels = " OR ".join(f"m:{KINDS[k]}" for k in kinds)
        rows = w.g.query(
            f"MATCH (m:Mem) WHERE ({labels}) AND m.status = 'IN' "
            "OPTIONAL MATCH (j:Justification)-[:JUSTIFIES]->(m) "
            "WITH m, count(j) AS njust "
            "RETURN m.id, labels(m), m.text, m.amount, m.executed, m.tool, m.args, njust "
            "ORDER BY (m.amount IS NULL), m.amount DESC, njust DESC, m.id LIMIT $n", {"n": limit}).result_set
        items = []
        for mid, labs, text, amount, executed, tool, args, njust in rows:
            kind = graphdata._kind(labs)
            label = graphdata._action_label(tool, amount, args) if kind == "action" else graphdata._label(text)
            try:
                f = fragility(w.g, mid, with_flow=False)
            except RetconError:
                continue
            items.append({"id": mid, "kind": kind, "label": graphdata._label(label, 70), "amount": amount,
                          "executed": bool(executed) if executed is not None else None,
                          "independent_sources": f["independent_sources"], "bound": f["bound"],
                          "cut_set": f["cut_set"], "live_sources": f["live_sources"], "justifications": njust})
        items.sort(key=lambda i: (i["independent_sources"], -(i["amount"] or 0), i["id"]))
        rule = policy_for("pay").get("independent_sources", {})
        out = {"version": w.version, "items": items,
               "policy": {"min": rule.get("min", 2), "over_amount": rule.get("over_amount")}}
        self._frag_cache = {k: v for k, v in self._frag_cache.items() if k[0] == name and k[1] == w.version}
        self._frag_cache[key] = out
        return out

    # -- routes ----------------------------------------------------------------------------
    def router(self):
        r = Router()

        def guard(fn):
            def run(req):
                try:
                    return fn(req)
                except RetconError as e:
                    return (404 if e.code == "NOT_FOUND" else 400), e.as_payload()
            return run

        def index(req):
            return 200, Raw((STATIC / "index.html").read_bytes(), "text/html; charset=utf-8")

        def static(req):
            p = None
            for base in STATIC_DIRS:
                cand = (base / req.params["name"]).resolve()
                if base.resolve() in cand.parents and cand.is_file():
                    p = cand
                    break
            if p is None:
                return _err(404, "NOT_FOUND", f"no such file {req.params['name']!r}")
            ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
            if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
                ctype += "; charset=utf-8"
            return 200, Raw(p.read_bytes(), ctype)

        def graphs(req):
            return 200, [{"name": n} for n in self.graph_names()]

        def graph(req):
            name, w = self.watcher(req.query.get("graph"))
            return 200, {"graph": name, **w.snapshot()}

        def delta(req):
            name, w = self.watcher(req.query.get("graph"))
            try:
                since = int(req.query.get("since", "0"))
            except ValueError:
                raise RetconError("INVALID_ARGUMENT", "since must be an integer", {"since": req.query.get("since")})
            return 200, {"graph": name, **w.delta(since)}

        def node(req):
            name, w = self.watcher(req.query.get("graph"))
            nid = req.query.get("id")
            if not nid:
                raise RetconError("INVALID_ARGUMENT", "id is required", {})
            g = w.g
            out = {"graph": name, "id": nid}
            out["why"] = why(g, nid, int(req.query.get("depth", "6")))   # raises NOT_FOUND for non-Mem ids
            try:
                out["fragility"] = fragility(g, nid)
            except RetconError:
                out["fragility"] = None
            return 200, out

        def frag(req):
            name, w = self.watcher(req.query.get("graph"))
            kinds = [k for k in req.query.get("kinds", "plan,action").split(",") if k]
            bad = [k for k in kinds if k not in KINDS]
            if bad or not kinds:
                raise RetconError("INVALID_ARGUMENT", f"kinds must be among {sorted(KINDS)}", {"kinds": kinds})
            try:
                limit = max(1, min(200, int(req.query.get("limit", "40"))))
            except ValueError:
                raise RetconError("INVALID_ARGUMENT", "limit must be an integer", {})
            return 200, {"graph": name, **self.fragility_table(name, w, kinds, limit)}

        def report(req):
            from core import report as report_mod
            name, w = self.watcher(req.query.get("graph"))
            data = report_mod.build(w.g, req.query.get("retraction"), graph_name=name)
            fmt = req.query.get("format", "html")
            if fmt == "json":
                return 200, data
            if fmt in ("md", "markdown"):
                return 200, Raw(report_mod.markdown(data).encode("utf8"), "text/markdown; charset=utf-8")
            if fmt == "html":
                return 200, Raw(report_mod.html(data).encode("utf8"), "text/html; charset=utf-8")
            raise RetconError("INVALID_ARGUMENT", "format must be html, md or json", {"format": fmt})

        def retr(req):
            name, w = self.watcher(req.query.get("graph"))
            return 200, {"graph": name, "retractions": graphdata.retractions(w.g)}

        r.add("GET", "/graph", index)
        r.add("GET", "/index.html", index)
        r.add("GET", "/static/<name>", static)
        r.add("GET", "/api/graphs", guard(graphs))
        r.add("GET", "/api/graph", guard(graph))
        r.add("GET", "/api/delta", guard(delta))
        r.add("GET", "/api/node", guard(node))
        r.add("GET", "/api/retractions", guard(retr))
        r.add("GET", "/api/fragility", guard(frag))
        r.add("GET", "/api/report", guard(report))
        from ui import ops          # operator console (A6): preview / commit / reinstate / approve
        self.ops = ops.mount(r, self)
        from ui import demo, guide, home          # front door, guided demo (browser-driven), guide panel files
        home.mount(r, self)
        demo.mount(r, self, self.ops)
        guide.mount(r)
        return r


def main():
    os.environ.setdefault("RETCON_EMBEDDER", "hash")      # the guided demo should work offline and start instantly
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8200)
    ap.add_argument("--graph", help="graph to open first (default tenant_<RETCON_TENANT>)")
    ap.add_argument("--limit", type=int, default=3000, help="max Mem nodes drawn")
    a = ap.parse_args()
    shell = Shell(default_graph=a.graph, limit=a.limit)
    _, url = serve(shell.router(), a.port)
    print(f"RETCON UI on {url}   graphs: {', '.join(shell.graph_names()) or '(none yet)'}")
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    main()
