/* Guided demo: five steps that drive the real operator console and the real agents, so a visitor sees
   the whole story with no terminal. Opens on /graph?guide=1 (the front page's "Run the demo"). Nothing here
   is simulated: each step calls the same endpoints the console uses. */
(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const GRAPH = "demo_live";
  let R = null, token = null, step = 0, busy = false, win = null, retractionId = null, card, reopen;

  async function get(path) {
    const r = await fetch(path, { cache: "no-store" });
    const j = await r.json();
    if (j && j.error) throw new Error(j.error.message);
    return j;
  }
  async function post(path, body) {
    const r = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(Object.assign({ token }, body)) });
    const j = await r.json();
    if (j && j.error) throw new Error(j.error.message);
    return j;
  }

  async function showGraph() {
    const sel = $("graph-select");
    if (![...sel.options].some((o) => o.value === GRAPH)) {
      const o = document.createElement("option"); o.value = o.textContent = GRAPH; sel.appendChild(o);
    }
    sel.value = GRAPH;
    sel.dispatchEvent(new Event("change"));
    for (let i = 0; i < 40 && R.graph() !== GRAPH; i++) await sleep(100);
    await sleep(500);
  }

  async function until(fn, ms, every) {
    const end = Date.now() + ms;
    while (Date.now() < end) { const v = await fn(); if (v) return v; await sleep(every || 400); }
    throw new Error("This is taking longer than expected. Is the database running?");
  }

  const STEPS = [
    {
      eyebrow: "1 of 5", title: "An agent day, running for real",
      text: "Four agents read invoices, purchase orders and a vendor portal, then plan payments; the Payments agent picks its own tools. Every fact they store keeps a record of which sources it rests on.",
      button: "Start the agents",
      async run(say) {
        await post("/api/demo/start", {});
        say("Agents working…");
        await until(async () => (await get("/api/graphs")).some((g) => g.name === GRAPH), 60000, 500);
        await showGraph();
        const st = await until(async () => { const s = await get("/api/demo/status"); if (s.phase === "error") throw new Error(s.error); say(`Agents working: ${s.tasks || 0} tasks done`); return s.phase === "ready" && s; }, 120000, 700);
        win = st.window;
        return `${st.tasks} tasks done. Payments agent: ${st.brain || "rule-based"}. The graph on the left is what the agents now believe.`;
      },
    },
    {
      eyebrow: "2 of 5", title: "One source turns out to be compromised",
      text: "The vendor portal was hacked for a week. Preview first: this runs on a copy of the graph, so nothing real changes yet.",
      button: "Preview the retraction",
      async run(say) {
        if (!win) win = (await get("/api/demo/status")).window;
        if (!win) throw new Error("Run step 1 first.");
        const L = window.OpsLogic;
        await until(() => [...$("ops-source").options].some((o) => o.value === win.source), 15000, 300);
        $("ops-source").value = win.source;
        $("ops-from").value = L.epochToLocal(Date.parse(win.from) / 1000);
        $("ops-to").value = L.epochToLocal(Date.parse(win.to) / 1000);
        say("Forking the graph…");
        $("ops-preview").click();
        const line = await until(() => { const el = $("ops-line"); return el && el.textContent.trim() && el.textContent; }, 20000, 300);
        document.getElementById("panel-ops").scrollIntoView({ block: "start" });
        return line;
      },
    },
    {
      eyebrow: "3 of 5", title: "Commit it, and keep what still stands",
      text: "Memories resting only on that source become tentative. Anything a second, independent source also supports stays. Nothing is deleted.",
      button: "Retract it",
      async run(say) {
        const btn = $("ops-commit-prev");
        if (!btn) throw new Error("Preview first.");
        const realConfirm = window.confirm;
        window.confirm = () => true;                 // this click is the confirmation
        try { btn.click(); } finally { setTimeout(() => { window.confirm = realConfirm; }, 0); }
        say("Retracting…");
        const line = await until(() => { const h = document.querySelector("#ops-result h3 .pill"); return h && /COMMITTED/.test(h.textContent) && $("ops-line").textContent; }, 30000, 300);
        const st = await get("/api/ops/recall?graph=" + GRAPH);
        const mine = (st.retractions || []).find((r) => !r.reinstated);
        retractionId = mine && mine.id;
        const sub = document.querySelector("#ops-result .ops-sub");
        return line + (sub ? ". " + sub.textContent.trim() : "");
      },
    },
    {
      eyebrow: "4 of 5", title: "What it could not take back",
      text: "Some payments had already gone out. They are listed for recall, each with a drafted correction, and the whole thing is written up as an incident report.",
      button: "Open the incident report",
      async run() {
        if (!retractionId) {                         // e.g. the page was reloaded after step 3
          const cur = await get("/api/ops/recall?graph=" + GRAPH);
          const mine = (cur.retractions || []).find((r) => !r.reinstated);
          retractionId = mine && mine.id;
        }
        if (!retractionId) throw new Error("Commit the retraction first.");
        window.open(`/api/report?graph=${GRAPH}&retraction=${encodeURIComponent(retractionId)}&format=html`, "_blank", "noopener");
        document.getElementById("panel-recall").scrollIntoView({ block: "start" });
        const st = await get("/api/ops/recall?graph=" + GRAPH);
        const sent = (st.recall || []).filter((a) => a.retraction_id === retractionId);
        const paid = sent.filter((a) => a.tool === "pay");
        const total = paid.reduce((n, a) => n + (a.amount || 0), 0);
        const drafts = (st.remediations || []).length;
        return `${paid.length} payment(s) totalling ${total.toLocaleString()} USD and ${sent.length - paid.length} other action(s) had already gone out. ${drafts} correction(s) drafted for approval. The report opened in a new tab.`;
      },
    },
    {
      eyebrow: "5 of 5", title: "Now take the graph away",
      text: "Same agents, same attack, but with plain similarity search instead of justifications. This runs both, which takes about a minute.",
      button: "Compare",
      async run(say) {
        await post("/api/demo/ablation", {});
        say("Running the attack twice…");
        const a = await until(async () => { const s = await get("/api/demo/ablation"); if (s.phase === "error") throw new Error(s.error); return s.phase === "ready" && s.result; }, 240000, 1500);
        const on = a.graph_on, off = a.graph_off;
        const fmt = (x) => x.paid_attacker_after_retraction ? `paid the attacker ${x.paid_attacker_after_retraction} more time(s), ${Number(x.amount_to_attacker_after).toLocaleString()} USD` : "paid the attacker nothing after the retraction";
        return { bad: true, html: `With the graph, the agents ${esc(fmt(on))}. Without it, they ${esc(fmt(off))}.` };
      },
    },
  ];

  function render(result, err) {
    const s = STEPS[Math.min(step, STEPS.length - 1)];
    const done = step >= STEPS.length;
    const dots = STEPS.map((_, i) => `<i class="${i < step ? "done" : ""}"></i>`).join("");
    card.innerHTML = `
      <div class="guide-dots" aria-hidden="true">${dots}</div>
      <p class="guide-eyebrow">${done ? "Done" : esc(s.eyebrow)}</p>
      <h2>${done ? "That is the whole loop" : esc(s.title)}</h2>
      <p>${done ? "Remember, retract, keep what stands, recall what escaped, and prove it against a baseline. The measured results are on the front page." : esc(s.text)}</p>
      ${result ? `<div class="guide-result ${err ? "bad" : "good"}" role="status">${result.html || esc(result)}</div>` : ""}
      <div class="guide-actions">
        ${done ? `<a class="btn primary" href="/#measured">See the measurements</a><a class="btn" href="/docs/MCP_CLIENT.md">Use it from Claude Code</a>`
               : `<button class="btn primary" id="guide-go"${busy ? " disabled" : ""}>${esc(s.button)}</button>`}
        <button class="guide-x" id="guide-close" aria-label="Close the guide">Close</button>
      </div>`;
    $("guide-close").onclick = () => { card.hidden = true; reopen.hidden = false; };
    const go = $("guide-go");
    if (go) go.onclick = advance;
  }

  async function advance() {
    if (busy) return;
    busy = true;
    const say = (t) => { const r = card.querySelector(".guide-result"); if (r) r.textContent = t; else { const p = document.createElement("div"); p.className = "guide-result"; p.textContent = t; card.querySelector(".guide-actions").before(p); } };
    render("Working…");
    try {
      const out = await STEPS[step].run((t) => { const r = card.querySelector(".guide-result"); if (r) r.textContent = t; });
      step++; busy = false; render(out);
    } catch (e) {
      busy = false; render(e.message, true);
    }
  }

  function boot() {
    card = document.createElement("aside");
    card.className = "guide"; card.setAttribute("aria-label", "Guided demo"); card.hidden = true;
    reopen = document.createElement("button");
    reopen.className = "btn guide-reopen"; reopen.textContent = "Guided demo"; reopen.hidden = false;
    reopen.onclick = () => { reopen.hidden = true; card.hidden = false; };
    document.body.append(card, reopen);
    render();
    if (/[?&]guide=1/.test(location.search)) { card.hidden = false; reopen.hidden = true; }
    window.RETCON_GUIDE = { open() { reopen.onclick(); }, goto(n) { step = n; render(); } };
  }

  async function ready(retcon) {
    R = retcon;
    try { token = (await get("/api/ops/session")).token; } catch (e) { /* console panels absent: guide stays inert */ }
  }

  boot();
  const wait = setInterval(() => { if (window.RETCON) { clearInterval(wait); window.RETCON.on("ready", ready); if (window.RETCON.graph && window.RETCON.graph()) ready(window.RETCON); } }, 100);
})();
