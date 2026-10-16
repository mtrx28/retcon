/* Operator panels for the shell (A6): distrust with preview -> commit, hop-by-hop cascade animation,
   recall list with drafted compensations (approve / reject), retraction history with reinstate.
   Extension API: ui/shell/README.md. Pure helpers live in ops_logic.js. */
(function () {
  "use strict";
  const L = window.OpsLogic;
  const STEP_MS = 700;                       // one cascade hop per step
  let R = null, token = null, lastPreview = null, animTimers = [];

  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const $ = (id) => document.getElementById(id);

  async function get(path) {
    const r = await fetch(path, { cache: "no-store" });
    const j = await r.json();
    if (j && j.error) throw new Error(j.error.message);
    return j;
  }
  async function post(path, body) {
    const r = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(Object.assign({ token, graph: R.graph() }, body)) });
    const j = await r.json();
    if (j && j.error) throw new Error(j.error.message);
    return j;
  }
  function say(text, isErr) { const m = $("ops-msg"); if (m) { m.textContent = text || ""; m.className = "ops-msg" + (isErr ? " err" : ""); } }
  function idButtons(ids, cls) {
    return ids.map((id) => `<button class="ops-id ${cls || ""}" data-id="${esc(id)}" title="${esc(id)}">${esc(label(id))}</button>`).join("");
  }
  function label(id) {
    const n = R.store.nodes.get(id);
    const t = n && (n.label || n.text);
    return t ? String(t).slice(0, 38) : id;
  }
  function clearAnim() { animTimers.forEach(clearTimeout); animTimers = []; }

  // ---- distrust panel -------------------------------------------------------------------------
  function mountDistrust(el) {
    el.innerHTML = `
      <div class="ops-grid">
        <label class="ops-field">Source <select id="ops-source" aria-label="Source to distrust"></select></label>
        <label class="ops-field">From (UTC) <input type="datetime-local" id="ops-from"></label>
        <label class="ops-field">To (UTC) <input type="datetime-local" id="ops-to"></label>
      </div>
      <div class="row">
        <button class="btn" id="ops-preview">Preview</button>
        <button class="btn danger" id="ops-commit">Commit</button>
      </div>
      <div id="ops-msg" class="ops-msg" role="status" aria-live="polite"></div>
      <div id="ops-result" hidden></div>`;
    el.addEventListener("click", onClick);
    $("ops-source").addEventListener("change", prefill);
    $("ops-preview").addEventListener("click", () => run("preview"));
    $("ops-commit").addEventListener("click", () => run("commit"));
    loadSources();
  }

  let sources = [];
  async function loadSources() {
    try {
      sources = (await get("/api/ops/sources?graph=" + encodeURIComponent(R.graph()))).sources;
    } catch (e) { say("Can't load sources: " + e.message, true); return; }
    const sel = $("ops-source"), cur = sel.value;
    sel.innerHTML = sources.map((s) => `<option value="${esc(s.id)}">${esc(s.id)} (${s.observations} obs, ${esc(s.kind)})</option>`).join("");
    if (cur) sel.value = cur;
    if (!$("ops-from").value) prefill();
  }
  function prefill() {
    const s = sources.find((x) => x.id === $("ops-source").value);
    if (!s) return;
    $("ops-from").value = L.epochToLocal(s.first);
    $("ops-to").value = L.epochToLocal(s.last);
  }

  async function run(mode) {
    const body = { source: $("ops-source").value, from: L.localToIso($("ops-from").value),
      to: L.localToIso($("ops-to").value), mode };
    if (!body.source || !body.from || !body.to) return say("Choose a source and a window.", true);
    if (mode === "commit" && !confirm(`Commit: retract everything resting only on ${body.source} between ${body.from} and ${body.to}?`)) return;
    setBusy(true); clearAnim(); R.clearHighlights();
    try {
      say(mode === "preview" ? "Forking the graph and running the cascade…" : "Committing…");
      const res = await post("/api/ops/distrust", body);
      say("");
      show(res, body);
      if (mode === "preview") {
        lastPreview = { res, body };
        R.highlight(res.flipped_ids, "--out");
        R.highlight(res.survived_ids || [], "--in");
      } else {
        lastPreview = null;
        animate(res);
        R.refresh && R.refresh();
        refreshRecall(); refreshHistory();
      }
    } catch (e) { say(e.message, true); }
    finally { setBusy(false); }
  }
  function setBusy(b) { ["ops-preview", "ops-commit"].forEach((i) => { const x = $(i); if (x) x.disabled = b; }); }

  function show(res, body) {
    const isPrev = !!res.preview;
    const groups = L.hopGroups(res.hops);
    const kept = res.survived_ids || [];
    const prof = res.profile && res.profile.execution_ms;
    const badge = $("ops-badge");
    if (badge) badge.innerHTML = `cascade <strong>${esc(L.fmtMs(res.latency_ms))}</strong> · engine <strong>${esc(L.fmtMs(prof))}</strong> <span class="muted">GRAPH.PROFILE</span>`;
    $("ops-result").hidden = false;
    $("ops-result").className = "ops-result";
    $("ops-result").innerHTML = `
      <h3><span class="pill ${isPrev ? "prev" : "in"}">${isPrev ? "PREVIEW" : "COMMITTED"}</span> <code>${esc(res.retraction_id)}</code></h3>
      <p class="ops-clock">${isPrev ? "preview on a copy" : "committed " + new Date().toISOString().slice(11, 19) + "Z"} · T+ is the replay clock, one hop every ${STEP_MS / 1000}s</p>
      <div class="ops-line" id="ops-line">${esc(L.cascadeLine(res))}</div>
      <div class="ops-sub">${esc(L.consequenceLine(res))}</div>
      <ol class="ops-hops" id="ops-hops" aria-label="Cascade by hop">
        ${groups.map((g, i) => `<li data-hop="${g.hop}"${isPrev ? "" : ' class="queued"'}><span class="t">T+${(i * STEP_MS / 1000).toFixed(1)}s</span><strong>hop ${g.hop}</strong><span class="ids">${idButtons(g.ids)}</span></li>`).join("")}
      </ol>
      ${kept.length ? `<div class="ops-sub">Stays IN: independent support</div><div class="ids" style="display:flex;flex-wrap:wrap;gap:4px">${idButtons(kept, "kept")}</div>` : ""}
      ${isPrev ? `<div class="row" style="margin-top:10px"><button class="btn danger" id="ops-commit-prev">Commit this retraction</button><button class="btn" id="ops-dismiss">Dismiss</button></div>
        <div class="ops-sub">Preview ran on a GRAPH.COPY fork; the live graph is unchanged.</div>` : ""}`;
  }

  function animate(res) {
    const steps = L.schedule(res.hops, STEP_MS);
    steps.forEach((s) => animTimers.push(setTimeout(() => {
      R.highlight(s.ids, "--tent");
      R.flash(s.ids, "out");
      const li = document.querySelector(`#ops-hops li[data-hop="${s.hop}"]`);
      document.querySelectorAll("#ops-hops li.active").forEach((x) => x.classList.remove("active"));
      if (li) { li.classList.remove("queued"); li.classList.add("active"); li.scrollIntoView && li.scrollIntoView({ block: "nearest" }); }
    }, s.at)));
    animTimers.push(setTimeout(() => {
      R.highlight(res.flipped_ids, null);
      R.highlight(res.survived_ids || [], "--in");
      R.flash(res.survived_ids || [], "in");
      document.querySelectorAll("#ops-hops li.active").forEach((x) => x.classList.remove("active"));
    }, steps.length * STEP_MS + 300));
  }

  function onClick(ev) {
    const b = ev.target.closest("button");
    if (!b) return;
    if (b.dataset.id) { R.select(b.dataset.id); R.centerOn(b.dataset.id); return; }
    if (b.id === "ops-dismiss") { R.clearHighlights(); $("ops-result").hidden = true; lastPreview = null; }
    if (b.id === "ops-commit-prev" && lastPreview) run("commit");
  }

  // ---- recall + remediation panel ------------------------------------------------------------
  function mountRecall(el) {
    el.innerHTML = `<div id="recall-body" class="ops-sub">Loading…</div>`;
    el.addEventListener("click", async (ev) => {
      const b = ev.target.closest("button");
      if (!b) return;
      if (b.dataset.id && !b.dataset.act) { R.select(b.dataset.id); R.centerOn(b.dataset.id); return; }
      if (b.dataset.act) {
        b.disabled = true;
        try {
          if (b.dataset.act === "approve" && !confirm("Approve this compensation? It will be carried out now.")) { b.disabled = false; return; }
          await post("/api/ops/remediation", { id: b.dataset.rem, action: b.dataset.act });
          say(`Remediation ${b.dataset.act}d.`);
        } catch (e) { say(e.message, true); }
        refreshRecall();
      }
    });
    refreshRecall();
  }
  async function refreshRecall() {
    let st;
    try { st = await get("/api/ops/recall?graph=" + encodeURIComponent(R.graph())); } catch (e) { return; }
    const host = $("recall-body");
    if (!host) return;
    const recall = st.recall, rems = st.remediations;
    if (!recall.length && !rems.length) { host.innerHTML = `<span class="muted">Nothing to recall. Executed actions that lose support appear here.</span>`; return; }
    host.className = "";
    host.innerHTML = `
      <div class="ops-sub">Executed on retracted beliefs, largest first</div>
      <ul class="ops-list">${recall.map((a) => `
        <li><div class="top"><span><button class="ops-id" data-id="${esc(a.action_id)}">${esc(a.tool)} · ${esc(a.agent || "?")}</button></span>
        <span class="amt">${esc(L.money(a.amount))}</span></div>
        <div class="ops-sub">${esc(a.retraction_id)}</div></li>`).join("") || `<li class="muted">None</li>`}</ul>
      <div class="ops-sub" style="margin-top:10px">Drafted compensations (nothing is sent until you approve)</div>
      <ul class="ops-list">${rems.map((r) => `
        <li><div class="top"><span>${esc(r.title)}</span><span class="pill ${esc(r.status)}">${esc(r.status)}</span></div>
        <div class="ops-sub">${esc(r.kind)} · ${esc(L.money(r.amount))}${r.error ? ` · <span class="err">${esc(r.error)}</span>` : ""}</div>
        ${r.status === "draft" ? `<div class="acts">
          <button class="btn primary" data-act="approve" data-rem="${esc(r.id)}">Approve</button>
          <button class="btn" data-act="reject" data-rem="${esc(r.id)}">Reject</button></div>` : ""}</li>`).join("") || `<li class="muted">None</li>`}</ul>`;
  }

  // ---- history panel --------------------------------------------------------------------------
  function mountHistory(el) {
    el.innerHTML = `<div id="history-body" class="ops-sub">Loading…</div>`;
    el.addEventListener("click", async (ev) => {
      const b = ev.target.closest("button[data-reinstate]");
      if (!b) return;
      if (!confirm(`Reinstate ${b.dataset.reinstate}? Everything it retracted is re-derived.`)) return;
      b.disabled = true;
      try {
        const r = await post("/api/ops/reinstate", { retraction_id: b.dataset.reinstate });
        say(`Reinstated ${b.dataset.reinstate}: ${r.restored_count} nodes back.`);
        R.refresh && R.refresh();
      } catch (e) { say(e.message, true); }
      refreshHistory(); refreshRecall();
    });
    refreshHistory();
  }
  async function refreshHistory() {
    let st;
    try { st = await get("/api/ops/recall?graph=" + encodeURIComponent(R.graph())); } catch (e) { return; }
    const host = $("history-body");
    if (!host) return;
    if (!st.retractions.length) { host.innerHTML = `<span class="muted">No retractions yet.</span>`; return; }
    host.className = "";
    host.innerHTML = `<ul class="ops-list">${st.retractions.map((r) => `
      <li><div class="top"><code>${esc(r.id)}</code>
        <span class="pill ${r.reinstated ? "withdrawn" : "out"}">${r.reinstated ? "reinstated" : "active"}</span></div>
        <div class="ops-sub">${esc(r.source)} · ${esc(L.epochToLocal(r.from).replace("T", " "))} → ${esc(L.epochToLocal(r.to).replace("T", " "))}</div>
        <div class="acts">${r.reinstated ? "" : `<button class="btn" data-reinstate="${esc(r.id)}">Reinstate</button>`}
          <a class="btn" target="_blank" rel="noopener" href="/api/report?graph=${encodeURIComponent(R.graph())}&retraction=${encodeURIComponent(r.id)}&format=html">Incident report</a>
          <a class="btn" href="/api/report?graph=${encodeURIComponent(R.graph())}&retraction=${encodeURIComponent(r.id)}&format=md" download="incident-${esc(r.id)}.md">Markdown</a></div></li>`).join("")}</ul>`;
  }

  // ---- boot -----------------------------------------------------------------------------------
  window.RETCON.on("ready", async (retcon) => {
    R = retcon;
    try { token = (await get("/api/ops/session")).token; } catch (e) { return; }
    const bar = document.querySelector(".bar .spacer");
    if (bar) { const b = document.createElement("span"); b.id = "ops-badge"; b.className = "chip"; b.textContent = "cascade: n/a"; bar.before(b); }
    const host = $("panels"), side = $("side");
    if (host && side) side.prepend(host);          // operator controls first, ahead of legend and filters
    R.panels.add({ id: "ops", title: "Operator: distrust a source", mount: mountDistrust });
    R.panels.add({ id: "recall", title: "Recall list and compensations", mount: mountRecall });
    R.panels.add({ id: "history", title: "Retractions", mount: mountHistory });
    R.on("delta", () => { /* keep recall fresh when the graph changes under us */ });
    setInterval(() => { refreshRecall(); refreshHistory(); }, 5000);
    R.on && R.on("graph", () => { loadSources(); });
  });
  document.addEventListener("change", (ev) => { if (ev.target && ev.target.id === "graph-select") setTimeout(() => R && loadSources(), 300); });
})();
