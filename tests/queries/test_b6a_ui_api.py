"""B6a: UI shell backend (snapshot, change feed, node details, static files).
Acceptance: python tasks.py accept B6A   (the canvas itself is checked in a browser; the pure JS logic
runs under `node --test tests/ui`, wrapped by tests/ui/test_js_logic.py)."""
import json
import urllib.error
import urllib.request

import pytest

from core.db import connect
from core.memory import MemoryService
from core.retract.cascade import distrust
from core.retrieve.embed import get_embedder
from core.retrieve.q2 import embed_graph
from data.generator import generate
from data.httpkit import serve
from data.load_fixture import load
from ui.shell import graphdata
from ui.shell.server import Shell

pytestmark = pytest.mark.b6a

SPEC = generate(seed=7, vendors=2, audit_incident=True)
WIN = SPEC["window"]


def get(url):
    try:
        with urllib.request.urlopen(url) as r:
            body = r.read()
            ctype = r.headers["Content-Type"]
            return r.status, ctype, (json.loads(body) if ctype.startswith("application/json") else body.decode())
    except urllib.error.HTTPError as e:
        return e.code, e.headers["Content-Type"], json.loads(e.read())


@pytest.fixture()
def ui():
    g = load(SPEC, graph_name="test_b6a")
    shell = Shell(db=connect(), default_graph="test_b6a", min_interval=0)
    srv, url = serve(shell.router())
    yield g, shell, url
    srv.shutdown()


def test_page_and_static_assets(ui):
    _, _, url = ui
    st, ctype, html = get(url + "/graph")          # `/` is the front page (ui/home)
    assert st == 200 and ctype.startswith("text/html") and "<canvas" in html and "app.js" in html
    for name in ("app.js", "store.js", "layout.js", "style.css"):
        st, ctype, body = get(f"{url}/static/{name}")
        assert st == 200 and len(body) > 200, name
    assert get(url + "/static/app.js")[1].startswith("application/javascript") or \
           get(url + "/static/app.js")[1].startswith("text/javascript")
    assert get(url + "/static/..%2Fserver.py")[0] == 404
    assert get(url + "/static/nope.js")[0] == 404


def test_graph_listing_and_snapshot_shape(ui):
    g, _, url = ui
    st, _, graphs = get(url + "/api/graphs")
    assert st == 200 and "test_b6a" in [x["name"] for x in graphs]
    st, _, snap = get(url + "/api/graph?graph=test_b6a")
    assert st == 200 and snap["graph"] == "test_b6a" and snap["version"] >= 1
    nodes = {n["id"]: n for n in snap["nodes"]}
    kinds = {n["kind"] for n in nodes.values()}
    assert {"source", "observation", "belief", "plan", "action", "justification"} <= kinds
    assert snap["counts"]["mem"] == len([n for n in nodes.values() if n["kind"] not in ("source", "justification")])
    for e in snap["edges"]:
        assert e["s"] in nodes and e["t"] in nodes, e
        assert e["type"] in ("SUPPORTS", "PREMISE_OF", "JUSTIFIES")
    assert not any("embedding" in n for n in nodes.values())
    labels = {n["label"] for n in nodes.values() if n["kind"] == "action"}
    assert any(lbl.startswith("pay ") for lbl in labels)         # readable, not raw JSON
    assert not any(lbl.startswith("{") for lbl in labels)
    proc = [n for n in nodes.values() if n.get("mtype") == "procedural"]
    assert proc and proc[0]["status"] == "IN"


def test_delta_reports_new_memory_and_status_flips(ui):
    g, shell, url = ui
    v0 = get(url + "/api/graph?graph=test_b6a")[2]["version"]
    assert get(f"{url}/api/delta?graph=test_b6a&since={v0}")[2]["nodes"] == []

    emb = get_embedder("hash")
    embed_graph(g, emb)
    m = MemoryService(g, emb)
    m.begin_turn("analyst")
    m.recall("Coastal Produce remit address", "analyst", k=1, contains="Coastal")
    new = m.remember("Remit address verified for the quarterly run.", "belief", "analyst")
    st, _, d = get(f"{url}/api/delta?graph=test_b6a&since={v0}")
    assert st == 200 and d["version"] > v0
    assert new["node_id"] in [n["id"] for n in d["nodes"]]
    assert any(e["t"] == new["node_id"] and e["type"] == "JUSTIFIES" for e in d["edges"])
    assert any(e["type"] == "PREMISE_OF" for e in d["edges"])

    v1 = d["version"]
    res = distrust(g, WIN["source"], WIN["from"], WIN["to"])
    st, _, d = get(f"{url}/api/delta?graph=test_b6a&since={v1}")
    flipped = {u["id"] for u in d["updates"] if u.get("status") == "OUT"}
    assert flipped == set(res["flipped_ids"])
    assert d["counts"]["OUT"] == len(res["flipped_ids"])
    # the distrusted source is marked, and a second poll with the new version is empty
    assert any(u["id"] == WIN["source"] and u.get("retracted_at") for u in d["updates"])
    assert get(f"{url}/api/delta?graph=test_b6a&since={d['version']}")[2]["updates"] == []


def test_delta_is_a_pure_function_of_version_and_resets_when_too_old(ui):
    g, shell, _ = ui
    w = graphdata.Watcher(g, min_interval=0, keep=2)
    w.refresh(force=True)
    for i in range(4):
        g.query("CREATE (:Mem:Belief {id:$i, text:'extra', status:'IN', agent:'x'})", {"i": f"extra_{i}"})
        w.refresh(force=True)
    assert w.delta(0).get("reset") is True
    assert w.delta(w.version - 1)["nodes"] != [] and "reset" not in w.delta(w.version - 1)


def test_node_details_have_the_justification_tree_and_fragility(ui):
    g, _, url = ui
    pid = g.query("MATCH (p:Plan) WHERE p.text CONTAINS 'INV-COASTAL-2' RETURN p.id").result_set[0][0]
    st, _, d = get(f"{url}/api/node?graph=test_b6a&id={pid}")
    assert st == 200 and d["why"]["id"] == pid and d["why"]["justifications"]
    assert d["fragility"]["independent_sources"] >= 1 and d["fragility"]["bound"] in ("exact", "upper")
    distrust(g, WIN["source"], WIN["from"], WIN["to"])
    d = get(f"{url}/api/node?graph=test_b6a&id={pid}")[2]
    assert d["why"]["status"] == "OUT" and d["fragility"]["independent_sources"] == 0


def test_errors_use_the_contract_shape(ui):
    _, _, url = ui
    st, _, e = get(url + "/api/node?graph=test_b6a&id=does_not_exist")
    assert st == 404 and e["error"]["code"] == "NOT_FOUND"
    st, _, e = get(url + "/api/graph?graph=no_such_graph")
    assert st == 404 and e["error"]["code"] == "NOT_FOUND" and "available" in e["error"]["details"]
    st, _, e = get(url + "/api/delta?graph=test_b6a&since=abc")
    assert st == 400 and e["error"]["code"] == "INVALID_ARGUMENT"
    st, _, e = get(url + "/api/node?graph=test_b6a")
    assert st == 400


def test_large_graphs_are_truncated_keeping_retracted_nodes(ui):
    g, _, _ = ui
    res = distrust(g, WIN["source"], WIN["from"], WIN["to"])
    snap = graphdata.snapshot(g, limit=12)
    mem = [n for n in snap["nodes"] if n["kind"] not in ("source", "justification")]
    assert snap["truncated"] is True and len(mem) == 12
    # retracted nodes are kept first: all of them (up to the limit) survive the cut
    assert sum(1 for n in mem if n["status"] == "OUT") == min(12, len(res["flipped_ids"]))
    ids = {n["id"] for n in snap["nodes"]}
    assert all(e["s"] in ids and e["t"] in ids for e in snap["edges"])


def test_retraction_audit_trail(ui):
    g, _, url = ui
    assert get(url + "/api/retractions?graph=test_b6a")[2]["retractions"] == []
    res = distrust(g, WIN["source"], WIN["from"], WIN["to"])
    r = get(url + "/api/retractions?graph=test_b6a")[2]["retractions"]
    assert [x["id"] for x in r] == [res["retraction_id"]]
    assert r[0]["source"] == WIN["source"] and r[0]["flipped"] == len(res["flipped_ids"]) and not r[0]["reinstated"]
