"""What the canvas shows: a snapshot of a tenant graph, and a version-numbered change feed.

Node ids are unique across kinds in every graph we generate, so the client keys by id. Embeddings are
never sent. FalkorDB has no change feed, so `Watcher` re-reads the graph (rate limited) and diffs it
against the previous read; clients ask for "everything after version v".
"""
import json
import threading
import time
from collections import deque

from core.db import fetch_all

MEM_FIELDS = ("m.id", "labels(m)", "m.text", "m.status", "m.mtype", "m.agent", "m.run", "m.amount",
              "m.executed", "m.observed_at", "m.created_at", "m.gate_state", "m.tool", "m.args")
KIND_ORDER = ("Observation", "Belief", "Plan", "Action")
MUTABLE = ("status", "run", "executed", "gate", "retracted_at")  # fields a node can change after it is created


def _kind(labels):
    return next((k.lower() for k in KIND_ORDER if k in labels), "mem")


def _action_label(tool, amount, args):
    """`pay 6000`, `email: Callback verification: INV-1` instead of the raw JSON in Mem.text."""
    if amount is not None:
        return f"{tool} {amount:g}" if isinstance(amount, (int, float)) else f"{tool} {amount}"
    try:
        subject = json.loads(args or "{}").get("subject")
    except (ValueError, AttributeError):
        subject = None
    return f"{tool}: {subject}" if subject else str(tool or "action")


def _label(text, n=90):
    text = (text or "").strip()
    return text if len(text) <= n else text[: n - 1] + "…"


def snapshot(g, limit=3000):
    """{nodes, edges, counts, truncated}. When the graph exceeds `limit` Mem nodes the retracted and
    most recent ones are kept, so the interesting part survives."""
    total = g.query("MATCH (m:Mem) RETURN count(m)").result_set[0][0]
    rows = g.query(
        f"MATCH (m:Mem) RETURN {', '.join(MEM_FIELDS)} "
        "ORDER BY CASE WHEN m.status = 'IN' THEN 1 ELSE 0 END, m.created_at DESC, m.id LIMIT $n",
        {"n": int(limit)}).result_set
    nodes = {}
    for mid, labels, text, status, mtype, agent, run, amount, executed, at, created, gate, tool, args in rows:
        kind = _kind(labels)
        label = _action_label(tool, amount, args) if kind == "action" else _label(text)
        nodes[mid] = {"id": mid, "kind": kind, "label": _label(label), "status": status,
                      "mtype": mtype, "agent": agent, "run": run, "amount": amount,
                      "executed": bool(executed) if executed is not None else None,
                      "at": at, "created": created, "gate": gate, "tool": tool}
    ids = list(nodes)
    edges = []
    distrusted = {r[0] for r in g.query(
        "MATCH (r:Retraction {reinstated:false}) RETURN DISTINCT r.source").result_set}
    for sid, trust, skind, retracted in g.query(
            "MATCH (s:Source) RETURN s.id, s.trust, s.kind, s.retracted_at").result_set:
        nodes[sid] = {"id": sid, "kind": "source", "label": sid, "trust": trust, "skind": skind,
                      "retracted_at": retracted or ("distrusted" if sid in distrusted else None), "status": None}
    for sid, oid in fetch_all(g, "MATCH (s:Source)-[:SUPPORTS]->(o:Observation) WHERE o.id IN $ids "
                                 "RETURN s.id AS s, o.id AS o", {"ids": ids}, order_by="s, o"):
        edges.append({"s": sid, "t": oid, "type": "SUPPORTS"})
    for jid, rule, agent in g.query(
            "MATCH (j:Justification)-[:JUSTIFIES]->(m:Mem) WHERE m.id IN $ids RETURN DISTINCT j.id, j.rule, j.agent",
            {"ids": ids}).result_set:
        nodes[jid] = {"id": jid, "kind": "justification", "label": jid, "rule": rule, "agent": agent,
                      "status": None}
    for jid, mid in fetch_all(g, "MATCH (j:Justification)-[:JUSTIFIES]->(m:Mem) WHERE m.id IN $ids "
                                 "RETURN j.id AS j, m.id AS m", {"ids": ids}, order_by="j, m"):
        edges.append({"s": jid, "t": mid, "type": "JUSTIFIES"})
    for pid, jid in fetch_all(g, "MATCH (p:Mem)-[:PREMISE_OF]->(j:Justification)-[:JUSTIFIES]->(m:Mem) "
                                 "WHERE m.id IN $ids AND p.id IN $ids RETURN p.id AS p, j.id AS j",
                              {"ids": ids}, order_by="p, j"):
        edges.append({"s": pid, "t": jid, "type": "PREMISE_OF"})
    counts = {"mem": total, "shown": len(ids)}
    for st in ("IN", "OUT"):
        counts[st] = sum(1 for n in nodes.values() if n.get("status") == st)
    counts["tentative"] = sum(1 for n in nodes.values() if n.get("run"))
    return {"nodes": list(nodes.values()), "edges": edges, "counts": counts, "truncated": total > len(ids)}


def retractions(g):
    rows = g.query("MATCH (r:Retraction) RETURN r.id, r.source, r.from, r.to, r.reason, r.operator, r.at, "
                   "r.reinstated ORDER BY r.id").result_set
    out = []
    for rid, source, f, t, reason, op, at, reinstated in rows:
        n = g.query("MATCH (:Retraction {id:$id})-[e:RETRACTED]->(:Mem) WHERE e.flipped = true RETURN count(e)",
                    {"id": rid}).result_set[0][0]
        out.append({"id": rid, "source": source, "from": f, "to": t, "reason": reason, "operator": op,
                    "at": at, "reinstated": bool(reinstated), "flipped": n})
    return out


def _edge_key(e):
    return f"{e['s']}>{e['t']}:{e['type']}"


class Watcher:
    """Diffs successive snapshots into a change log: version -> {added nodes, added edges, updates}."""

    def __init__(self, graph, limit=3000, min_interval=0.3, keep=500):
        self.g, self.limit, self.min_interval = graph, limit, min_interval
        self.version, self._nodes, self._edges = 0, {}, set()
        self._log = deque(maxlen=keep)       # (version, change dict)
        self._last = 0.0
        self._lock = threading.Lock()
        self.counts, self.truncated = {}, False

    def refresh(self, force=False):
        with self._lock:
            now = time.monotonic()
            if not force and self.version and now - self._last < self.min_interval:
                return self.version
            self._last = now
            snap = snapshot(self.g, self.limit)
            self.counts, self.truncated = snap["counts"], snap["truncated"]
            cur = {n["id"]: n for n in snap["nodes"]}
            keys = {_edge_key(e): e for e in snap["edges"]}
            if self.version == 0:
                self._nodes, self._edges, self.version = cur, set(keys), 1
                return self.version
            added = [n for i, n in cur.items() if i not in self._nodes]
            added_edges = [e for k, e in keys.items() if k not in self._edges]
            updates = []
            for i, n in cur.items():
                old = self._nodes.get(i)
                if old is None:
                    continue
                diff = {f: n.get(f) for f in MUTABLE if n.get(f) != old.get(f)}
                if diff:
                    updates.append({"id": i, **diff})
            if added or added_edges or updates:
                self.version += 1
                self._log.append((self.version, {"nodes": added, "edges": added_edges, "updates": updates}))
            self._nodes, self._edges = cur, set(keys)
            return self.version

    def snapshot(self):
        self.refresh(force=True)
        with self._lock:
            return {"version": self.version, "nodes": list(self._nodes.values()),
                    "edges": [e for e in self._current_edges()], "counts": self.counts,
                    "truncated": self.truncated}

    def _current_edges(self):
        # edges are kept as a set of keys; rebuild dicts from the key (s>t:type)
        for k in sorted(self._edges):
            st, typ = k.rsplit(":", 1)
            s, t = st.split(">", 1)
            yield {"s": s, "t": t, "type": typ}

    def delta(self, since):
        """Changes after `since`; {"reset": True} when that version is no longer kept."""
        self.refresh()
        with self._lock:
            if since >= self.version:
                return {"version": self.version, "nodes": [], "edges": [], "updates": [], "counts": self.counts}
            if self._log and since < self._log[0][0] - 1:
                return {"version": self.version, "reset": True}
            out = {"version": self.version, "nodes": [], "edges": [], "updates": [], "counts": self.counts}
            for v, ch in self._log:
                if v > since:
                    out["nodes"] += ch["nodes"]
                    out["edges"] += ch["edges"]
                    out["updates"] += ch["updates"]
            return out
