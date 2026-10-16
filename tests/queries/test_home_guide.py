"""Front page + guided demo endpoints: numbers come from result files, the comparison runs real strategies,
demo POSTs are token guarded, doc and static routes are whitelisted."""
import json
import urllib.error
import urllib.request

import pytest

from core.db import connect
from data.httpkit import serve
from ui.shell.server import Shell

pytestmark = [pytest.mark.home, pytest.mark.guide]


def call(url, data=None):
    req = urllib.request.Request(url, data=None if data is None else json.dumps(data).encode(),
                                 headers={"Content-Type": "application/json"} if data is not None else {})
    try:
        with urllib.request.urlopen(req) as r:
            body = r.read()
            return r.status, r.headers["Content-Type"], body
    except urllib.error.HTTPError as e:
        return e.code, e.headers["Content-Type"], e.read()


@pytest.fixture(scope="module")
def site():
    shell = Shell(db=connect(), default_graph="tenant_northwind", min_interval=0)
    router = shell.router()
    from ui.demo import mount as mount_demo
    from ui.guide import mount as mount_guide
    from ui.home import mount as mount_home
    from ui.ops import mount as mount_ops
    ops = mount_ops(router, shell)
    mount_home(router, shell)
    mount_guide(router)
    mount_demo(router, shell, ops)
    srv, url = serve(router)
    yield url
    srv.shutdown()


def test_front_page_and_static(site):
    st, ctype, body = call(site + "/")
    assert st == 200 and ctype.startswith("text/html") and b"RETRACT" in body
    assert call(site + "/home/home.css")[0] == 200
    assert call(site + "/home/assets/palimpsest.jpg")[0] == 200
    assert call(site + "/home/..%2F__init__.py")[0] == 404
    assert call(site + "/guide/guide.js")[0] == 200


def test_docs_are_whitelisted(site):
    assert call(site + "/docs/MCP_CLIENT.md")[0] == 200
    assert call(site + "/docs/STATUS.md")[0] == 404
    assert call(site + "/docs/..%2FREADME.md")[0] == 404


def test_numbers_read_from_result_files(site):
    st, _, body = call(site + "/api/home/numbers")
    out = json.loads(body)
    assert st == 200 and "speed" in out and "precision" in out
    for row in out["precision"]:
        assert row["collateral"] is not None


def test_compare_runs_all_five_rules(site):
    st, _, body = call(site + "/api/home/compare")
    out = json.loads(body)
    assert st == 200 and len(out["strategies"]) == 5
    r = out["strategies"]["retcon"]
    assert r["residual"] == 0 and r["collateral"] == 0           # exactly what should go
    assert out["strategies"]["coarse_taint"]["collateral"] > 0       # coarse taint loses correct memories


def test_demo_posts_need_the_session_token(site):
    for path in ("/api/demo/start", "/api/demo/ablation"):
        st, _, _ = call(site + path, {"token": "wrong"})
        assert st == 403
    st, _, body = call(site + "/api/demo/status")
    assert st == 200 and json.loads(body)["phase"] in ("idle", "running", "ready", "error")
