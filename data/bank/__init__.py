"""Mock bank API (task B4a): what the Payments agent calls through `act`, and what the Remediator
calls to recall money. Pure in-memory ledger; nothing real moves.

    POST /payments              {vendor, iban, amount, invoice, idempotency_key?} -> 201 payment
    GET  /payments              -> all payments, oldest first
    GET  /payments/<id>         -> one payment
    POST /payments/<id>/recall  {reason?} -> payment with status "recalled" (only if "executed")
    GET  /accounts/<vendor>     -> {vendor, iban}: the IBAN on file (from the signed contract)

Errors use the contract shape {"error": {"code", "message", "details"}}.
Payment ids are sequential (pay_0001, ...), so a seeded run is reproducible.
"""
from data.httpkit import Router


def _err(status, code, message, **details):
    return status, {"error": {"code": code, "message": message, "details": details}}


class MockBank:
    def __init__(self, on_file=None):
        self.on_file = dict(on_file or {})   # vendor id -> IBAN on file
        self.payments = []
        self._by_key = {}

    @classmethod
    def from_spec(cls, spec):
        return cls({v["id"]: v["iban_on_contract"] for v in spec["vendors"]})

    def pay(self, vendor, iban, amount, invoice=None, idempotency_key=None):
        """Returns (status, body). Idempotent on idempotency_key."""
        if idempotency_key and idempotency_key in self._by_key:
            return 200, self._by_key[idempotency_key]
        if not isinstance(amount, (int, float)) or isinstance(amount, bool) or amount <= 0:
            return _err(400, "INVALID_ARGUMENT", "amount must be a positive number", amount=amount)
        if vendor not in self.on_file:
            return _err(404, "NOT_FOUND", f"unknown vendor {vendor!r}", vendor=vendor)
        if not iban:
            return _err(400, "INVALID_ARGUMENT", "iban is required")
        p = {"id": f"pay_{len(self.payments) + 1:04d}", "vendor": vendor, "iban": iban, "amount": amount,
             "invoice": invoice, "status": "executed", "iban_matches_contract": iban == self.on_file[vendor]}
        self.payments.append(p)
        if idempotency_key:
            self._by_key[idempotency_key] = p
        return 201, p

    def get(self, pid):
        return next((p for p in self.payments if p["id"] == pid), None)

    def recall(self, pid, reason=None):
        p = self.get(pid)
        if p is None:
            return _err(404, "NOT_FOUND", f"unknown payment {pid}", payment_id=pid)
        if p["status"] != "executed":
            return _err(409, "INVALID_ARGUMENT", f"payment is {p['status']}, cannot recall", payment_id=pid)
        p["status"], p["recall_reason"] = "recalled", reason
        return 200, p

    def router(self):
        r = Router()
        r.add("POST", "/payments", lambda q: self.pay(**_pick(q.json or {}, "vendor", "iban", "amount",
                                                               "invoice", "idempotency_key")))
        r.add("GET", "/payments", lambda q: (200, list(self.payments)))
        r.add("GET", "/payments/<pid>", lambda q: (200, self.get(q.params["pid"])) if self.get(q.params["pid"])
              else _err(404, "NOT_FOUND", f"unknown payment {q.params['pid']}"))
        r.add("POST", "/payments/<pid>/recall", lambda q: self.recall(q.params["pid"], (q.json or {}).get("reason")))
        r.add("GET", "/accounts/<vendor>", lambda q: (200, {"vendor": q.params["vendor"],
                                                           "iban": self.on_file[q.params["vendor"]]})
              if q.params["vendor"] in self.on_file else _err(404, "NOT_FOUND", "unknown vendor"))
        return r


def _pick(d, *keys):
    return {k: d[k] for k in keys if k in d}
