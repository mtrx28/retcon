/* Keystone and contradiction panels (A12). Loaded after ops.js; same extension API (ui/shell/README.md). */
(function () {
  "use strict";
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const $ = (id) => document.getElementById(id);
  let R = null, order = "priority", shownBlast = null;

  async function get(path) {
    const r = await fetch(path, { cache: "no-store" });
    const j = await r.json();
    if (j && j.error) throw new Error(j.error.message);
    return j;
  }
  const num = (x) => (x == null ? "n/a" : x >= 0.1 ? x.toFixed(3) : x.toFixed(4));

  // ---- keystones ------------------------------------------------------------------------------
  function mountKeystones(el) {
    el.innerHTML = `
      <div class="row">
        <label class="ops-field" style="flex:1">Order by
          <select id="ks-order" aria-label="Order keystone sources by">
            <option value="priority">audit priority (rank x (1 - trust))</option>
            <option value="rank">PageRank</option>
            <option value="downstream">blast radius</option>
          </select></label>
      </div>
      <div id="ks-body" class="ops-sub">Loading…</div>`;
    $("ks-order").addEventListener("change", (e) => { order = e.target.value; refresh(); });
    el.addEventListener("click", (ev) => {
      const b = ev.target.closest("button[data-blast]");
      if (b) toggleBlast(b.dataset.blast);
    });
    refresh();
  }

  async function toggleBlast(source) {
    R.clearHighlights();
    if (shownBlast === source) { shownBlast = null; refresh(); return; }
    try {
      const j = await get(`/api/ops/blast?graph=${encodeURIComponent(R.graph())}&source=${encodeURIComponent(source)}`);
      R.highlight(j.ids, "--accent");
      shownBlast = source;
      refresh();
    } catch (e) { const b = $("ks-body"); if (b) b.insertAdjacentHTML("afterbegin", `<div class="ops-msg err">${esc(e.message)}</div>`); }
  }

  async function refresh() {
    let j;
    try { j = await get(`/api/ops/keystones?graph=${encodeURIComponent(R.graph())}&top=8&order=${order}`); }
    catch (e) { const b = $("ks-body"); if (b) b.textContent = "Can't load keystones: " + e.message; return; }
    const host = $("ks-body");
    if (!host) return;
    const rows = j.keystones;
    if (!rows.length) { host.innerHTML = `<span class="muted">No sources yet.</span>`; return; }
    const max = Math.max(...rows.map((r) => (order === "downstream" ? r.downstream : order === "rank" ? r.rank : r.priority)), 1e-12);
    host.className = "";
    host.innerHTML = `<ul class="ops-list">${rows.map((r) => {
      const v = order === "downstream" ? r.downstream : order === "rank" ? r.rank : r.priority;
      const pct = Math.max(2, Math.round(100 * v / max));
      return `<li><div class="top"><span><strong>${r.position}.</strong> <code>${esc(r.id)}</code>
          ${r.retracted_at ? `<span class="pill out">retracted ${esc(r.retracted_at)}</span>` : ""}</span>
          <span class="muted">trust ${r.trust.toFixed(2)}</span></div>
        <div class="ks-bar" role="img" aria-label="${esc(order)} ${pct}% of the top source"><i style="width:${pct}%"></i></div>
        <div class="ops-sub">rank ${num(r.rank)} · priority ${num(r.priority)} · ${r.observations} obs ·
          <strong>${r.downstream}</strong> memories rest on it (${r.live_downstream} still IN)</div>
        <div class="acts"><button class="btn" data-blast="${esc(r.id)}" aria-pressed="${shownBlast === r.id}">
          ${shownBlast === r.id ? "Hide" : "Show"} what rests on it</button></div></li>`;
    }).join("")}</ul>`;
  }

  // ---- contradictions -------------------------------------------------------------------------
  function mountContradictions(el) {
    el.innerHTML = `<div id="cx-body" class="ops-sub">Loading…</div>`;
    el.addEventListener("click", (ev) => {
      const b = ev.target.closest("button[data-id]");
      if (b) { R.select(b.dataset.id); R.centerOn(b.dataset.id); }
    });
    refreshContradictions();
  }
  async function refreshContradictions() {
    let j;
    try { j = await get(`/api/ops/contradictions?graph=${encodeURIComponent(R.graph())}`); } catch (e) { return; }
    const host = $("cx-body");
    if (!host) return;
    if (!j.clusters.length) { host.innerHTML = `<span class="muted">No conflicting beliefs.</span>`; return; }
    host.className = "";
    host.innerHTML = `<ul class="ops-list">${j.clusters.map((c) => `
      <li><div class="top"><span>${esc(c.subject || "?")} <span class="muted">(${esc(c.attribute || "?")})</span></span>
        <span class="pill ${c.resolved ? "in" : "tentative"}">${c.resolved ? "resolved" : "in conflict"}</span></div>
        ${c.members.map((m) => `<div class="ops-sub"><span class="pill ${m.status === "IN" ? "in" : "out"}">${esc(m.status)}</span>
          <button class="ops-id" data-id="${esc(m.id)}" title="${esc(m.text)}">${esc((m.text || m.id).slice(0, 52))}</button>
          <span class="muted">${esc(m.agent || "")}${m.sources.length ? " · from " + esc(m.sources.join(", ")) : ""}</span></div>`).join("")}</li>`).join("")}</ul>`;
  }

  window.RETCON.on("ready", (retcon) => {
    R = retcon;
    R.panels.add({ id: "keystones", title: "Keystone sources", mount: mountKeystones });
    R.panels.add({ id: "contradictions", title: "Contradictions", mount: mountContradictions });
    setInterval(() => { refresh(); refreshContradictions(); }, 8000);
    // retractions change what is IN: refresh straight away
    R.on("delta", () => { /* the interval picks it up; keeps the poll cheap while idle */ });
  });
})();
