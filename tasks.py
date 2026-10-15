"""Cross-platform task runner (no `make` on Windows). Usage: python tasks.py <task> [args]

  up | down           start/stop FalkorDB via docker compose
  fixture             load data/fixtures/ap_tiny.json into tenant_<RETCON_TENANT>
  gen [args]          generate a seeded scenario: gen --vendors 3 -o data/fixtures/ap_gen.json (see data/generator)
  sandbox [spec]      run fake portal + mock bank + inbox on :8100
  demo [args]         the seeded agent day as a transcript (python -m agents.demo; --transport mcp for real MCP)
  ui [--port 8200]    the graph canvas (open the printed URL); pair with `demo --live` to watch it grow
  bench [args]        RetconBench: python -m bench.harness --scenarios ap_tiny,ap_1k,ap_prec_1k --launder --ablation --concurrency --charts auto
  science [args]      build data/fixtures/science.json from data/science/raw (python -m data.science.ingest)
  embed               create the vector index and embed every Mem of tenant_<RETCON_TENANT>
  test                run the full pytest suite
  accept <ID>         acceptance check for one task, e.g. accept A4 (runs tests marked/named for it)
  spike               run scripts/spike.py (live-engine syntax checks, writes docs/SPIKE.md)
"""
import subprocess
import sys


def run(*cmd):
    sys.exit(subprocess.call(cmd))


def main(argv):
    if not argv:
        print(__doc__)
        return
    t, rest = argv[0], argv[1:]
    py = sys.executable
    if t == "up":
        run("docker", "compose", "up", "-d", "falkordb")
    elif t == "down":
        run("docker", "compose", "down")
    elif t == "fixture":
        run(py, "-m", "data.load_fixture", *rest)
    elif t == "gen":
        run(py, "-m", "data.generator", *rest)
    elif t == "sandbox":
        run(py, "-m", "data.sandbox", *rest)
    elif t == "demo":
        run(py, "-m", "agents.demo", *rest)
    elif t == "ui":
        run(py, "-m", "ui.shell.server", *rest)
    elif t == "bench":
        run(py, "-m", "bench.harness", *rest)
    elif t == "science":
        run(py, "-m", "data.science.ingest", *rest)
    elif t == "embed":
        run(py, "-m", "core.retrieve.embed_cli", *rest)
    elif t == "test":
        run(py, "-m", "pytest", "-q", *rest)
    elif t == "accept":
        if not rest:
            sys.exit("usage: python tasks.py accept <TASK_ID>")
        import os
        if rest[0].lower() == "a2":  # full strength: 1,000 differential graphs, 300 property graphs
            os.environ.setdefault("RETCON_DIFF_N", "1000")
            os.environ.setdefault("RETCON_PROP_N", "300")
        run(py, "-m", "pytest", "-q", "-m", rest[0].lower().replace("+", "plus"))  # B1+ -> b1plus
    elif t == "spike":
        run(py, "scripts/spike.py")
    else:
        sys.exit(f"unknown task: {t}\n{__doc__}")


if __name__ == "__main__":
    main(sys.argv[1:])
