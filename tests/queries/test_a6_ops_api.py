"""A6 acceptance (API side): the operator console's write API on top of the read-only shell."""
import json
from pathlib import Path

import pytest

from data.load_fixture import load
from ui.shell.server import Shell

pytestmark = pytest.mark.a6

ROOT = Path(__file__).resolve().parents[2]
SPEC = json.loads((ROOT / "data" / "fixtures" / "ap_tiny.json").read_text(encoding="utf8"))
W = SPEC["window"]
GRAPH = "a6_ui"


class Recorder:
    def __init__(self):
        self.compensated = []

    def compensate(self, kind, payload):
        self.compensated.append((kind, payload))
        return {"ok": True}


@pytest.fixture()
def api():
    load(SPEC, graph_name=GRAPH)
    shell = Shell(default_graph=GRAPH, min_interval=0)
    router = shell.router()
    shell.ops.executor = Recorder()

    class Api:
        ops = shell.ops

        def get(self, path):
            return router.dispatch("GET", path)

        def post(self, path, body, token=True):
            b = dict(body)
            if token:
                b["token"] = shell.ops.token
            b.setdefault("graph", GRAPH)
            return router.dispatch("POST", path, b)
    return Api()


def window(mode):
    return {"source": W["source"], "from": W["from"], "to": W["to"], "mode": mode}


def statuses(api):
    st, body = api.get(f"/api/graph?graph={GRAPH}")
    assert st == 200
    return {n["id"]: n.get("status") for n in body["nodes"] if n.get("status")}


def test_writes_need_the_session_token(api):
    st, body = api.post("/api/ops/distrust", window("preview"), token=False)
    assert st == 403 and body["error"]["code"] == "FORBIDDEN"
    st, body = api.get("/api/ops/session")
    assert st == 200 and len(body["token"]) >= 16


def test_sources_listing(api):
    st, body = api.get(f"/api/ops/sources?graph={GRAPH}")
    assert st == 200
    s = {x["id"]: x for x in body["sources"]}
    assert s["coastal-portal"]["observations"] == 4 and s["coastal-portal"]["first"] < s["coastal-portal"]["last"]


def test_preview_changes_nothing_then_commit_flips(api):
    before = statuses(api)
    st, p = api.post("/api/ops/distrust", window("preview"))
    assert st == 200 and p["preview"] is True and p["diff"]
    assert statuses(api) == before
    assert api.get(f"/api/ops/recall?graph={GRAPH}")[1]["retractions"] == []

    st, c = api.post("/api/ops/distrust", window("commit"))
    assert st == 200 and c["retraction_id"] == p["retraction_id"]
    assert set(c["flipped_ids"]) == set(p["flipped_ids"])
    after = statuses(api)
    assert {k for k, v in after.items() if v == "OUT"} == set(c["flipped_ids"])
    assert c["profile"]["execution_ms"] is not None
    assert [d["status"] for d in c["remediations"]] == ["draft"]


def test_recall_state_and_approval_flow(api):
    api.post("/api/ops/distrust", window("commit"))
    st, state = api.get(f"/api/ops/recall?graph={GRAPH}")
    assert st == 200
    assert [r["action_id"] for r in state["recall"]] == ["act_pay_1"] and state["recall"][0]["amount"] == 18400
    rem = state["remediations"][0]
    assert rem["kind"] == "bank_recall" and rem["status"] == "draft"

    st, done = api.post("/api/ops/remediation", {"id": rem["id"], "action": "approve", "operator": "dennis"})
    assert st == 200 and done["status"] == "executed" and done["approved_by"] == "dennis"
    assert api.ops.executor.compensated[0][0] == "bank_recall"
    st, again = api.post("/api/ops/remediation", {"id": rem["id"], "action": "approve"})
    assert st == 400 and again["error"]["code"] == "INVALID_ARGUMENT"


def test_reject_and_unknown_action(api):
    api.post("/api/ops/distrust", window("commit"))
    rem = api.get(f"/api/ops/recall?graph={GRAPH}")[1]["remediations"][0]
    st, body = api.post("/api/ops/remediation", {"id": rem["id"], "action": "explode"})
    assert st == 400 and body["error"]["code"] == "INVALID_ARGUMENT"
    st, body = api.post("/api/ops/remediation", {"id": rem["id"], "action": "reject"})
    assert st == 200 and body["status"] == "rejected" and api.ops.executor.compensated == []


def test_reinstate_withdraws_everything(api):
    before = statuses(api)
    rid = api.post("/api/ops/distrust", window("commit"))[1]["retraction_id"]
    st, out = api.post("/api/ops/reinstate", {"retraction_id": rid})
    assert st == 200 and out["restored_count"] > 0
    assert statuses(api) == before
    state = api.get(f"/api/ops/recall?graph={GRAPH}")[1]
    assert state["retractions"][0]["reinstated"] is True and state["recall"] == []
    assert {r["status"] for r in state["remediations"]} == {"withdrawn"}
    st, _ = api.post("/api/ops/reinstate", {"retraction_id": rid})
    assert st == 400


def test_errors_use_the_contract_shape(api):
    st, body = api.post("/api/ops/distrust", {**window("preview"), "source": "ghost"})
    assert st == 404 and body["error"]["code"] == "NOT_FOUND"
    st, body = api.post("/api/ops/distrust", {"source": "coastal-portal", "mode": "preview"})
    assert st == 400 and body["error"]["code"] == "INVALID_ARGUMENT"
    st, _ = api.post("/api/ops/distrust", {**window("dryrun")})
    assert st == 400


def test_static_files_and_page_wiring(api):
    st, js = api.get("/ops/ops.js")
    assert st == 200 and "RETCON" in js.data.decode()
    assert api.get("/ops/ops_logic.js")[0] == 200 and api.get("/ops/ops.css")[0] == 200
    assert api.get("/ops/nothing.js")[0] == 404
    st, page = api.get("/graph")
    html = page.data.decode()
    assert "/ops/ops.js" in html and "/ops/ops_logic.js" in html and "/ops/ops.css" in html
    assert html.index("/static/app.js") < html.index("/ops/ops.js")  # panels load after the shell
