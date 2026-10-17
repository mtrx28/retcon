"""A8: the README and the front-page footer keep their promises.

These are cheap text checks (plus one scenario-identity check) so a later edit cannot silently drop something
the hackathon rules require (README contents, AI disclosure) or something we agreed not to say.
"""
import json
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.a8

ROOT = Path(__file__).resolve().parents[2]
README = (ROOT / "README.md").read_text(encoding="utf8")
REPO = "https://github.com/mtrx28/retcon"


def test_readme_has_what_the_rules_require():
    low = README.lower()
    for needle in ("track 02", "track 01", "ai assistance", "claude code", "gemini", "queries we depend on",
                   "graph data model" if "graph data model" in low else "what it is, in one picture",
                   "limitations", "synthetic", "retraction watch", "openalex"):
        assert needle in low, f"README is missing: {needle}"
    assert REPO in README
    for q in ("Q1", "Q2", "Q3", "Q4", "Q5", "Q6", "Q7", "Q8"):
        assert f"**{q}," in README, f"README does not list {q}"


def test_readme_uses_the_payments_agent_sentence_from_the_docs():
    doc = (ROOT / "docs" / "PAYMENTS_AGENT.md").read_text(encoding="utf8")
    lead = "The Payments agent can choose its own tool calls with Gemini function calling."
    assert lead in doc and lead in README
    assert "The rule-based Payments agent stays as the default and as the fallback." in README


def test_readme_leads_the_graph_off_result_with_the_embedder_independent_numbers():
    i = README.index("Take the graph away.")
    para = README[i:i + 1400]
    assert "retracted 3 of 9" in para and "lost 5 clean ones" in para
    # the embedder caveat is stated, and "pays the attacker" is never presented as the general result
    assert "hash" in para and "MiniLM" in para and "not \"it always pays\"" in para
    assert para.index("retracted 3 of 9") < para.index("paid the attacker") if "paid the attacker" in para else True


def test_readme_never_claims_a_falkordb_bug_and_states_what_is_pending():
    low = README.lower()
    for banned in ("falkordb bug", "found a bug", "bug in falkordb", "we discovered a bug"):
        assert banned not in low
    assert "model reviewer, not a human" in README           # audit status, until a human has confirmed it
    assert "not a free win" in README                         # the 0%/0% framing


def test_every_quickstart_command_is_a_real_task():
    tasks_doc = (ROOT / "tasks.py").read_text(encoding="utf8")
    block = README[README.index("## Run it in five minutes"):README.index("**Use it from your own agent.**")]
    used = re.findall(r"python tasks\.py (\w+)", block)
    assert used[:4] == ["up", "fixture", "demo", "ui"]
    for t in used:
        assert re.search(rf"\b{t}\b", tasks_doc.split('"""')[1]), f"tasks.py has no task {t}"


def test_every_local_link_in_the_readme_exists():
    for target in re.findall(r"\]\((docs/[^)#]+|[A-Za-z_/]+\.md)\)", README):
        assert (ROOT / target).exists(), f"README links to missing {target}"


def test_front_page_footer_links_to_the_repo():
    html = (ROOT / "ui" / "home" / "static" / "index.html").read_text(encoding="utf8")
    foot = html[html.index('<footer class="foot">'):]
    assert f'href="{REPO}"' in foot
    from ui.shell.server import Shell
    st, page = Shell(default_graph="x").router().dispatch("GET", "/")
    assert st == 200 and f'href="{REPO}"' in page.data.decode()


def test_baselines_runner_has_no_private_ap_scenarios():
    """bench/baselines/run.py used to build its own ap_<N>k, a different graph than the harness's ap_1k."""
    src = (ROOT / "bench" / "baselines" / "run.py").read_text(encoding="utf8")
    assert "fullmatch" not in src
    from bench.baselines.run import scenario
    from bench.harness.scenarios import build
    spec, meta = scenario("ap_1k")
    mine, theirs = spec, build("ap_1k").spec
    assert json.dumps(mine["ground_truth"], sort_keys=True) == json.dumps(theirs["ground_truth"], sort_keys=True)
    assert len(mine["actions"]) == len(theirs["actions"]) and len(mine["derivations"]) == len(theirs["derivations"])
    assert len(mine["actions"]) > 10                           # the harness scenario (12 invoices per vendor), not the old 2
    rows = json.loads((ROOT / "bench" / "results" / "baselines.json").read_text(encoding="utf8"))
    latest = {(r["scenario"], r["strategy"]): r for r in
              json.loads((ROOT / "bench" / "results" / "latest.json").read_text(encoding="utf8")) if r.get("metrics")}
    shared = [r for r in rows if (r["scenario"], r["strategy"]) in latest and r.get("metrics")]
    assert len(shared) >= 15
    for r in shared:                                           # the two runners now agree row for row
        a, b = r["metrics"], latest[(r["scenario"], r["strategy"])]["metrics"]
        for k in ("residual_contamination", "collateral_loss", "action_recall", "blocked_recall"):
            assert a[k] == b[k], (r["scenario"], r["strategy"], k)
