"""Contradictions between beliefs, and their clusters (task A12).

    link_contradictions(g)    find conflicting beliefs and record `(a)-[:CONTRADICTS {...}]->(b)` (idempotent)
    contradiction_clusters(g) weakly connected components over CONTRADICTS only (`algo.WCC`), size >= 2

A detector is a rule that reads belief text and returns (subject, attribute, value). Two beliefs with the
same subject and attribute but different values contradict. The rules below cover the accounts-payable
domain (a vendor's bank account, a remit address); another domain adds patterns, and anything smarter
(an NLI model, a threat-intel feed, A-MemGuard-style consistency checks) can call `add_contradiction`.

The edge is only a *record*: it never changes IN/OUT. A cluster is "resolved" when at most one of the
conflicting values is still IN, which is what a retraction of the bad side produces.
"""
import re
import time

PATTERNS = [
    ("bank", re.compile(r"^(?P<subject>.+?) bank account is IBAN (?P<value>SYN-\d{4}-\d{4})\.?$")),
    ("bank", re.compile(r"^Contract bank for (?P<subject>.+?) is IBAN (?P<value>SYN-\d{4}-\d{4})\.?$")),
    ("address", re.compile(r"^(?P<subject>.+?) remit address is (?P<value>.+?)\.?$")),
]


def facts(text: str):
    """(subject, attribute, value) or None."""
    for attribute, rx in PATTERNS:
        m = rx.match(text.strip())
        if m:
            return m["subject"].strip().lower(), attribute, m["value"].strip().lower()
    return None


def detect(g) -> list[dict]:
    """Conflicting belief pairs, any status (history is kept). Deterministic order."""
    rows = g.query("MATCH (b:Belief) WHERE b.text IS NOT NULL RETURN b.id, b.text ORDER BY b.id").result_set
    groups: dict[tuple, dict[str, list[str]]] = {}
    for bid, text in rows:
        f = facts(text)
        if f:
            subject, attribute, value = f
            groups.setdefault((subject, attribute), {}).setdefault(value, []).append(bid)
    pairs = []
    for (subject, attribute), values in sorted(groups.items()):
        vals = sorted(values)
        for i, va in enumerate(vals):
            for vb in vals[i + 1:]:
                for a in values[va]:
                    for b in values[vb]:
                        x, y = sorted((a, b))
                        pairs.append({"a": x, "b": y, "subject": subject, "attribute": attribute,
                                      "values": [va, vb]})
    return pairs


def add_contradiction(g, a: str, b: str, subject: str = "", attribute: str = "", detector: str = "rule") -> int:
    """Record one contradiction (idempotent). Returns 1 if a new edge was created."""
    a, b = sorted((a, b))
    before = g.query("MATCH (:Mem {id:$a})-[c:CONTRADICTS]->(:Mem {id:$b}) RETURN count(c)",
                     {"a": a, "b": b}).result_set[0][0]
    g.query("MATCH (x:Mem {id:$a}), (y:Mem {id:$b}) MERGE (x)-[c:CONTRADICTS]->(y) "
            "ON CREATE SET c.subject = $s, c.attribute = $t, c.detector = $d, c.at = $now",
            {"a": a, "b": b, "s": subject, "t": attribute, "d": detector, "now": int(time.time())})
    return 0 if before else 1


def link_contradictions(g) -> dict:
    found = detect(g)
    created = sum(add_contradiction(g, p["a"], p["b"], p["subject"], p["attribute"]) for p in found)
    return {"found": len(found), "created": created}


def contradiction_clusters(g, link: bool = True) -> list[dict]:
    """Clusters of mutually conflicting beliefs, largest first. `link=True` refreshes the edges first."""
    if link:
        link_contradictions(g)
    if not g.query("MATCH ()-[c:CONTRADICTS]->() RETURN count(c)").result_set[0][0]:
        return []                     # algo.WCC raises on a relationship type that does not exist yet
    comp = {}
    for nid, cid in g.query(
            "CALL algo.WCC({nodeLabels:['Mem'], relationshipTypes:['CONTRADICTS']}) YIELD node, componentId "
            "RETURN node.id, componentId").result_set:
        comp.setdefault(cid, []).append(nid)
    clusters = []
    for cid, ids in comp.items():
        if len(ids) < 2:
            continue
        rows = g.query(
            "MATCH (m:Mem) WHERE m.id IN $ids "
            "OPTIONAL MATCH (s:Source)-[:SUPPORTS]->(:Observation)-[:PREMISE_OF|JUSTIFIES*1..12]->(m) "
            "RETURN m.id, m.text, m.status, m.agent, collect(DISTINCT s.id)", {"ids": ids}).result_set
        members = []
        for mid, text, status, agent, srcs in sorted(rows, key=lambda r: r[0]):
            f = facts(text or "")
            members.append({"id": mid, "text": text, "status": status, "agent": agent,
                            "value": f[2] if f else None, "sources": sorted(s for s in srcs if s)})
        live_values = {m["value"] for m in members if m["status"] == "IN" and m["value"] is not None}
        edge = g.query("MATCH (a:Mem)-[c:CONTRADICTS]->(b:Mem) WHERE a.id IN $ids "
                       "RETURN c.subject, c.attribute LIMIT 1", {"ids": ids}).result_set
        clusters.append({"size": len(members), "subject": edge[0][0] if edge else None,
                         "attribute": edge[0][1] if edge else None, "members": members,
                         "resolved": len(live_values) <= 1,
                         "live_values": sorted(live_values)})
    clusters.sort(key=lambda c: (-c["size"], c["members"][0]["id"]))
    for i, c in enumerate(clusters, 1):
        c["id"] = f"cluster_{i}"
    return clusters
