"""python -m core.report [--graph NAME] [--retraction ret_0001] [--format md|html|json] [-o FILE]

Prints (or writes) the incident report for a retraction. Defaults: tenant_<RETCON_TENANT>, latest active retraction, Markdown.
"""
import argparse
import json
import os
import sys

from core import report
from core.db import connect

ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
ap.add_argument("--graph", default=f"tenant_{os.getenv('RETCON_TENANT', 'northwind')}")
ap.add_argument("--retraction")
ap.add_argument("--format", default="md", choices=["md", "html", "json"])
ap.add_argument("-o", "--out")
a = ap.parse_args()

g = connect().select_graph(a.graph)
try:
    data = report.build(g, a.retraction, graph_name=a.graph)
except Exception as e:  # noqa: BLE001 - a missing retraction is the common failure; say it plainly
    sys.exit(f"cannot build a report: {e}")
text = {"md": report.markdown, "html": report.html, "json": lambda d: json.dumps(d, indent=1, default=str)}[a.format](data)
if a.out:
    with open(a.out, "w", encoding="utf8") as f:
        f.write(text)
    print(f"wrote {a.out}")
else:
    sys.stdout.reconfigure(encoding="utf8")
    print(text)
