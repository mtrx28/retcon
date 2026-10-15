import random
from datetime import datetime, timedelta, timezone

# Fictional vendors only (synthetic data rule). Vendor 0 is always Coastal Produce, the demo victim.
NAMES = ["Coastal Produce", "Harbor Dairy", "Summit Packaging", "Ridgeline Foods", "Bluewater Seafood",
         "Orchard Row Farms", "Ironbark Logistics", "Meadowlark Bakery", "Cedar Point Spices",
         "Lakeshore Beverages", "Northgate Grains", "Saltmarsh Provisions"]
WINDOW = ("2026-10-02T00:00:00Z", "2026-10-09T23:59:59Z")
BASE = datetime(2026, 10, 1, 9, 0, 0, tzinfo=timezone.utc)


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _at(day, hour=9, minute=0):
    return _iso(BASE + timedelta(days=day - 1, hours=hour - 9, minutes=minute))


def _slug(i):
    return "coastal" if i == 0 else f"v{i:03d}"


def _name(i):
    return NAMES[i] if i < len(NAMES) else f"Northwind Vendor {i:03d}"


def vendors_for_nodes(target, invoices=2, launder_depth=2):
    """How many vendors give roughly `target` Mem nodes."""
    per = 14 + launder_depth + 4 * invoices  # Mem nodes one vendor adds (24 for the defaults)
    return max(1, round(target / per))


def generate(seed=7, vendors=3, invoices=2, launder_depth=2, poisoned=1, tenant="northwind",
             audit_incident=False):
    """Build a scenario. The first `poisoned` vendors have a compromised portal (window WINDOW).

    audit_incident=True adds one episode from a trusted audit log (a past bank-change fraud caught by
    callback) and the procedural rule Intake learned from it, so all three mtypes exist (B1+). The rule
    rests on that episode, not on any portal, so it survives the cascade. Off by default: node counts
    of existing scenarios do not change."""
    if not (1 <= poisoned <= vendors):
        raise ValueError("need 1 <= poisoned <= vendors")
    rnd = random.Random(seed)
    spec = {
        "tenant": tenant,
        "description": (f"Synthetic AP scenario (seed {seed}): {vendors} vendors, {poisoned} compromised "
                        f"portal(s) during {WINDOW[0][:10]}..{WINDOW[1][:10]}. Fictional data."),
        "window": {"source": f"{_slug(0)}-portal", "from": WINDOW[0], "to": WINDOW[1]},
        "meta": {"seed": seed, "vendors": vendors, "invoices": invoices,
                 "launder_depth": launder_depth, "poisoned": poisoned},
        "sources": [{"id": "erp", "kind": "agent", "trust": 0.95},
                    {"id": "po-system", "kind": "agent", "trust": 0.9}],
        "agents": [{"id": a, "role": a} for a in ("intake", "analyst", "payments", "comms", "remediator")],
        "vendors": [],
        "observations": [], "derivations": [], "actions": [],
    }
    for i in range(vendors):
        _vendor(spec, rnd, i, invoices, launder_depth, compromised=i < poisoned)
    if audit_incident:
        _audit_incident(spec)
    spec["ground_truth"] = _ground_truth(spec)
    return spec


RULE_ID = "rule_verify_bank"
EPISODE_ID = "audit_o_incident"
RULE_TEXT = "Verify bank-detail changes by callback to the number on the signed contract before paying."


def _audit_incident(spec):
    spec["sources"].append({"id": "audit-log", "kind": "user", "trust": 0.95})
    spec["observations"].append({
        "id": EPISODE_ID, "source": "audit-log", "observed_at": "2026-09-12T09:00:00Z",
        "text": "Audit log: an attempted bank-detail change was caught by callback verification; no funds lost."})
    spec["derivations"].append({
        "id": "audit_d_rule", "rule": "infer", "agent": "intake", "premises": [EPISODE_ID],
        "conclusion": {"id": RULE_ID, "kind": "belief", "mtype": "procedural", "text": RULE_TEXT}})
    spec["meta"]["audit_incident"] = True


def _vendor(spec, rnd, i, invoices, depth, compromised):
    s, name = _slug(i), _name(i)
    portal, contract = f"{s}-portal", f"{s}-contract"
    new_iban = f"SYN-{9000 + i % 1000:04d}-{rnd.randrange(10000):04d}"
    old_iban = f"SYN-{1000 + i % 1000:04d}-{rnd.randrange(10000):04d}"
    street = f"{rnd.randrange(1, 99)} {rnd.choice(['Dock', 'Mill', 'Harbor', 'Orchard', 'Quarry'])} Road"
    spec["vendors"].append({"id": s, "name": name, "portal_source": portal, "contract_source": contract,
                            "iban_on_contract": old_iban, "iban_on_portal": new_iban,
                            "address": street, "compromised": compromised})
    spec["sources"] += [{"id": portal, "kind": "portal", "trust": 0.4 if compromised else 0.7},
                        {"id": contract, "kind": "pdf", "trust": 0.9}]
    ob, dv = spec["observations"], spec["derivations"]

    def obs(suffix, source, at, text):
        oid = f"{s}_o_{suffix}"
        ob.append({"id": oid, "source": source, "observed_at": at, "text": text})
        return oid

    def der(did, rule, agent, premises, cid, kind, text):
        dv.append({"id": f"{s}_d_{did}", "rule": rule, "agent": agent, "premises": premises,
                   "conclusion": {"id": cid, "kind": kind, "text": text}})
        return cid

    o_bank = obs("bank_new", portal, _at(5, 10), f"{name} portal: bank details changed to IBAN {new_iban}.")
    o_addr = obs("addr_portal", portal, _at(5, 10, 1), f"{name} portal: remit address {street}.")
    o_apdf = obs("addr_pdf", contract, _at(3), f"Signed contract amendment: {name} address {street}.")
    o_old = obs("bank_old", contract, _at(1), f"Signed contract: {name} bank IBAN {old_iban}.")
    o_pre = obs("hours", portal, _at(-3, 8), f"{name} portal: opening hours 06:00-14:00.")
    o_late = obs("closure", portal, _at(12, 8), f"{name} portal: holiday closure notice 2026-10-20.")
    o_po = obs("po", "po-system", _at(1, 12), f"Purchase orders PO-{s}-1 to PO-{s}-{invoices} open for {name}.")

    b_new = der("bank_new", "extract", "intake", [o_bank], f"{s}_b_bank_new", "belief",
                f"{name} bank account is IBAN {new_iban}.")
    last, chain = b_new, [("analyst", "infer"), ("comms", "handoff")]
    for k in range(depth):  # laundering: the claim is restated by agent after agent
        agent, rule = chain[k % 2]
        last = der(f"echo{k}", rule, agent, [last], f"{s}_b_echo{k}", "belief",
                   f"{agent.capitalize()} note: vendor bank updated to {new_iban}.")
    der("addr_portal", "extract", "intake", [o_addr], f"{s}_b_addr", "belief", f"{name} remit address is {street}.")
    der("addr_pdf", "extract", "intake", [o_apdf], f"{s}_b_addr", "belief", f"{name} remit address is {street}.")
    der("old_bank", "extract", "intake", [o_old], f"{s}_b_old_bank", "belief",
        f"Contract bank for {name} is IBAN {old_iban}.")
    der("hours", "extract", "intake", [o_pre], f"{s}_b_hours", "belief", f"{name} opens 06:00-14:00.")
    der("closure", "extract", "intake", [o_late], f"{s}_b_closure", "belief", f"{name} closed on 2026-10-20.")
    a, b = f"{s}_b_circ_a", f"{s}_b_circ_b"  # circular support, grounded only through the portal
    der("circ_a_obs", "infer", "analyst", [o_bank], a, "belief", f"{name} payment channel changed (analyst).")
    der("circ_a_b", "infer", "analyst", [b], a, "belief", f"{name} payment channel changed (analyst).")
    der("circ_b_a", "infer", "comms", [a], b, "belief", f"{name} payment channel changed (comms).")

    for j in range(invoices):
        amount = rnd.randrange(4, 26) * 1000 + rnd.choice([0, 250, 400, 750]) if j == 0 \
            else rnd.randrange(11, 61) * 1000 + rnd.choice([0, 250, 500])
        o_inv = obs(f"inv{j}", "erp", _at(6 + j, 11), f"Invoice INV-{s.upper()}-{j + 1} from {name}, {amount} USD.")
        ok = der(f"inv{j}_ok", "combine", "analyst", [o_inv, o_po], f"{s}_b_inv{j}_ok", "belief",
                 f"INV-{s.upper()}-{j + 1} ({amount} USD) matches an open PO.")
        plan = der(f"plan{j}", "combine", "payments", [ok, last], f"{s}_plan_pay{j}", "plan",
                   f"Pay INV-{s.upper()}-{j + 1} {amount} USD to {new_iban}.")
        executed = j == 0  # first invoice already paid (recorded seed run), the rest still pending
        spec["actions"].append({"id": f"{s}_act_pay{j}", "tool": "pay", "agent": "payments", "amount": amount,
                                "executed": executed, "executed_at": _at(7, 14) if executed else None,
                                "premises": [plan], "vendor": s, "invoice": f"INV-{s.upper()}-{j + 1}"})


def reference_labels(spec):
    """Independent JTMS: least fixpoint of 'IN iff some justification has all premises IN'.
    Returns (in_ids, out_ids) after retracting observations of compromised portals in WINDOW."""
    poisoned = {v["portal_source"] for v in spec["vendors"] if v["compromised"]}
    lo, hi = spec["window"]["from"], spec["window"]["to"]
    live = {o["id"] for o in spec["observations"]
            if not (o["source"] in poisoned and lo <= o["observed_at"] <= hi)}
    just = [(d["premises"], d["conclusion"]["id"]) for d in spec["derivations"]]
    just += [(a["premises"], a["id"]) for a in spec["actions"]]
    allids = {o["id"] for o in spec["observations"]} | {c for _, c in just}
    changed = True
    while changed:
        changed = False
        for prem, concl in just:
            if concl not in live and all(p in live for p in prem):
                live.add(concl)
                changed = True
    return live, allids - live


def _ground_truth(spec):
    live, dead = reference_labels(spec)
    acts = {a["id"]: a for a in spec["actions"]}
    key = lambda ids: sorted(ids)  # noqa: E731
    return {"contaminated": key(dead), "truly_supported": key(live),
            "recall_list": key(i for i in dead if i in acts and acts[i]["executed"]),
            "blocked": key(i for i in dead if i in acts and not acts[i]["executed"])}


def validate(spec):
    """Schema + referential integrity. Returns a list of problems (empty = valid)."""
    bad = []
    for k in ("tenant", "sources", "agents", "observations", "derivations", "actions", "ground_truth"):
        if k not in spec:
            bad.append(f"missing key {k}")
    if bad:
        return bad
    sources = {s["id"] for s in spec["sources"]}
    agents = {a["id"] for a in spec["agents"]}
    ids = [o["id"] for o in spec["observations"]]
    concl = {d["conclusion"]["id"] for d in spec["derivations"]}
    known = set(ids) | concl | {a["id"] for a in spec["actions"]}
    if len(ids) != len(set(ids)):
        bad.append("duplicate observation ids")
    if set(ids) & concl:
        bad.append("observation id reused as conclusion")
    for o in spec["observations"]:
        if o["source"] not in sources:
            bad.append(f"{o['id']}: unknown source {o['source']}")
    for d in spec["derivations"]:
        if d["agent"] not in agents:
            bad.append(f"{d['id']}: unknown agent")
        bad += [f"{d['id']}: unknown premise {p}" for p in d["premises"] if p not in known]
    for a in spec["actions"]:
        bad += [f"{a['id']}: unknown premise {p}" for p in a["premises"] if p not in known]
    for k, v in spec["ground_truth"].items():
        bad += [f"ground_truth.{k}: unknown id {i}" for i in v if i not in known]
    return bad
