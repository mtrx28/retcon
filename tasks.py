"""Cross-platform task runner (no `make` on Windows). Usage: python tasks.py <task> [args]

  up | down           start/stop FalkorDB via docker compose
  fixture             load data/fixtures/ap_tiny.json into tenant_<RETCON_TENANT>
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
    elif t == "embed":
        run(py, "-m", "core.retrieve.embed_cli", *rest)
    elif t == "test":
        run(py, "-m", "pytest", "-q", *rest)
    elif t == "accept":
        if not rest:
            sys.exit("usage: python tasks.py accept <TASK_ID>")
        run(py, "-m", "pytest", "-q", "-m", rest[0].lower())
    elif t == "spike":
        run(py, "scripts/spike.py")
    else:
        sys.exit(f"unknown task: {t}\n{__doc__}")


if __name__ == "__main__":
    main(sys.argv[1:])
