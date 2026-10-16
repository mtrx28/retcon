"""Incident report (upgrade 3): one retraction, written down for the people who have to act on it.

    report = build(g, "ret_0001")          # or build(g) for the most recent active retraction
    markdown(report), html(report)         # the same facts, as a document to hand over or print

Everything comes from the graph, nothing is estimated: what was retracted and why, which payments to recall
or hold, what still stands and on whose evidence, and which sources deserve an audit first. The audit list is
a priority, not a detection: RETCON does not know which source is compromised, only where the most memory
rests on the least trusted evidence.
"""
import html as _html
import json
import time

from agents import remediator
from core.analytics import keystone
from core.db import fetch_all
from core.errors import RetconError
from core.recall.recall_list import blocked_actions, recall_list
from core.retract.why import why
from core.retrieve.q2 import support

CAVEAT = ("Audit priority, not detection: this report lists where the most memory rests on the least trusted "
          "evidence. It does not claim to know which source is compromised.")


def _iso(epoch):
    return time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(epoch)) if epoch else "unknown"


def _kind(labels):
    return next((k.lower() for k in ("Observation", "Belief", "Plan", "Action") if k in labels), "mem")


def _args(raw):
    try:
        return json.loads(raw or "{}")
    except ValueError:
        return {}


def _poisoned_path(tree, source):
    """Texts from this node down to an observation of `source`, following the first justification that
    reaches it (the chain a human would read: payment <- plan <- belief <- the portal's claim)."""
    if tree.get("source", {}).get("id") == source:
        return [tree.get("text") or tree["id"]]
    for j in tree.get("justifications", []):
        for p in j.get("premises", []):
            sub = _poisoned_path(p, source) if not p.get("cycle") else None
            if sub:
                return [tree.get("text") or tree["id"]] + sub
    return None


def build(g, retraction_id=None, graph_name=None):
    if retraction_id is None:
        rows = g.query("MATCH (r:Retraction {reinstated:false}) RETURN r.id ORDER BY r.id DESC LIMIT 1").result_set
        if not rows:
            raise RetconError("NOT_FOUND", "no active retraction in this graph", {})
        retraction_id = rows[0][0]
    row = g.query("MATCH (r:Retraction {id:$i}) RETURN properties(r)", {"i": retraction_id}).result_set
    if not row:
        raise RetconError("NOT_FOUND", f"retraction {retraction_id!r}", {"retraction_id": retraction_id})
    r = dict(row[0][0])
    source = r["source"]

    flipped = fetch_all(
        g, "MATCH (:Retraction {id:$i})-[e:RETRACTED]->(x:Mem) WHERE e.flipped = true "
           "RETURN x.id AS id, labels(x), x.text, x.amount, x.executed, x.args, x.agent, e.hop, x.tool",
        {"i": retraction_id},
        order_by="id")
    counts = {"observations": 0, "beliefs": 0, "plans": 0, "actions": 0}
    plural = {"observation": "observations", "belief": "beliefs", "plan": "plans", "action": "actions"}
    acts = []
    for xid, labels, text, amount, executed, args, agent, hop, tool in flipped:
        kind = _kind(labels)
        counts[plural.get(kind, "beliefs")] += 1
        if kind == "action":
            a = _args(args)
            acts.append({"id": xid, "tool": tool or ("pay" if a.get("iban") else "email"),
                         "amount": amount, "executed": bool(executed), "agent": agent,
                         "vendor": a.get("vendor"), "invoice": a.get("invoice"), "iban": a.get("iban"),
                         "subject": a.get("subject"), "to": a.get("to")})
    for a in acts:
        a["rested_on"] = _poisoned_path(why(g, a["id"], 12), source) or []
    payments_paid = sorted([a for a in acts if a["tool"] == "pay" and a["executed"]], key=lambda a: -(a["amount"] or 0))
    payments_held = sorted([a for a in acts if a["tool"] == "pay" and not a["executed"]], key=lambda a: -(a["amount"] or 0))
    messages = [a for a in acts if a["tool"] != "pay"]

    remeds = [m for m in remediator.list_remediations(g) if m.get("retraction_id") == retraction_id]

    blast = keystone.blast_radius(g, source)
    live = [x for x in fetch_all(g, "MATCH (m:Mem) WHERE m.id IN $ids AND m.status = 'IN' AND NOT m:Observation "
                                    "RETURN m.id AS id, m.text, labels(m)", {"ids": blast}, order_by="id")]
    survivors = []
    for sid, text, labels in live:
        if _kind(labels) != "belief":
            continue
        sup = support(g, sid)
        others = sorted(set(sup) - {source})
        survivors.append({"id": sid, "text": text, "sources": sorted(sup), "independent": len(sup),
                          # corroborated: another source also supports it; otherwise it rests only on this
                          # source's evidence that lies outside the retracted window
                          "why_stayed": "corroborated" if others else "outside_window", "other_sources": others})
    survivors.sort(key=lambda s: (s["why_stayed"] != "corroborated", -s["independent"], s["id"]))

    ks = keystone.keystones(g, 5)
    total = sum(a["amount"] or 0 for a in payments_paid)
    return {
        "graph": graph_name or getattr(g, "name", ""), "generated": _iso(time.time()),
        "retraction": {"id": retraction_id, "source": source, "from": _iso(r.get("from")), "to": _iso(r.get("to")),
                       "reason": r.get("reason"), "operator": r.get("operator"), "at": _iso(r.get("at")),
                       "reinstated": bool(r.get("reinstated"))},
        "counts": counts, "paid": payments_paid, "held": payments_held, "messages": messages,
        "paid_total": total, "held_total": sum(a["amount"] or 0 for a in payments_held),
        "remediations": [{"id": m["id"], "kind": m["kind"], "status": m["status"], "title": m["title"],
                          "amount": m.get("amount")} for m in remeds],
        "survivors": survivors[:10], "survivor_count": len(survivors),
        "corroborated_count": sum(1 for s in survivors if s["why_stayed"] == "corroborated"),
        "audit_priority": [{"source": k["id"], "kind": k["kind"], "trust": k["trust"], "live_downstream": k["live_downstream"],
                            "retracted": bool(k.get("retracted_at"))} for k in ks],
        "caveat": CAVEAT,
    }


def _money(x):
    return "n/a" if x is None else f"{x:,.0f} USD"


def markdown(r):
    t, c = r["retraction"], r["counts"]
    out = [f"# Incident report: {t['source']} distrusted", "",
           f"Retraction `{t['id']}` on graph `{r['graph']}`, generated {r['generated']}.",
           f"Window: {t['from']} to {t['to']}. Operator: {t['operator']}. Recorded {t['at']}."
           + (" **This retraction has been reinstated.**" if t["reinstated"] else ""), ""]
    out += ["## What happened", "",
            f"- Reason on record: {t['reason']}",
            f"- Retracted: {c['observations']} observations, {c['beliefs']} beliefs, {c['plans']} plans, "
            f"{c['actions']} actions.",
            f"- Downstream of this source but still standing: {r['survivor_count']} beliefs "
            f"({r['corroborated_count']} confirmed by another source, the rest rest on this source's evidence outside the window).",
            f"- Nothing was deleted. The retraction can be reversed exactly (`reinstate {t['id']}`).", ""]
    out += ["## What to do now", ""]
    if r["paid"]:
        out += [f"### Payments already made on retracted beliefs: {len(r['paid'])}, {_money(r['paid_total'])} in total. Recall them", "",
                "| Payment | Amount | Vendor | Invoice | It rested on |", "|---|---:|---|---|---|"]
        for a in r["paid"]:
            out.append(f"| `{a['id']}` | {_money(a['amount'])} | {a['vendor'] or ''} | {a['invoice'] or ''} | "
                       f"{' <- '.join(a['rested_on'][-2:]) or 'see why'} |")
        out.append("")
    else:
        out += ["No executed payment depended on this source.", ""]
    if r["held"]:
        out += [f"### Payments not yet made, now blocked: {len(r['held'])}, {_money(r['held_total'])} in total", "",
                "| Payment | Amount | Vendor | Invoice |", "|---|---:|---|---|"]
        out += [f"| `{a['id']}` | {_money(a['amount'])} | {a['vendor'] or ''} | {a['invoice'] or ''} |" for a in r["held"]]
        out.append("")
    if r["messages"]:
        out += [f"### Messages sent on retracted beliefs ({len(r['messages'])}): correct", ""]
        out += [f"- `{a['id']}` {a['tool']}" + (f" to {a['to']}: {a['subject']}" if a.get("to") else "") for a in r["messages"]]
        out.append("")
    if r["remediations"]:
        out += ["### Drafted compensations (nothing is sent until a person approves)", "",
                "| Draft | Kind | Status | Amount |", "|---|---|---|---:|"]
        out += [f"| {m['title']} | {m['kind']} | {m['status']} | {_money(m['amount'])} |" for m in r["remediations"]]
        out.append("")
    out += ["## What still stands", ""]
    if r["survivors"]:
        out += ["These beliefs were downstream of the source and stayed. A belief confirmed by another source needs nothing; "
                "one that rests only on this source's evidence from outside the window is still worth a look.", "",
                "| Belief | Why it stayed | Sources |", "|---|---|---|"]
        out += [f"| {s['text']} | {'confirmed by ' + ', '.join(s['other_sources']) if s['why_stayed'] == 'corroborated' else 'evidence outside the window'} "
                f"| {', '.join(s['sources'])} |" for s in r["survivors"]]
        out.append("")
    else:
        out += ["Nothing downstream of this source had independent support.", ""]
    out += ["## Audit these sources first", "",
            "| Source | Kind | Trust | Live memories resting on it |", "|---|---|---:|---:|"]
    out += [f"| {k['source']}{' (retracted)' if k['retracted'] else ''} | {k['kind']} | {k['trust']} | {k['live_downstream']} |"
            for k in r["audit_priority"]]
    out += ["", f"_{r['caveat']}_", "", "---", "Generated by RETCON from the justification graph in FalkorDB. "
            "Every row above can be traced with `why <node id>`."]
    return "\n".join(out) + "\n"


def html(r):
    """The same report as a self-contained page that prints cleanly (no scripts, no external files)."""
    e = _html.escape
    t, c = r["retraction"], r["counts"]

    def table(head, rows, right=()):
        th = "".join(f"<th{' class=r' if i in right else ''}>{e(h)}</th>" for i, h in enumerate(head))
        tr = "".join("<tr>" + "".join(f"<td{' class=r' if i in right else ''}>{e(str(v))}</td>" for i, v in enumerate(row)) + "</tr>"
                     for row in rows)
        return f"<table><thead><tr>{th}</tr></thead><tbody>{tr}</tbody></table>"

    parts = [f"<h1>Incident report: {e(t['source'])} distrusted</h1>",
             f"<p class=meta>Retraction {e(t['id'])} on graph {e(r['graph'])}, generated {e(r['generated'])}. "
             f"Window {e(t['from'])} to {e(t['to'])}. Operator {e(t['operator'] or '')}.</p>"
             + ("<p class=warn>This retraction has been reinstated.</p>" if t["reinstated"] else ""),
             "<h2>What happened</h2><ul>"
             f"<li>Reason on record: {e(str(t['reason']))}</li>"
             f"<li>Retracted: {c['observations']} observations, {c['beliefs']} beliefs, {c['plans']} plans, {c['actions']} actions.</li>"
             f"<li>Downstream of this source but still standing: {r['survivor_count']} beliefs "
             f"({r['corroborated_count']} confirmed by another source, the rest rest on this source's evidence outside the window).</li>"
             f"<li>Nothing was deleted; the retraction can be reversed exactly.</li></ul>",
             "<h2>What to do now</h2>"]
    if r["paid"]:
        parts += [f"<h3>Payments already made on retracted beliefs: {len(r['paid'])}, {_money(r['paid_total'])} in total. Recall them</h3>",
                  table(["Payment", "Amount", "Vendor", "Invoice", "It rested on"],
                        [(a["id"], _money(a["amount"]), a["vendor"] or "", a["invoice"] or "",
                          " <- ".join(a["rested_on"][-2:])) for a in r["paid"]], right=(1,))]
    else:
        parts.append("<p>No executed payment depended on this source.</p>")
    if r["held"]:
        parts += [f"<h3>Payments not yet made, now blocked: {len(r['held'])}, {_money(r['held_total'])} in total</h3>",
                  table(["Payment", "Amount", "Vendor", "Invoice"],
                        [(a["id"], _money(a["amount"]), a["vendor"] or "", a["invoice"] or "") for a in r["held"]], right=(1,))]
    if r["messages"]:
        parts += ["<h3>Messages sent on retracted beliefs: correct</h3><ul>"
                  + "".join(f"<li>{e(a['id'])} {e(a['tool'])} {e(a.get('subject') or '')}</li>" for a in r["messages"]) + "</ul>"]
    if r["remediations"]:
        parts += ["<h3>Drafted compensations (nothing is sent until a person approves)</h3>",
                  table(["Draft", "Kind", "Status", "Amount"],
                        [(m["title"], m["kind"], m["status"], _money(m["amount"])) for m in r["remediations"]], right=(3,))]
    parts.append("<h2>What still stands</h2>")
    parts.append(table(["Belief", "Why it stayed", "Sources"],
                       [(s["text"], ("confirmed by " + ", ".join(s["other_sources"])) if s["why_stayed"] == "corroborated"
                         else "evidence outside the window", ", ".join(s["sources"])) for s in r["survivors"]])
                 if r["survivors"] else "<p>Nothing downstream of this source had independent support.</p>")
    parts += ["<h2>Audit these sources first</h2>",
              table(["Source", "Kind", "Trust", "Live memories resting on it"],
                    [(k["source"] + (" (retracted)" if k["retracted"] else ""), k["kind"], k["trust"], k["live_downstream"])
                     for k in r["audit_priority"]], right=(2, 3)),
              f"<p class=note>{e(r['caveat'])}</p>",
              "<footer>Generated by RETCON from the justification graph in FalkorDB. Every row can be traced with why.</footer>"]
    css = ("body{font:16px/1.5 Georgia,'Times New Roman',serif;color:#1b1b1f;max-width:46rem;margin:2rem auto;padding:0 1rem}"
           "h1{font-size:1.9rem;line-height:1.15;margin:0 0 .4rem}h2{font-size:1.25rem;margin:2rem 0 .5rem}h3{font-size:1.05rem;margin:1.4rem 0 .4rem}"
           ".meta{color:#555;margin:0 0 1rem}.warn{background:#ffe9e6;padding:.5rem .75rem}.note{color:#555;font-style:italic}"
           "table{border-collapse:collapse;width:100%;font:14px/1.4 system-ui,sans-serif;margin:.4rem 0 1rem}"
           "th,td{text-align:left;padding:.35rem .5rem;border-bottom:1px solid #ddd;vertical-align:top}th{background:#f3f3f5}"
           ".r{text-align:right}footer{margin-top:2.5rem;color:#666;font-size:.85rem}"
           "@media print{body{margin:0;max-width:none}}")
    return (f"<!doctype html><html lang=en><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
            f"<title>Incident report {e(t['id'])}</title><style>{css}</style></head><body>{''.join(parts)}</body></html>")
