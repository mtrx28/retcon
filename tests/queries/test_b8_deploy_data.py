"""B8 (deploy + DATA.md): cheap checks that keep the promises these files make.

The expensive proof for B8 (a clean copy of the repo brought up with `docker compose up --build`, the front page,
the guided demo, the MCP server and the replayed agent day all working) was run by hand; see docs/STATUS.md.
"""
import json
import re
import sys
from pathlib import Path

import pytest

from core.db import connection_args

pytestmark = pytest.mark.b8

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = (ROOT / "docker-compose.yml").read_text(encoding="utf8")
DOCKERFILE = (ROOT / "Dockerfile").read_text(encoding="utf8")
DOCKERIGNORE = (ROOT / ".dockerignore").read_text(encoding="utf8")
DATA = (ROOT / "DATA.md").read_text(encoding="utf8")
DEPLOY = (ROOT / "docs" / "DEPLOY.md").read_text(encoding="utf8")


# ---- connection ---------------------------------------------------------------------------------

def test_connection_args_defaults_and_hosted_options():
    assert connection_args({}) == {"host": "localhost", "port": 6379}
    got = connection_args({"FALKORDB_HOST": "db.example", "FALKORDB_PORT": "6390", "FALKORDB_USERNAME": "u",
                           "FALKORDB_PASSWORD": "p", "FALKORDB_SSL": "1"})
    assert got == {"host": "db.example", "port": 6390, "username": "u", "password": "p", "ssl": True}
    assert "ssl" not in connection_args({"FALKORDB_SSL": "0"})
    assert "password" not in connection_args({"FALKORDB_PASSWORD": ""})


def test_one_place_decides_how_to_reach_falkordb():
    import core.db
    import data.load_fixture
    assert data.load_fixture.connect is core.db.connect


def test_server_binds_localhost_unless_told_otherwise(monkeypatch):
    import ui.shell.server as srv
    monkeypatch.setenv("RETCON_EMBEDDER", "hash")     # main() sets it as a default; restore afterwards
    seen = {}

    def fake_serve(router, port=0, host="127.0.0.1"):
        seen["host"], seen["port"] = host, port
        return None, f"http://{host}:{port}"

    class Stop(Exception):
        pass

    def stop(_):
        raise Stop

    class FakeShell:
        def __init__(self, **kw):
            pass

        def router(self):
            return None

        def graph_names(self):
            return []

    monkeypatch.setattr(srv, "serve", fake_serve)
    monkeypatch.setattr(srv, "Shell", FakeShell)
    monkeypatch.setattr(srv.time, "sleep", stop)
    monkeypatch.delenv("RETCON_HOST", raising=False)
    monkeypatch.setattr(sys, "argv", ["server"])
    with pytest.raises(Stop):
        srv.main()
    assert seen["host"] == "127.0.0.1"
    monkeypatch.setattr(sys, "argv", ["server", "--host", "0.0.0.0", "--port", "9"])
    with pytest.raises(Stop):
        srv.main()
    assert seen == {"host": "0.0.0.0", "port": 9}


# ---- docker -------------------------------------------------------------------------------------

def test_compose_runs_the_whole_product_with_falkordb_as_the_only_store():
    for svc in ("falkordb:", "seed:", "app:"):
        assert re.search(rf"^  {svc}$", COMPOSE, re.M), svc
    images = re.findall(r"^\s+image:\s*(\S+)", COMPOSE, re.M)
    assert [i for i in images if not i.startswith("retcon-app")] and all(
        i.startswith(("falkordb/falkordb@sha256:", "retcon-app")) for i in images)   # pinned; no other database
    assert "redis-cli" in COMPOSE and "service_healthy" in COMPOSE and "service_completed_successfully" in COMPOSE


def test_the_operator_api_is_published_to_this_machine_only():
    ports = re.findall(r'^\s+- "([^"]+:8200)"', COMPOSE, re.M)
    assert ports and all(p.startswith("127.0.0.1:") for p in ports)


def test_the_image_has_no_secrets_and_runs_unprivileged():
    assert "USER retcon" in DOCKERFILE and "EXPOSE 8200" in DOCKERFILE and "HEALTHCHECK" in DOCKERFILE
    for secret_like in (".env", "GEMINI_API_KEY", "ANTHROPIC_API_KEY"):
        assert f"COPY {secret_like}" not in DOCKERFILE
    ignored = {line.strip() for line in DOCKERIGNORE.splitlines()}
    assert {".env", ".git", ".venv", "data/science/raw"} <= ignored


def test_tasks_up_still_starts_only_the_database():
    tasks = (ROOT / "tasks.py").read_text(encoding="utf8")
    assert '"compose", "up", "-d", "falkordb"' in tasks and re.search(r"^  falkordb:$", COMPOSE, re.M)


# ---- DATA.md ------------------------------------------------------------------------------------

def test_data_md_says_synthetic_or_public_and_names_every_source():
    low = DATA.lower()
    for needle in ("synthetic", "public", "retraction watch", "openalex", "gemini", "rule 6", "cc0",
                   "no author names", "not redistribute the raw csv"):
        assert needle in low, needle
    for path in ("data/generator", "data/fixtures/ap_tiny.json", "data/fixtures/science.json", "data/llm_cache/payments",
                 "data/science", "bench/results", "ui/home/static/assets"):
        assert (ROOT / path).exists(), path


def test_data_md_numbers_match_the_committed_science_fixture():
    spec = json.loads((ROOT / "data" / "fixtures" / "science.json").read_text(encoding="utf8"))
    assert f"{len(spec['observations']):,}" in DATA and f"{len(spec['sources'])}" in DATA
    assert sum(1 for s in spec["sources"] if s.get("retracted_at")) == 40 and "40 retracted" in DATA
    def keys(x):                       # field NAMES, not text: a reason like "Author Unresponsive" is a value
        if isinstance(x, dict):
            for k, v in x.items():
                yield k
                yield from keys(v)
        elif isinstance(x, list):
            for v in x:
                yield from keys(v)
    stored = {k.lower() for k in keys(spec)}
    assert not {k for k in stored if k.startswith(("author", "institution", "affiliation", "countr"))}
    assert len(list((ROOT / "data" / "llm_cache" / "payments").glob("*.json"))) == 49 and "49 requests" in DATA


def test_synthetic_scenario_uses_only_invented_identifiers():
    spec = json.loads((ROOT / "data" / "fixtures" / "ap_tiny.json").read_text(encoding="utf8"))
    text = json.dumps(spec)
    assert re.findall(r"\b[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b", text) == []         # no IBAN-shaped strings
    assert "SYN-" in text and "@" not in text


def test_deploy_md_is_honest_about_what_was_tested():
    low = DEPLOY.lower()
    assert "docker compose up --build" in DEPLOY and "no api key" in low
    assert "have not deployed to falkordb cloud" in low and "127.0.0.1" in DEPLOY
