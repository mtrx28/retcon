/* Graph state for the shell: nodes, edges, change application, filters. No DOM, so it runs under Node tests. */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.RetconStore = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  class GraphStore {
    constructor() { this.reset(); }

    reset() {
      this.nodes = new Map();
      this.edges = [];
      this._edgeKeys = new Set();
      this.out = new Map();   // id -> [edge]
      this.inc = new Map();   // id -> [edge]
      this.version = 0;
      this.serverCounts = {};
      this.truncated = false;
    }

    _addEdge(e) {
      const key = e.s + ">" + e.t + ":" + e.type;
      if (this._edgeKeys.has(key)) return false;
      this._edgeKeys.add(key);
      this.edges.push(e);
      if (!this.out.has(e.s)) this.out.set(e.s, []);
      if (!this.inc.has(e.t)) this.inc.set(e.t, []);
      this.out.get(e.s).push(e);
      this.inc.get(e.t).push(e);
      return true;
    }

    load(snap) {
      this.reset();
      for (const n of snap.nodes) this.nodes.set(n.id, Object.assign({}, n));
      for (const e of snap.edges) this._addEdge(Object.assign({}, e));
      this.version = snap.version || 0;
      this.serverCounts = snap.counts || {};
      this.truncated = !!snap.truncated;
    }

    /** Apply a /api/delta payload. Returns {added: [ids], changed: [{id, from, to}], edges: n}. */
    applyDelta(d) {
      const res = { added: [], changed: [], edges: 0 };
      for (const n of d.nodes || []) {
        if (!this.nodes.has(n.id)) { this.nodes.set(n.id, Object.assign({}, n)); res.added.push(n.id); }
      }
      for (const e of d.edges || []) if (this._addEdge(Object.assign({}, e))) res.edges++;
      for (const u of d.updates || []) {
        const n = this.nodes.get(u.id);
        if (!n) continue;
        const before = n.status;
        for (const k of Object.keys(u)) if (k !== "id") n[k] = u[k];
        res.changed.push({ id: u.id, from: before, to: n.status });
      }
      if (d.version) this.version = d.version;
      if (d.counts) this.serverCounts = d.counts;
      return res;
    }

    /** A justification is live iff every premise is IN (the AND). */
    justificationLive(jid) {
      const prem = (this.inc.get(jid) || []).filter((e) => e.type === "PREMISE_OF");
      return prem.length > 0 && prem.every((e) => (this.nodes.get(e.s) || {}).status === "IN");
    }

    /** Displayed state of a node: IN | OUT | TENTATIVE (mid-cascade) | null (sources, justifications). */
    state(n) {
      if (n.kind === "source") return n.retracted_at ? "OUT" : null;
      if (n.kind === "justification") return this.justificationLive(n.id) ? "IN" : "OUT";
      if (n.run) return "TENTATIVE";
      return n.status || null;
    }

    counts() {
      const c = { IN: 0, OUT: 0, TENTATIVE: 0, nodes: 0, edges: this.edges.length, byKind: {} };
      for (const n of this.nodes.values()) {
        if (n.kind === "justification") continue;
        c.nodes++;
        c.byKind[n.kind] = (c.byKind[n.kind] || 0) + 1;
        if (n.kind === "source") continue;
        c[this.state(n)] = (c[this.state(n)] || 0) + 1;
      }
      return c;
    }

    /** Ids reachable upstream (what `id` rests on) and downstream (what rests on it). */
    lineage(id) {
      const walk = (start, adj, pick) => {
        const seen = new Set([start]), q = [start];
        while (q.length) {
          const cur = q.pop();
          for (const e of adj.get(cur) || []) {
            const nxt = pick(e);
            if (!seen.has(nxt)) { seen.add(nxt); q.push(nxt); }
          }
        }
        seen.delete(start);
        return seen;
      };
      return {
        up: walk(id, this.inc, (e) => e.s),
        down: walk(id, this.out, (e) => e.t),
      };
    }

    /** filter: {kinds:Set|null, states:Set|null, mtypes:Set|null, agent:string|null, query:string} */
    visible(filter) {
      const f = filter || {};
      const q = (f.query || "").trim().toLowerCase();
      const ok = new Set();
      for (const n of this.nodes.values()) {
        if (f.kinds && !f.kinds.has(n.kind)) continue;
        if (n.kind !== "justification" && n.kind !== "source") {
          if (f.states && !f.states.has(this.state(n))) continue;
          if (f.mtypes && n.mtype && !f.mtypes.has(n.mtype)) continue;
          if (f.agent && n.agent !== f.agent) continue;
        }
        if (q && !((n.label || "").toLowerCase().includes(q) || n.id.toLowerCase().includes(q))) continue;
        ok.add(n.id);
      }
      return ok;
    }

    agents() {
      return [...new Set([...this.nodes.values()].map((n) => n.agent).filter(Boolean))].sort();
    }
  }

  return { GraphStore };
});
