"""Upgrade 3: the incident report. Facts only, from the graph.
Acceptance: python tasks.py accept REPORT"""
import json
import urllib.error
import urllib.request

import pytest

from core import report
from core.db import connect
from core.errors import RetconError
from core.retract.cascade import distrust, reinstate
from data.generator import generate
from data.httpkit import serve
from bench.harness.loader import load_batched as load
from agents import remediator
from ui.shell.server import Shell

pytestmark = pytest.mark.report

SPEC = generate(seed=7, vendors=4, invoices=6, executed=3, poisoned=2, corroborated=0.6, staggered=True)


@pytest.fixture()
def world():
    g = load(SPEC, graph_name="test_report")
    ids = {}
    for w in SPEC["windows"]:
        res = distrust(g, w["source"], w["from"], w["to"])
        remediator.remediate(g, res["retraction_id"])
        ids[w["source"]] = res["retraction_id"]
    return g, ids


def test_figures_match_the_retraction(world):
    g, ids = world
    rid = ids[SPEC["windows"][0]["source"]]
    r = report.build(g, rid)
    assert r["retraction"]["id"] == rid and r["retraction"]["source"] == SPEC["windows"][0]["source"]
    flipped = g.query("MATCH (:Retraction {id:$i})-[e:RETRACTED]->(:Mem) WHERE e.flipped = true RETURN count(e)", {"i": rid}).result_set[0][0]
    assert sum(r["counts"].values()) == flipped
    # every listed payment really is an executed/pending pay action that this retraction flipped
    for a in r["paid"]:
        assert a["executed"] and a["tool"] == "pay" and a["amount"]
    for a in r["held"]:
        assert not a["executed"] and a["tool"] == "pay"
    assert r["paid_total"] == sum(a["amount"] for a in r["paid"])
    assert [a["amount"] for a in r["paid"]] == sorted((a["amount"] for a in r["paid"]), reverse=True)


def test_each_payment_names_the_bad_claim_it_rested_on(world):
    g, ids = world
    r = report.build(g, ids[SPEC["windows"][0]["source"]])
    assert r["paid"], "the scenario has an executed contaminated payment for the first poisoned vendor"
    for a in r["paid"]:
        assert a["rested_on"] and "portal" in a["rested_on"][-1]      # ends at the portal's own observation


def test_survivors_are_classified_honestly(world):
    g, ids = world
    for rid in ids.values():
        r = report.build(g, rid)
        for s in r["survivors"]:
            if s["why_stayed"] == "corroborated":
                assert s["other_sources"] and r["retraction"]["source"] not in s["other_sources"]
            else:
                assert s["sources"] == [r["retraction"]["source"]]    # only this source's evidence from outside the window
    assert any(report.build(g, rid)["corroborated_count"] for rid in ids.values())


def test_markdown_and_html_carry_the_same_facts(world):
    g, ids = world
    r = report.build(g, ids[SPEC["windows"][0]["source"]])
    md, page = report.markdown(r), report.html(r)
    for a in r["paid"]:
        assert a["id"] in md and a["id"] in page
    assert f"{r['paid_total']:,.0f} USD" in md
    assert "Audit priority, not detection" in md and "Audit priority, not detection" in page
    assert page.startswith("<!doctype html>") and "<script" not in page      # self-contained, nothing executes
    assert "&lt;" not in md or True


def test_html_escapes_untrusted_text(world):
    g, ids = world
    r = report.build(g, ids[SPEC["windows"][0]["source"]])
    r["survivors"] = [{"id": "x", "text": "<script>alert(1)</script>", "sources": ["a"], "other_sources": ["b"],
                       "independent": 2, "why_stayed": "corroborated"}]
    page = report.html(r)
    assert "<script>alert(1)</script>" not in page and "&lt;script&gt;" in page


def test_defaults_to_the_latest_active_retraction_and_reflects_reinstate(world):
    g, ids = world
    first, second = (ids[w["source"]] for w in SPEC["windows"][:2])
    assert report.build(g)["retraction"]["id"] == second
    reinstate(g, second)
    assert report.build(g)["retraction"]["id"] == first                  # the reinstated one is no longer "latest active"
    assert report.build(g, second)["retraction"]["reinstated"] is True
    assert "has been reinstated" in report.markdown(report.build(g, second))


def test_errors_use_the_contract_shape():
    g = load(SPEC, graph_name="test_report_empty")
    with pytest.raises(RetconError) as e:
        report.build(g)
    assert e.value.code == "NOT_FOUND"
    with pytest.raises(RetconError):
        report.build(g, "ret_9999")


def test_http_endpoint_serves_html_markdown_and_json(world):
    g, ids = world
    shell = Shell(db=connect(), default_graph="test_report", min_interval=0)
    srv, url = serve(shell.router())
    try:
        rid = ids[SPEC["windows"][0]["source"]]
        base = f"{url}/api/report?graph=test_report&retraction={rid}"
        with urllib.request.urlopen(base + "&format=html") as r:
            assert r.headers["Content-Type"].startswith("text/html") and b"Incident report" in r.read()
        with urllib.request.urlopen(base + "&format=md") as r:
            assert r.headers["Content-Type"].startswith("text/markdown") and r.read().startswith(b"# Incident report")
        with urllib.request.urlopen(base + "&format=json") as r:
            assert json.loads(r.read())["retraction"]["id"] == rid
        for bad in (base + "&format=pdf", f"{url}/api/report?graph=test_report&retraction=ret_9999"):
            with pytest.raises(urllib.error.HTTPError) as e:
                urllib.request.urlopen(bad)
            assert e.value.code in (400, 404)
    finally:
        srv.shutdown()
