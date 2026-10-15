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
from ui.shell import graphdata

STATIC = Path(__file__).resolve().parent / "static"
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
            p = (STATIC / req.params["name"]).resolve()
            if STATIC not in p.parents or not p.is_file():
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

        def retr(req):
            name, w = self.watcher(req.query.get("graph"))
            return 200, {"graph": name, "retractions": graphdata.retractions(w.g)}

        r.add("GET", "/", index)
        r.add("GET", "/static/<name>", static)
        r.add("GET", "/api/graphs", guard(graphs))
        r.add("GET", "/api/graph", guard(graph))
        r.add("GET", "/api/delta", guard(delta))
        r.add("GET", "/api/node", guard(node))
        r.add("GET", "/api/retractions", guard(retr))
        return r


def main():
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
