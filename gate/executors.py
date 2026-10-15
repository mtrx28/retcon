"""Executors: how a released action (or an approved compensation) touches the outside world.

Interface (duck-typed):
    execute(tool, args) -> dict         raises ExecutionError on failure
    compensate(kind, payload) -> dict   raises ExecutionError on failure

SandboxExecutor drives the in-process mock bank / sandbox inbox (data/bank, data/inbox).
HttpExecutor drives the same services over HTTP (`python tasks.py sandbox`, default :8100).
Nothing real moves: both targets are synthetic (rule 6).
"""
import json
import urllib.error
import urllib.request


class ExecutionError(Exception):
    pass


class SandboxExecutor:
    def __init__(self, bank=None, inbox=None):
        self.bank, self.inbox = bank, inbox

    def execute(self, tool, args):
        if tool == "pay" and self.bank is not None:
            status, body = self.bank.pay(vendor=args.get("vendor"), iban=args.get("iban"),
                                         amount=args.get("amount"), invoice=args.get("invoice"),
                                         idempotency_key=args.get("idempotency_key"))
            if status >= 400:
                raise ExecutionError(body["error"]["message"])
            return {"payment_id": body["id"], "status": body["status"],
                    "iban_matches_contract": body.get("iban_matches_contract")}
        if tool in ("email", "notify") and self.inbox is not None:
            m = self.inbox.send(args.get("to"), args.get("subject", ""), args.get("body", ""),
                                agent=args.get("agent"))
            return {"message_id": m["id"]}
        raise ExecutionError(f"no executor for tool {tool!r}")

    def compensate(self, kind, payload):
        if kind == "bank_recall" and self.bank is not None:
            if not payload.get("payment_id"):
                raise ExecutionError("no payment id recorded for this action; recall manually")
            status, body = self.bank.recall(payload["payment_id"], payload.get("reason"))
            if status >= 400:
                raise ExecutionError(body["error"]["message"])
            return {"payment_id": body["id"], "status": body["status"]}
        if kind == "correction_email" and self.inbox is not None:
            m = self.inbox.send(payload.get("to"), payload.get("subject", ""), payload.get("body", ""),
                                agent="remediator")
            return {"message_id": m["id"]}
        raise ExecutionError(f"no compensation executor for {kind!r}")


class HttpExecutor:
    def __init__(self, base="http://127.0.0.1:8100"):
        self.base = base.rstrip("/")

    def _post(self, path, body):
        req = urllib.request.Request(self.base + path, data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            try:
                msg = json.loads(e.read())["error"]["message"]
            except Exception:  # noqa: BLE001
                msg = str(e)
            raise ExecutionError(msg) from None
        except OSError as e:
            raise ExecutionError(f"sandbox unreachable: {e}") from None

    def execute(self, tool, args):
        if tool == "pay":
            keys = ("vendor", "iban", "amount", "invoice", "idempotency_key")
            body = self._post("/bank/payments", {k: args[k] for k in keys if k in args})
            return {"payment_id": body["id"], "status": body["status"]}
        if tool in ("email", "notify"):
            body = self._post("/mail/outbox", {k: args.get(k) for k in ("to", "subject", "body", "agent")})
            return {"message_id": body.get("id")}
        raise ExecutionError(f"no executor for tool {tool!r}")

    def compensate(self, kind, payload):
        if kind == "bank_recall" and payload.get("payment_id"):
            body = self._post(f"/bank/payments/{payload['payment_id']}/recall",
                              {"reason": payload.get("reason")})
            return {"payment_id": body["id"], "status": body["status"]}
        if kind == "correction_email":
            body = self._post("/mail/outbox", {"to": payload.get("to"), "subject": payload.get("subject"),
                                             "body": payload.get("body"), "agent": "remediator"})
            return {"message_id": body.get("id")}
        raise ExecutionError(f"no compensation executor for {kind!r}")
