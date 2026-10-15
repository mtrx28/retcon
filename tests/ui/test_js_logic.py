"""Runs the pure-JS logic tests (layout + store) with Node's built-in runner. Skipped if Node is absent."""
import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.b6a
HERE = Path(__file__).resolve().parent


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_layout_and_store_logic():
    r = subprocess.run(["node", "--test", str(HERE / "layout.test.js")], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-1000:]
