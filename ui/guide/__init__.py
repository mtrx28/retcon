"""Guide panel files (upgrade 1): served at /guide/<file>. The panel itself is guide.js; the API it calls is ui.demo."""
import mimetypes
from pathlib import Path

from data.httpkit import Raw

STATIC = Path(__file__).resolve().parent / "static"


def mount(router):
    def static(req):
        p = (STATIC / req.params["name"]).resolve()
        if STATIC not in p.parents or not p.is_file():
            return 404, {"error": {"code": "NOT_FOUND", "message": req.params["name"], "details": {}}}
        ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
            ctype += "; charset=utf-8"
        return 200, Raw(p.read_bytes(), ctype)

    router.add("GET", "/guide/<name>", static)
