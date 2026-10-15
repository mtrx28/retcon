"""Load a scenario/fixture JSON (docs/CONTRACT.md section 8) into graph tenant_<tenant>.

Usage: python -m data.load_fixture [path]   (default: data/fixtures/ap_tiny.json)
"""
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from falkordb import FalkorDB

SCHEMA = Path(__file__).resolve().parent.parent / "core" / "schema.cypher"
FLOW_CAP = 1_000_000
MTYPES = ("episodic", "semantic", "procedural")
DOMAINS = ("ap", "science")
SOURCE_OPTIONAL = ("retracted_at", "rw_reason", "title", "doi")  # contract v1.1 science sources (+ display fields)


def epoch(iso):
    return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()) if iso else None


def connect():
    return FalkorDB(host=os.getenv("FALKORDB_HOST", "localhost"),
                    port=int(os.getenv("FALKORDB_PORT", "6379")))


def validate_spec(spec, require_ground_truth=False):
    """Check the optional contract v1.1 fields. Raises ValueError. Missing fields are fine."""
    if spec.get("domain", "ap") not in DOMAINS:
        raise ValueError(f"domain must be one of {DOMAINS}, got {spec['domain']!r}")
    for d in spec.get("derivations", []):
        m = d["conclusion"].get("mtype")
        if m is not None and m not in MTYPES:
            raise ValueError(f"mtype of {d['conclusion']['id']!r} must be one of {MTYPES}, got {m!r}")
    if require_ground_truth:
        gt = spec.get("ground_truth") or {}
        for k in ("contaminated", "truly_supported"):
            if k not in gt:
                raise ValueError(f"ground_truth.{k} is required")


def load(spec, db=None, graph_name=None):
    """Recreate the tenant graph from spec and return it."""
    validate_spec(spec)
    db = db or connect()
    name = graph_name or f"tenant_{spec['tenant']}"
    try:
        db.select_graph(name).delete()
    except Exception:
        pass
    g = db.select_graph(name)
    for line in SCHEMA.read_text().splitlines():
        if line.strip() and not line.startswith("//"):
            g.query(line)
    q = g.query

    for s in spec["sources"]:
        extra = {k: s[k] for k in SOURCE_OPTIONAL if s.get(k) is not None}
        q("CREATE (src:Source {id:$id, kind:$kind, trust:$trust}) SET src += $extra",
          {"id": s["id"], "kind": s["kind"], "trust": s["trust"], "extra": extra})
    for a in spec["agents"]:
        q("CREATE (:Agent {id:$id, role:$role, tenant:$t})", {**a, "t": spec["tenant"]})
    for o in spec["observations"]:
        q("MATCH (s:Source {id:$src}) "
          "CREATE (o:Mem:Observation {id:$id, text:$text, status:'IN', observed_at:$at, agent:'intake', "
          "mtype:'episodic'}) "
          "CREATE (s)-[:SUPPORTS]->(o) "
          "CREATE (s)-[:FLOW {cap:1}]->(o) "
          "CREATE (o)-[:DEPENDS_ON]->(s)",
          {"src": o["source"], "id": o["id"], "text": o["text"], "at": epoch(o["observed_at"])})

    # Create every conclusion node before any justification: premises may reference conclusions
    # defined later (circular support), and a missing premise would make a justification vacuous.
    created = set()
    for d in spec["derivations"]:
        c = d["conclusion"]
        if c["id"] not in created:
            label = "Plan" if c["kind"] == "plan" else "Belief"
            mtype = c.get("mtype") or ("semantic" if label == "Belief" else None)
            q(f"CREATE (m:Mem:{label} {{id:$id, text:$text, status:'IN', agent:$agent}}) "
              "SET m += $extra",
              {"id": c["id"], "text": c["text"], "agent": d["agent"],
               "extra": {"mtype": mtype} if mtype else {}})
            created.add(c["id"])
    for a in spec["actions"]:
        q("CREATE (:Mem:Action {id:$id, tool:$tool, amount:$amount, executed:$ex, executed_at:$at, "
          "status:'IN', agent:$agent, text:$text})",
          {"id": a["id"], "tool": a["tool"], "amount": a["amount"], "ex": a["executed"],
           "at": epoch(a["executed_at"]), "agent": a["agent"], "text": f"{a['tool']} {a['amount']}"})

    for d in spec["derivations"]:
        _justify(q, d["id"], d["rule"], d["agent"], d["premises"], d["conclusion"]["id"])
        q("MATCH (a:Agent {id:$a}), (m:Mem {id:$m}) MERGE (a)-[:HOLDS]->(m)",
          {"a": d["agent"], "m": d["conclusion"]["id"]})
    for a in spec["actions"]:
        _justify(q, f"j_{a['id']}", "combine", a["agent"], a["premises"], a["id"])
        q("MATCH (a:Agent {id:$a}), (m:Mem {id:$m}) MERGE (a)-[:HOLDS]->(m)",
          {"a": a["agent"], "m": a["id"]})
    return g


def _justify(q, jid, rule, agent, premises, conclusion):
    q("MATCH (c:Mem {id:$c}) "
      "CREATE (j:Justification {id:$j, rule:$rule, agent:$agent})-[:JUSTIFIES]->(c)",
      {"j": jid, "rule": rule, "agent": agent, "c": conclusion})
    for p in premises:
        if not q("MATCH (p:Mem {id:$p}) RETURN p.id", {"p": p}).result_set:
            raise ValueError(f"fixture error: premise {p!r} of {jid!r} does not exist")
        q("MATCH (p:Mem {id:$p}), (j:Justification {id:$j}), (c:Mem {id:$c}) "
          "CREATE (p)-[:PREMISE_OF]->(j) "
          "MERGE (p)-[f:FLOW]->(c) SET f.cap = $cap "
          "MERGE (c)-[:DEPENDS_ON]->(p)",
          {"p": p, "j": jid, "c": conclusion, "cap": FLOW_CAP})


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    path = Path(args[0]) if args else Path(__file__).parent / "fixtures" / "ap_tiny.json"
    spec = json.loads(path.read_text(encoding="utf8"))
    validate_spec(spec, require_ground_truth=True)
    g = load(spec)
    n = g.query("MATCH (m:Mem) RETURN count(m)").result_set[0][0]
    print(f"loaded tenant_{spec['tenant']}: {n} Mem nodes")
