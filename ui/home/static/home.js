/* RETCON front door. Everything numeric is read from /api/home/*; nothing is typed in here. */
(function () {
  "use strict";
  window.__retconReady = true;
  const $ = (id) => document.getElementById(id);
  const fmt = (n) => (n == null ? "" : Number(n).toLocaleString("en-US"));
  const el = (tag, attrs, text) => {
    const e = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) e.setAttribute(k, v);
    if (text != null) e.textContent = text;
    return e;
  };
  const NS = "http://www.w3.org/2000/svg";
  const sv = (tag, attrs, text) => {
    const e = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs || {})) e.setAttribute(k, v);
    if (text != null) e.textContent = text;
    return e;
  };

  // ---- entrances (once). Content is visible if this script never runs. -----------------------------
  const reveal = document.querySelectorAll("[data-reveal]");
  if ("IntersectionObserver" in window) {
    const io = new IntersectionObserver((entries) => entries.forEach((e) => {
      if (e.isIntersecting) { e.target.classList.add("is-in"); io.unobserve(e.target); }
    }), { threshold: 0.12 });
    reveal.forEach((n) => io.observe(n));
  } else reveal.forEach((n) => n.classList.add("is-in"));

  async function getJson(url) {
    const r = await fetch(url, { cache: "no-store" });
    const j = await r.json();
    if (j && j.error) throw new Error(j.error.message);
    return j;
  }

  // ---- the five rules, run live on one real graph -------------------------------------------------------
  const RULES = {
    delete_source: ["Delete the source", "Remove only what the bad source said directly, and nothing that was built on it."],
    vector_only: ["Delete lookalikes", "Also remove anything that reads like it, by similarity search. No graph."],
    edge_invalidation: ["Invalidate one hop", "Remove what was extracted straight from it. Anything repeated further on stays."],
    coarse_taint: ["Taint everything downstream", "Remove everything that could have come from it, even when another source agrees."],
    retcon: ["RETCON", "Retract, then bring back whatever an independent source still supports."],
  };
  const COLS = [["source", "Sources", 150], ["observation", "Said", 330], ["belief", "Believed", 520], ["plan", "Planned", 690], ["action", "Paid", 780]];

  function layout(nodes, edges) {
    const col = Object.fromEntries(COLS.map(([k], i) => [k, i]));
    const cols = COLS.map(() => []);
    nodes.forEach((n) => cols[col[n.kind]].push(n));
    cols.forEach((c) => c.sort((a, b) => (a.id < b.id ? -1 : 1)));
    const nb = new Map(nodes.map((n) => [n.id, []]));
    edges.forEach((e) => { if (nb.has(e.s) && nb.has(e.t)) { nb.get(e.s).push(e.t); nb.get(e.t).push(e.s); } });
    const y = new Map();
    const place = () => cols.forEach((c) => c.forEach((n, i) => y.set(n.id, i)));
    place();
    for (let sweep = 0; sweep < 4; sweep++) {                    // barycentre sweeps to untangle the crossings
      const order = sweep % 2 ? [...cols.keys()].reverse() : [...cols.keys()];
      for (const ci of order) {
        const mean = (n) => { const ys = nb.get(n.id).filter((m) => col[nodes.find((x) => x.id === m).kind] !== ci).map((m) => y.get(m)); return ys.length ? ys.reduce((a, b) => a + b, 0) / ys.length : y.get(n.id); };
        cols[ci].sort((a, b) => mean(a) - mean(b) || (a.id < b.id ? -1 : 1));
        cols[ci].forEach((n, i) => y.set(n.id, i));
      }
    }
    const gap = 30, top = 52, tallest = Math.max(...cols.map((c) => c.length));
    const pos = {};
    cols.forEach((c, ci) => c.forEach((n, i) => { pos[n.id] = { x: COLS[ci][2], y: top + (tallest - c.length) * gap / 2 + i * gap }; }));
    return { pos, height: top + tallest * gap + 24 };
  }

  function shape(n, p, cls) {
    if (n.kind === "source") return sv("rect", { x: p.x - 8, y: p.y - 8, width: 16, height: 16, rx: 2, class: "n src " + cls });
    if (n.kind === "plan") {
      const pts = [0, 1, 2, 3, 4, 5].map((i) => { const a = Math.PI / 3 * i + Math.PI / 6; return `${(p.x + 8.5 * Math.cos(a)).toFixed(1)},${(p.y + 8.5 * Math.sin(a)).toFixed(1)}`; });
      return sv("polygon", { points: pts.join(" "), class: "n " + cls });
    }
    if (n.kind === "action") return sv("polygon", { points: `${p.x},${p.y - 9} ${p.x + 9},${p.y + 7} ${p.x - 9},${p.y + 7}`, class: "n " + cls });
    return sv("circle", { cx: p.x, cy: p.y, r: n.kind === "belief" ? 7 : 5.5, class: "n " + cls });
  }

  async function mountCompare() {
    let data;
    try { data = await getJson("/api/home/compare"); }
    catch (e) { $("compare-fallback").hidden = false; $("compare-fallback").insertAdjacentText("beforeend", " (" + e.message + ")"); return; }
    const names = ["none", ...Object.keys(RULES).filter((k) => data.strategies[k])];
    const svg = $("graph"), rules = $("rules");
    const { pos, height } = layout(data.nodes, data.edges);
    svg.setAttribute("viewBox", `0 0 1000 ${height}`);
    svg.setAttribute("height", height);
    const byId = new Map(data.nodes.map((n) => [n.id, n]));
    const group = (name) => { const g = sv("g"); svg.appendChild(g); return g; };
    COLS.forEach(([, label, x]) => svg.appendChild(sv("text", { x: x - 6, y: 24, class: "col" }, label)));
    const gEdges = group(), gNodes = group();
    const edgeEls = data.edges.filter((e) => pos[e.s] && pos[e.t]).map((e) => {
      const a = pos[e.s], b = pos[e.t], mx = (a.x + b.x) / 2;
      const p = sv("path", { d: `M${a.x},${a.y} C${mx},${a.y} ${mx},${b.y} ${b.x},${b.y}`, class: "e" });
      gEdges.appendChild(p);
      return { e, p };
    });
    const nodeEls = data.nodes.map((n) => {
      const g = sv("g", { tabindex: "0", role: "img", "aria-label": `${n.kind}: ${n.label}` });
      const holder = { n, g, shape: null, x: null };
      g.addEventListener("mouseenter", () => show(n)); g.addEventListener("focus", () => show(n));
      gNodes.appendChild(g);
      if (n.kind === "source") g.appendChild(sv("text", { x: pos[n.id].x - 14, y: pos[n.id].y + 4, class: "lab", "text-anchor": "end" }, n.label));
      if (n.kind === "action") g.appendChild(sv("text", { x: pos[n.id].x + 16, y: pos[n.id].y + 4, class: "lab" }, n.label));
      return holder;
    });
    let current = "none";

    function show(n) {
      const out = current !== "none" && new Set(data.strategies[current].out).has(n.id);
      const state = n.kind === "source" ? "A source."
        : out ? (n.bad ? "Retracted, correctly." : "Retracted, and it should have stayed.")
        : (n.bad ? (current === "none" ? "Should be retracted." : "Still believed, and it should not be.") : "Kept.");
      const box = $("inspect"); box.textContent = "";
      box.appendChild(el("strong", {}, n.kind[0].toUpperCase() + n.kind.slice(1)));
      box.appendChild(el("p", {}, n.label));
      box.appendChild(el("p", { class: "muted" }, state + (n.ways > 1 ? ` Supported ${n.ways} independent ways.` : "")));
    }

    function paint(name) {
      current = name;
      const r = data.strategies[name], out = new Set(name === "none" ? [] : r.out);
      nodeEls.forEach(({ n, g }) => {
        g.querySelectorAll(".n, .x").forEach((x) => x.remove());
        let cls = n.kind === "source" ? "" : out.has(n.id) ? (n.bad ? "out" : "lost") : (n.bad ? "ring" + (name === "none" ? "" : " still") : "kept");
        const s = shape(n, pos[n.id], cls); g.insertBefore(s, g.firstChild);
        if (cls === "out" || cls === "lost") {
          const p = pos[n.id];
          g.appendChild(sv("path", { d: `M${p.x - 3.5},${p.y - 3.5} L${p.x + 3.5},${p.y + 3.5} M${p.x + 3.5},${p.y - 3.5} L${p.x - 3.5},${p.y + 3.5}`, class: "x" }));
        }
      });
      edgeEls.forEach(({ e, p }) => p.setAttribute("class", "e" + (out.has(e.t) ? " dead" : "")));
      const sayEl = $("rule-says"), v = $("verdict");
      if (name === "none") {
        sayEl.textContent = "Nothing retracted yet. The source coastal-portal was compromised between 2 and 9 October. The red rings mark what should go.";
        v.textContent = `${data.total_bad} memories should be retracted, including both payments. ${data.total_good} should stay.`;
        return;
      }
      sayEl.textContent = RULES[name][1] + ` Took ${r.ms} ms.`;
      const stillBad = Math.round(r.residual * data.total_bad), lost = Math.round(r.collateral * data.total_good);
      const gone = data.total_bad - stillBad;
      v.textContent = "";
      const parts = [];
      parts.push(el("strong", {}, `${gone} of ${data.total_bad}`)); parts.push(document.createTextNode(" bad memories retracted"));
      if (stillBad) { parts.push(document.createTextNode(", ")); parts.push(el("strong", {}, `${stillBad} still believed`)); }
      parts.push(document.createTextNode(". "));
      parts.push(el("strong", {}, lost ? `${lost} correct ${lost === 1 ? "memory" : "memories"} lost` : "No correct memory lost"));
      if (r.wrong_actions) parts.push(document.createTextNode(`, including ${r.wrong_actions} correct payment${r.wrong_actions > 1 ? "s" : ""}`));
      parts.push(document.createTextNode(stillBad === 0 && lost === 0 ? ": exactly what should go." : "."));
      parts.forEach((p) => v.appendChild(p));
    }

    names.forEach((name, i) => {
      const lab = el("label", { class: "rule" });
      const inp = el("input", { type: "radio", name: "rule", value: name });
      if (i === 0) inp.checked = true;
      inp.addEventListener("change", () => paint(name));
      lab.appendChild(inp); lab.appendChild(el("span", {}, name === "none" ? "Before" : RULES[name][0]));
      rules.appendChild(lab);
    });
    data.strategies.none = { out: [], ms: 0, residual: 1, collateral: 0, wrong_actions: 0 };
    paint("none");
    $("compare").classList.add("ready");
  }

  // ---- the receipt: the itemised list adds up to the total --------------------------------------------
  function slip(r) {
    const box = $("slip"); box.textContent = "";
    r.groups.forEach((g) => {
      box.appendChild(el("h3", {}, `${g.name}: ${g.count} correct payments flagged`));
      g.rows.forEach((row) => {
        const d = el("div", { class: "row" });
        d.appendChild(el("span", { class: "d" }, row.label)); d.appendChild(el("span", { class: "lead", "aria-hidden": "true" }));
        d.appendChild(el("span", { class: "v" }, fmt(row.amount)));
        box.appendChild(d);
      });
    });
    const sum = el("div", { class: "sum" }); sum.appendChild(el("span", {}, "Total flagged, USD")); sum.appendChild(el("span", {}, fmt(r.total)));
    box.appendChild(sum);
    // torn-paper bottom edge
    const w = box.clientWidth || 400, n = Math.max(8, Math.round(w / 22)), pts = ["0 0", "100% 0", "100% calc(100% - 14px)"];
    for (let i = n; i >= 0; i--) pts.push(`${(i / n * 100).toFixed(2)}% ${i % 2 ? "100%" : "calc(100% - 14px)"}`);
    box.style.clipPath = `polygon(${pts.join(",")})`;
  }

  function numbers(num) {
    const r = num.receipt;
    if (r) {
      $("total-fig").textContent = "$" + (r.total / 1e6).toFixed(2) + "M";
      $("total-cap").textContent = `in ${r.count} correct payments that "taint everything" flags (${r.executed} already paid). RETCON flags ${r.retcon.count}.`;
      const share = r.profile && r.profile.corroborated_share != null ? Math.round(r.profile.corroborated_share * 100) : null;
      $("receipt-note").textContent = `A rule that taints everything downstream of a bad source also flags payments that are still correct. Measured on ${r.poisoned_vendors} compromised vendors, each with its own window` +
        (share != null ? `; about ${share}% of what they touched is also confirmed by a second source.` : ".");
      slip(r);
    } else {
      $("total-fig").textContent = "";
    }
    const line = (cls, text, note) => { const li = document.querySelector("." + cls); if (!li) return; li.querySelector(".fact-line").textContent = text; if (note) li.querySelector(".fact-note").textContent = note; };
    const sp = num.speed || [];
    if (sp.length) {
      const first = sp[0], last = sp[sp.length - 1];
      line("fact-a", `${Math.round(last.p50_ms)} ms to retract among ${fmt(last.nodes)} memories.`,
        `Median time for one retraction, measured from ${fmt(first.nodes)} memories (${Math.round(first.p50_ms)} ms) up to ${fmt(last.nodes)}.`);
    }
    if (num.science) {
      const s = num.science, left = s.residual === 0 ? "none left" : `${(s.residual * 100).toFixed(1)}% left`;
      line("fact-b", `${s.windows} real retractions, ${fmt(s.contaminated)} bad memories, ${left}.`,
        `Retracted papers from the Retraction Watch database, replayed on their real dates; ${s.collateral === 0 ? "no correct memory lost" : (s.collateral * 100).toFixed(1) + "% of correct memories lost"}.`);
    }
    if (num.concurrency) {
      const c = num.concurrency;
      line("fact-c", `${c.max_writers} writers at once, ${c.stale} stale answers.`,
        `Agents writing while a retraction runs; afterwards every status is checked against an independent recomputation (${fmt(c.ops)} operations, ${(c.error_rate * 100).toFixed(1)}% errors).`);
    }
    if (num.ablation) {
      const off = num.ablation.graph_off, on = num.ablation.graph_on;
      line("fact-d", off.paid_attacker_after > 0 ? "Take the graph away and it pays the attacker." : "Take the graph away and it still loses good memories.",
        `Same agents, same attack, similarity search instead of justifications: it retracted ${off.retracted} of ${off.of} bad memories and lost ${off.clean_lost} good ones; with the graph, ${on.retracted} of ${on.of} and ${on.clean_lost}.`);
    }
    if (num.embedder) $("embedder-note").textContent = `Similarity uses the ${num.embedder} embedder.`;
  }

  getJson("/api/home/numbers").then(numbers).catch(() => {});
  mountCompare();
})();
