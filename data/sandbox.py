"""One process for the whole sandbox: portal, bank and inbox on a single port.

    python -m data.sandbox [spec.json] [--port 8100]     (default: generated on the fly, seed 7, 3 vendors)
    /portal/...  /bank/...  /mail/...
"""
import argparse
import json
import time
from pathlib import Path

from data.bank import MockBank
from data.httpkit import Router, serve
from data.inbox import SandboxInbox
from data.portal import Portal


def build(spec):
    """Returns (router, services) with the three services mounted under /portal, /bank, /mail."""
    svc = {"portal": Portal(spec), "bank": MockBank.from_spec(spec), "inbox": SandboxInbox.from_spec(spec)}
    root = Router()
    root.mount("/portal", svc["portal"].router())
    root.mount("/bank", svc["bank"].router())
    root.mount("/mail", svc["inbox"].router())
    return root, svc


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("spec", nargs="?")
    ap.add_argument("--port", type=int, default=8100)
    a = ap.parse_args()
    if a.spec:
        spec = json.loads(Path(a.spec).read_text(encoding="utf8"))
    else:
        from data.generator import generate
        spec = generate(seed=7, vendors=3)
    router, _ = build(spec)
    _, url = serve(router, a.port)
    print(f"sandbox on {url}  (portal /portal/vendors, bank /bank/payments, mail /mail/inbox)")
    while True:
        time.sleep(3600)
