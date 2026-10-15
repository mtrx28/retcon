"""B6b: fragility radar data (poisoning cost over many nodes) served to the UI.
Acceptance: python tasks.py accept B6B"""
import json
import urllib.error
import urllib.request

import pytest

from core.db import connect
from core.retract.cascade import distrust
from data.generator import generate
from data.httpkit import serve
from data.load_fixture import load
from ui.shell.server import Shell

pytestmark = pytest.mark.b6b

SPEC = generate(seed=7, vendors=2, audit_incident=True)
WIN = SPEC["window"]


def get(url):
    try:
        with urllib.request.urlopen(url) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


@pytest.fixture()
def ui():
    g = load(SPEC, graph_name="test_b6b")
    shell = Shell(db=connect(), default_graph="test_b6b", min_interval=0)
    srv, url = serve(shell.router())
    yield g, shell, url
    srv.shutdown()


def test_decisions_are_scored_cheapest_to_poison_first(ui):
    _, _, url = ui
    st, d = get(url + "/api/fragility?graph=test_b6b")
    assert st == 200 and d["policy"] == {"min": 2, "over_amount": 10000}
    items = d["items"]
    assert items and {i["kind"] for i in items} <= {"plan", "action"}
    costs = [i["independent_sources"] for i in items]
    assert costs == sorted(costs)
    pending = next(i for i in items if i["kind"] == "action" and i["executed"] is False)
    assert pending["independent_sources"] == 1 and pending["bound"] == "exact" and pending["cut_set"]
    assert pending["label"].startswith("pay ")


def test_independently_supported_claims_score_higher(ui):
    _, _, url = ui
    d = get(url + "/api/fragility?graph=test_b6b&kinds=belief&limit=200")[1]
    by_label = {i["label"]: i for i in d["items"]}
    addr = next(i for l, i in by_label.items() if l.startswith("Coastal Produce remit address"))
    assert addr["independent_sources"] == 2 and addr["justifications"] == 2     # portal OR signed contract
    assert addr["independent_sources"] >= d["policy"]["min"]


def test_radar_shrinks_to_the_survivors_after_a_retraction(ui):
    g, _, url = ui
    before = get(url + "/api/fragility?graph=test_b6b")[1]
    res = distrust(g, WIN["source"], WIN["from"], WIN["to"])
    after = get(url + "/api/fragility?graph=test_b6b")[1]
    gone = set(res["flipped_ids"]) & {i["id"] for i in before["items"]}
    assert gone and not gone & {i["id"] for i in after["items"]}
    assert after["version"] > before["version"]
    assert all(i["independent_sources"] >= 1 for i in after["items"])          # only live nodes are scored


def test_results_are_cached_per_graph_version(ui):
    _, shell, url = ui
    a = get(url + "/api/fragility?graph=test_b6b")[1]
    key = next(iter(shell._frag_cache))
    cached = shell._frag_cache[key]
    b = get(url + "/api/fragility?graph=test_b6b")[1]
    assert a == b and shell._frag_cache[key] is cached


def test_bad_arguments(ui):
    _, _, url = ui
    st, e = get(url + "/api/fragility?graph=test_b6b&kinds=nonsense")
    assert st == 400 and e["error"]["code"] == "INVALID_ARGUMENT"
    st, e = get(url + "/api/fragility?graph=test_b6b&limit=abc")
    assert st == 400


def test_radar_script_is_served(ui):
    _, _, url = ui
    with urllib.request.urlopen(url + "/static/radar.js") as r:
        body = r.read().decode()
        assert r.status == 200 and "Fragility radar" in body
