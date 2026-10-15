"""B4a: scenario generator, fake portal, mock bank, sandbox inbox. Acceptance: python tasks.py accept B4A"""
import json
import urllib.request

import pytest

from data.bank import MockBank
from data.generator import generate, reference_labels, validate, vendors_for_nodes
from data.httpkit import serve
from data.inbox import SandboxInbox
from data.load_fixture import epoch, load
from data.portal import Portal
from data.sandbox import build

pytestmark = pytest.mark.b4a


def mem_count(spec):
    return (len(spec["observations"]) + len({d["conclusion"]["id"] for d in spec["derivations"]})
            + len(spec["actions"]))


# ---- generator -------------------------------------------------------------------------------

def test_seeded_and_valid():
    a, b = generate(seed=7, vendors=3), generate(seed=7, vendors=3)
    assert json.dumps(a) == json.dumps(b)
    assert json.dumps(a) != json.dumps(generate(seed=8, vendors=3))
    assert validate(a) == []


def test_one_vendor_has_the_fixture_shape():
    s = generate(seed=7, vendors=1)
    assert mem_count(s) == 24  # same size as ap_tiny.json
    gt = s["ground_truth"]
    assert len(gt["recall_list"]) == 1 and len(gt["blocked"]) == 1
    assert any(a["executed"] for a in s["actions"]) and any(not a["executed"] for a in s["actions"])
    # corroborated belief: two justifications for one conclusion, one of them from the contract
    addr = [d for d in s["derivations"] if d["conclusion"]["id"].endswith("_b_addr")]
    assert len(addr) == 2
    assert f"{addr[0]['conclusion']['id'][:-7]}_b_addr" in gt["truly_supported"]
    # circular pair is present and fully contaminated
    assert {"coastal_b_circ_a", "coastal_b_circ_b"} <= set(gt["contaminated"])


def test_only_poisoned_vendors_are_contaminated():
    s = generate(seed=3, vendors=4, poisoned=1)
    assert all(i.startswith("coastal_") for i in s["ground_truth"]["contaminated"])
    s2 = generate(seed=3, vendors=4, poisoned=2)
    assert {i.split("_")[0] for i in s2["ground_truth"]["contaminated"]} == {"coastal", "v001"}


def test_window_is_respected():
    s = generate(seed=7, vendors=1)
    dead = set(s["ground_truth"]["contaminated"])
    assert "coastal_o_hours" not in dead and "coastal_o_closure" not in dead  # portal, outside window
    assert {"coastal_o_bank_new", "coastal_o_addr_portal"} <= dead


def test_scale_target():
    for target in (1000, 10000):
        n = mem_count(generate(seed=1, vendors=vendors_for_nodes(target)))
        assert abs(n - target) / target < 0.05, (target, n)


def test_ground_truth_matches_the_live_engine():
    """The reference JTMS and FalkorDB (Q3-Q5 from docs/SPIKE.md) must agree on every node."""
    spec = generate(seed=11, vendors=3)
    g = load(spec, graph_name="test_b4a")
    poisoned = [v["portal_source"] for v in spec["vendors"] if v["compromised"]]
    for src in poisoned:
        g.query("MATCH (s:Source {id:$s})-[:SUPPORTS]->(o:Observation) "
                "WHERE o.observed_at >= $f AND o.observed_at <= $t SET o.status='OUT', o.run='r'",
                {"s": src, "f": epoch(spec["window"]["from"]), "t": epoch(spec["window"]["to"])})
    g.query("MATCH (o:Observation {run:'r'})-[:PREMISE_OF|JUSTIFIES*1..12]->(x:Mem) "
            "WHERE x.status='IN' WITH DISTINCT x SET x.status='OUT', x.run='r'")
    while g.query(
            "MATCH (j:Justification)-[:JUSTIFIES]->(b:Mem {status:'OUT', run:'r'}) "
            "OPTIONAL MATCH (p:Mem {status:'OUT'})-[:PREMISE_OF]->(j) "
            "WITH b, j, count(p) AS dead WHERE dead = 0 "
            "WITH DISTINCT b SET b.status='IN', b.run=null RETURN b.id").result_set:
        pass
    out = {r[0] for r in g.query("MATCH (m:Mem {status:'OUT'}) RETURN m.id").result_set}
    assert out == set(spec["ground_truth"]["contaminated"])
    assert out == reference_labels(spec)[1]


# ---- portal ----------------------------------------------------------------------------------

def test_portal_replays_by_clock():
    spec = generate(seed=7, vendors=2)
    p = Portal(spec)
    before = p.visible("coastal", "2026-10-04T00:00:00Z")
    after = p.visible("coastal", "2026-10-06T00:00:00Z")
    assert "coastal_o_bank_new" not in {f["obs_id"] for f in before}
    assert "coastal_o_bank_new" in {f["obs_id"] for f in after}
    assert "data-obs-id=\"coastal_o_bank_new\"" in p.page("coastal")
    assert p.page("v001") != p.page("coastal")


# ---- bank ------------------------------------------------------------------------------------

def test_bank_pay_idempotent_and_recall():
    b = MockBank({"coastal": "SYN-1111-0001"})
    st, p = b.pay("coastal", "SYN-9999-0001", 18400, "INV-1", "k1")
    assert st == 201 and p["id"] == "pay_0001" and p["iban_matches_contract"] is False
    assert b.pay("coastal", "SYN-9999-0001", 18400, "INV-1", "k1") == (200, p) and len(b.payments) == 1
    st, r = b.recall("pay_0001", "portal compromised")
    assert st == 200 and r["status"] == "recalled"
    assert b.recall("pay_0001")[0] == 409
    assert b.pay("coastal", "x", -5)[1]["error"]["code"] == "INVALID_ARGUMENT"
    assert b.pay("nobody", "x", 5)[1]["error"]["code"] == "NOT_FOUND"
    assert b.recall("pay_9999")[1]["error"]["code"] == "NOT_FOUND"


# ---- inbox -----------------------------------------------------------------------------------

def test_inbox_inbound_and_outbound_capture():
    spec = generate(seed=7, vendors=3)
    box = SandboxInbox.from_spec(spec)
    assert len(box.inbound) == 1 and "SYN-" in box.inbound[0]["body"]
    box.send("ar@coastal.example.test", "Hold", "Payment on hold.", agent="comms")
    assert box.outbox[0]["agent"] == "comms"


# ---- all three over real HTTP ----------------------------------------------------------------

def call(url, body=None):
    req = urllib.request.Request(url, data=None if body is None else json.dumps(body).encode(),
                                 method="GET" if body is None else "POST")
    try:
        with urllib.request.urlopen(req) as r:
            data = r.read().decode()
            return r.status, (json.loads(data) if r.headers["Content-Type"].startswith("application/json") else data)
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_sandbox_over_http():
    spec = generate(seed=7, vendors=2)
    router, _ = build(spec)
    srv, url = serve(router)
    try:
        st, vendors = call(f"{url}/portal/vendors")
        assert st == 200 and [v["id"] for v in vendors] == ["coastal", "v001"]
        st, html = call(f"{url}/portal/vendors/coastal?as_of=2026-10-06T00:00:00Z")
        assert st == 200 and "SYN-" in html
        assert call(f"{url}/portal/vendors/ghost")[0] == 404
        st, p = call(f"{url}/bank/payments", {"vendor": "coastal", "iban": "SYN-9999-0001", "amount": 100})
        assert st == 201 and call(f"{url}/bank/payments/{p['id']}/recall", {})[1]["status"] == "recalled"
        assert call(f"{url}/bank/accounts/coastal")[1]["iban"] == spec["vendors"][0]["iban_on_contract"]
        assert call(f"{url}/mail/outbox", {"to": "a@b.test"})[0] == 400
        assert call(f"{url}/mail/outbox", {"to": "a@b.test", "subject": "s", "body": "b"})[0] == 201
        assert len(call(f"{url}/mail/inbox")[1]) == 1
    finally:
        srv.shutdown()
