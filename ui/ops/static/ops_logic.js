/* Pure helpers for the operator panels (A6). No DOM: unit-tested with `node --test tests/ui`. */
(function (root) {
  "use strict";

  const KIND_LABEL = { observation: "observation", belief: "belief", plan: "plan", action: "action" };

  /** {obs, beliefs, plans, actions} from a distrust/preview payload (`flipped`). */
  function counts(res) {
    const f = (res && res.flipped) || {};
    return { observations: f.observations || 0, beliefs: f.beliefs || 0, plans: f.plans || 0, actions: f.actions || 0 };
  }

  function plural(n, one, many) { return n + " " + (n === 1 ? one : (many || one + "s")); }

  /** The headline the operator reads: "1 source → 2 observations → 5 beliefs → 2 plans → 2 actions". */
  function cascadeLine(res) {
    const c = counts(res);
    const parts = ["1 source", plural(c.observations, "observation"), plural(c.beliefs, "belief"),
      plural(c.plans, "plan"), plural(c.actions, "action")];
    return parts.join(" → ");
  }

  /** Consequences line: pending blocked, executed to recall, kept by independent support. */
  function consequenceLine(res) {
    const blocked = (res.blocked_action_ids || []).length;
    const recall = (res.recall_list || []).length;
    const kept = (res.survived_ids || []).length;
    return [plural(blocked, "pending action") + " blocked",
      plural(recall, "executed action") + " to recall",
      kept + " kept by independent support"].join(" · ");
  }

  /** hops: {"0": [ids], "1": [...]} -> [{hop, ids}] sorted by hop. */
  function hopGroups(hops) {
    return Object.keys(hops || {}).map(Number).sort((a, b) => a - b).map((h) => ({ hop: h, ids: hops[String(h)] || hops[h] || [] }));
  }

  /** Timeline for the cascade animation: one step per hop, stepMs apart. */
  function schedule(hops, stepMs) {
    return hopGroups(hops).map((g, i) => ({ at: i * stepMs, hop: g.hop, ids: g.ids }));
  }

  /** Group a preview `diff` by kind for the summary table. */
  function byKind(diff) {
    const out = {};
    for (const d of diff || []) (out[d.kind] = out[d.kind] || []).push(d.id);
    return out;
  }

  /** <input type=datetime-local> value ("2026-10-02T00:00") -> ISO Z. Treated as UTC, like the data. */
  function localToIso(v) {
    if (!v) return null;
    const m = /^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})(?::(\d{2}))?/.exec(v);
    return m ? `${m[1]}T${m[2]}:${m[3] || "00"}Z` : null;
  }

  /** epoch seconds -> datetime-local string in UTC. */
  function epochToLocal(sec) {
    if (sec == null) return "";
    return new Date(sec * 1000).toISOString().slice(0, 16);
  }

  function fmtMs(x) {
    if (x == null) return "n/a";
    return x >= 100 ? Math.round(x) + " ms" : x >= 1 ? x.toFixed(1) + " ms" : x.toFixed(3) + " ms";
  }

  /** "$18,400" for amounts; "no amount" for actions without one. */
  function money(a) {
    return a == null ? "no amount" : "$" + Number(a).toLocaleString("en-US");
  }

  const api = { counts, cascadeLine, consequenceLine, hopGroups, schedule, byKind, localToIso, epochToLocal, fmtMs, money, KIND_LABEL };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.OpsLogic = api;
})(typeof window !== "undefined" ? window : globalThis);
