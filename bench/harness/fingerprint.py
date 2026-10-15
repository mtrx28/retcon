"""A canonical, order-independent dump of a graph, and its hash. Used to prove two loads are the same
graph (batched loader vs data.load_fixture.load) and that one tenant's graph is untouched by work in
another (B11). Embeddings and wall-clock stamps are excluded: they are not part of the memory's logic."""
import hashlib
import json

from core.db import fetch_all

VOLATILE = {"embedding", "created_at"}


def _clean(props, drop=()):
    return {k: v for k, v in props.items() if k not in VOLATILE and k not in drop and v is not None}


def dump(g, drop=()):
    nodes = []
    for labels, props, _ in fetch_all(g, "MATCH (n) RETURN labels(n), properties(n), id(n) AS _i", order_by="_i"):
        nodes.append({"labels": sorted(labels), "props": _clean(props, drop)})
    edges = []
    for s, t, typ, props, _ in fetch_all(
            g, "MATCH (a)-[r]->(b) RETURN a.id, b.id, type(r), properties(r), id(r) AS _i", order_by="_i"):
        edges.append({"s": s, "t": t, "type": typ, "props": _clean(props, drop)})

    def key(x):
        return json.dumps(x, sort_keys=True, default=str)

    return {"nodes": sorted(nodes, key=key), "edges": sorted(edges, key=key)}


def fingerprint(g, drop=()):
    d = dump(g, drop)
    h = hashlib.sha256(json.dumps(d, sort_keys=True, default=str).encode("utf8")).hexdigest()
    return {"sha256": h, "nodes": len(d["nodes"]), "edges": len(d["edges"])}
