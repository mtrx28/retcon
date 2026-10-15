"""Fake vendor portal (task B4a): the page the Intake agent scrapes.

Serves one HTML page per vendor built from the scenario's portal observations. A deterministic
clock makes it replayable: `?as_of=<ISO>` shows only what the portal had published by then, so the
seeded agent phase sees the poisoned bank-change appear on Oct 5 and never "live" time.

    GET /vendors                       -> [{id, name}]
    GET /vendors/<id>                  -> HTML (facts as <li data-observed-at data-obs-id>)
    GET /api/vendors/<id>/facts        -> JSON [{obs_id, observed_at, text}]
"""
import html

from data.httpkit import Router


class Portal:
    def __init__(self, spec):
        self.vendors = {v["id"]: v for v in spec["vendors"]}
        self.facts = {v["id"]: [] for v in spec["vendors"]}
        by_source = {v["portal_source"]: v["id"] for v in spec["vendors"]}
        for o in spec["observations"]:
            if o["source"] in by_source:
                self.facts[by_source[o["source"]]].append(
                    {"obs_id": o["id"], "observed_at": o["observed_at"], "text": o["text"]})
        for rows in self.facts.values():
            rows.sort(key=lambda r: r["observed_at"])

    def visible(self, vendor, as_of=None):
        return [f for f in self.facts[vendor] if as_of is None or f["observed_at"] <= as_of]

    def page(self, vendor, as_of=None):
        v = self.vendors[vendor]
        items = "\n".join(
            f'<li data-obs-id="{f["obs_id"]}" data-observed-at="{f["observed_at"]}">{html.escape(f["text"])}</li>'
            for f in self.visible(vendor, as_of))
        return (f"<!doctype html><html><head><title>{html.escape(v['name'])} supplier portal</title></head>"
                f"<body><h1>{html.escape(v['name'])}</h1><ul id=\"facts\">\n{items}\n</ul></body></html>")

    def router(self):
        r = Router()

        def listing(req):
            return 200, [{"id": k, "name": v["name"]} for k, v in self.vendors.items()]

        def page(req):
            vid = req.params["vid"]
            return (200, self.page(vid, req.query.get("as_of"))) if vid in self.vendors else _missing(vid)

        def facts(req):
            vid = req.params["vid"]
            return (200, self.visible(vid, req.query.get("as_of"))) if vid in self.vendors else _missing(vid)

        r.add("GET", "/vendors", listing)
        r.add("GET", "/vendors/<vid>", page)
        r.add("GET", "/api/vendors/<vid>/facts", facts)
        return r


def _missing(vid):
    return 404, {"error": {"code": "NOT_FOUND", "message": f"unknown vendor {vid}", "details": {}}}
