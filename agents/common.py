"""Shared helpers for the rule-based policies: tool-call shorthand and observation extraction."""
import re

IBAN = re.compile(r"SYN-\d{4}-\d{4}")
RULE_VERIFY_BANK = "Verify bank-detail changes by callback to the number on the signed contract before paying."


def call(tool, /, **args):
    return (tool, args)


def failed(result):
    return isinstance(result, dict) and "error" in result


def ok_list(result):
    """recall payload as a list of hits ([] on error)."""
    return result if isinstance(result, list) and not failed(result) else []


# Observation text -> what Intake believes. The generator's templates (data/generator) are the
# "documents"; an LLM brain would do this extraction with a prompt instead.
_PATTERNS = [
    ("bank_change", re.compile(r"^(?P<name>.+) portal: bank details changed to IBAN (?P<iban>SYN-\d{4}-\d{4})\.$"),
     lambda m: f"{m['name']} bank account is IBAN {m['iban']}."),
    ("address", re.compile(r"^(?P<name>.+) portal: remit address (?P<addr>.+)\.$"),
     lambda m: f"{m['name']} remit address is {m['addr']}."),
    ("address", re.compile(r"^Signed contract amendment: (?P<name>.+) address (?P<addr>.+)\.$"),
     lambda m: f"{m['name']} remit address is {m['addr']}."),
    ("contract_bank", re.compile(r"^Signed contract: (?P<name>.+) bank IBAN (?P<iban>SYN-\d{4}-\d{4})\.$"),
     lambda m: f"Contract bank for {m['name']} is IBAN {m['iban']}."),
    ("hours", re.compile(r"^(?P<name>.+) portal: opening hours (?P<h>.+)\.$"),
     lambda m: f"{m['name']} opens {m['h']}."),
    ("closure", re.compile(r"^(?P<name>.+) portal: holiday closure notice (?P<d>.+)\.$"),
     lambda m: f"{m['name']} closed on {m['d']}."),
]
_INVOICE = re.compile(r"^Invoice (?P<inv>INV-[\w-]+) from (?P<name>.+), (?P<amt>\d+) USD\.$")
_AUDIT = re.compile(r"^Audit log: an attempted bank-detail change was caught by callback verification")


def extract(text):
    """-> {"topic", "belief", "mtype"?, "iban"?, "invoice"?, "amount"?} or None (nothing to believe)."""
    if _AUDIT.match(text):
        return {"topic": "rule", "belief": RULE_VERIFY_BANK, "mtype": "procedural"}
    for topic, rx, make in _PATTERNS:
        m = rx.match(text)
        if m:
            out = {"topic": topic, "belief": make(m)}
            if "iban" in m.groupdict():
                out["iban"] = m["iban"]
            return out
    m = _INVOICE.match(text)
    if m:
        return {"topic": "invoice", "belief": None, "invoice": m["inv"], "amount": int(m["amt"])}
    return None


def choose_iban(hits):
    """The account Payments pays: the most recent *change* wins (typical bank-change workflow),
    otherwise the contract account. Only IN beliefs are ever recalled, so retracted claims cannot win."""
    changed, contract = None, None
    for h in hits:
        text = h.get("text", "")
        m = IBAN.search(text)
        if not m:
            continue
        if text.startswith("Contract bank for"):
            contract = contract or m.group(0)
        else:
            changed = changed or m.group(0)
    return changed or contract
