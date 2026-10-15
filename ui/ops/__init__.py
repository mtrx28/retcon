"""Operator API + panels for the UI shell (task A6).

The shell itself is read-only (B6a). This module adds what the operator console needs, mounted into
the shell's router with `ops.mount(router, shell)`:

    GET  /api/ops/session                  {token}  per-process token the page must echo on POSTs
    GET  /api/ops/sources?graph=           sources with their observation time range (form defaults)
    GET  /api/ops/recall?graph=            {retractions, recall, remediations}
    GET  /api/ops/keystones?graph=&top=&order=   ranked sources (PageRank, Q8)
    GET  /api/ops/blast?graph=&source=     ids downstream of a source (to highlight)
    GET  /api/ops/contradictions?graph=    clusters of conflicting beliefs (algo.WCC)
    POST /api/ops/distrust    {token, graph, source, from, to, mode: preview|commit}
    POST /api/ops/reinstate   {token, graph, retraction_id}
    POST /api/ops/remediation {token, graph, id, action: approve|reject, operator?}
    GET  /ops/<file>                       the panels' static JS/CSS

The token stops a page on another origin from driving the console: a cross-origin page can send
the POST but cannot read the token (no CORS). Everything binds to 127.0.0.1 like the shell.
`RETCON_SANDBOX_URL` makes approved compensations reach the sandbox bank/inbox; without it an
approval is recorded and nothing is sent.
"""
import mimetypes
import os
import secrets
from pathlib import Path

from agents import remediator
from core.analytics import contradictions as contradiction_mod
from core.analytics import keystone as keystone_mod
from core.errors import RetconError
from core.preview.preview import preview
from core.recall.recall_list import recall_list
from core.retract import cascade
from data.httpkit import Raw

STATIC = Path(__file__).resolve().parent / "static"


def _executor():
    url = os.getenv("RETCON_SANDBOX_URL")
    if not url:
        return None
    from gate.executors import HttpExecutor
    return HttpExecutor(url)


class Ops:
    def __init__(self, shell, executor=None):
        self.shell = shell
        self.executor = executor if executor is not None else _executor()
        self.token = secrets.token_urlsafe(16)

    # -- helpers ------------------------------------------------------------------------------
    def _graph(self, name):
        _, w = self.shell.watcher(name)
        return w.g

    def _need(self, body, *keys):
        body = body or {}
        if not secrets.compare_digest(str(body.get("token", "")), self.token):
            raise RetconError("FORBIDDEN", "missing or wrong session token", {})
        missing = [k for k in keys if not body.get(k)]
        if missing:
            raise RetconError("INVALID_ARGUMENT", f"missing {missing}", {"missing": missing})
        return body

    # -- operations ---------------------------------------------------------------------------
    def sources(self, graph):
        g = self._graph(graph)
        rows = g.query(
            "MATCH (s:Source) OPTIONAL MATCH (s)-[:SUPPORTS]->(o:Observation) "
            "RETURN s.id, s.kind, s.trust, count(o), min(o.observed_at), max(o.observed_at) ORDER BY s.id"
        ).result_set
        return [{"id": r[0], "kind": r[1], "trust": r[2], "observations": r[3],
                 "first": r[4], "last": r[5]} for r in rows]

    def recall_state(self, graph):
        g = self._graph(graph)
        rets = [{"id": r[0], "source": r[1], "from": r[2], "to": r[3], "reason": r[4],
                 "at": r[5], "reinstated": bool(r[6])} for r in g.query(
            "MATCH (r:Retraction) RETURN r.id, r.source, r.from, r.to, r.reason, r.at, r.reinstated "
            "ORDER BY r.id DESC").result_set]
        seen, recall = set(), []
        for r in rets:
            if r["reinstated"]:
                continue
            for a in recall_list(g, r["id"]):
                if a["action_id"] not in seen:
                    seen.add(a["action_id"])
                    recall.append({**a, "retraction_id": r["id"]})
        recall.sort(key=lambda a: -(a["amount"] or 0))
        return {"retractions": rets, "recall": recall,
                "remediations": remediator.list_remediations(g)}

    def keystones(self, graph, top, order):
        try:
            top = max(1, min(int(top or 10), 100))
        except ValueError:
            raise RetconError("INVALID_ARGUMENT", "top must be an integer", {"top": top}) from None
        order = order or "priority"
        if order not in keystone_mod.ORDERS:
            raise RetconError("INVALID_ARGUMENT", f"order must be one of {list(keystone_mod.ORDERS)}", {"order": order})
        return {"order": order, "keystones": keystone_mod.keystones(self._graph(graph), top, order)}

    def blast(self, graph, source):
        if not source:
            raise RetconError("INVALID_ARGUMENT", "source is required", {})
        g = self._graph(graph)
        if not g.query("MATCH (s:Source {id:$s}) RETURN s.id", {"s": source}).result_set:
            raise RetconError("NOT_FOUND", f"source {source!r}", {"source": source})
        return {"source": source, "ids": keystone_mod.blast_radius(g, source)}

    def contradictions(self, graph):
        return {"clusters": contradiction_mod.contradiction_clusters(self._graph(graph))}

    def distrust(self, body):
        body = self._need(body, "source", "from", "to")
        g = self._graph(body.get("graph"))
        mode = body.get("mode", "preview")
        if mode == "preview":
            return preview(g, body["source"], body["from"], body["to"], operator="ui")
        if mode != "commit":
            raise RetconError("INVALID_ARGUMENT", "mode must be preview or commit", {"mode": mode})
        res = cascade.distrust(g, body["source"], body["from"], body["to"], operator=body.get("operator", "ui"))
        res["remediations"] = remediator.remediate(g, res["retraction_id"])
        return res

    def reinstate(self, body):
        body = self._need(body, "retraction_id")
        return cascade.reinstate(self._graph(body.get("graph")), body["retraction_id"])

    def remediation(self, body):
        body = self._need(body, "id", "action")
        g, op = self._graph(body.get("graph")), body.get("operator", "ui")
        if body["action"] == "approve":
            return remediator.approve(g, body["id"], op, self.executor)
        if body["action"] == "reject":
            return remediator.reject(g, body["id"], op)
        raise RetconError("INVALID_ARGUMENT", "action must be approve or reject", {"action": body["action"]})


def mount(router, shell, executor=None):
    """Add the operator routes to the shell's router. Returns the Ops instance."""
    ops = Ops(shell, executor)
    status = {"NOT_FOUND": 404, "FORBIDDEN": 403}

    def guard(fn):
        def run(req):
            try:
                return 200, fn(req)
            except RetconError as e:
                return status.get(e.code, 400), e.as_payload()
        return run

    def static(req):
        p = (STATIC / req.params["name"]).resolve()
        if STATIC not in p.parents or not p.is_file():
            return 404, {"error": {"code": "NOT_FOUND", "message": req.params["name"], "details": {}}}
        ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
            ctype += "; charset=utf-8"
        return 200, Raw(p.read_bytes(), ctype)

    router.add("GET", "/ops/<name>", static)
    router.add("GET", "/api/ops/session", guard(lambda r: {"token": ops.token}))
    router.add("GET", "/api/ops/sources", guard(lambda r: {"sources": ops.sources(r.query.get("graph"))}))
    router.add("GET", "/api/ops/recall", guard(lambda r: ops.recall_state(r.query.get("graph"))))
    router.add("GET", "/api/ops/keystones", guard(lambda r: ops.keystones(
        r.query.get("graph"), r.query.get("top"), r.query.get("order"))))
    router.add("GET", "/api/ops/blast", guard(lambda r: ops.blast(r.query.get("graph"), r.query.get("source"))))
    router.add("GET", "/api/ops/contradictions", guard(lambda r: ops.contradictions(r.query.get("graph"))))
    router.add("POST", "/api/ops/distrust", guard(lambda r: ops.distrust(r.json)))
    router.add("POST", "/api/ops/reinstate", guard(lambda r: ops.reinstate(r.json)))
    router.add("POST", "/api/ops/remediation", guard(lambda r: ops.remediation(r.json)))
    return ops
