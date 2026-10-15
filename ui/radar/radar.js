/* Fragility radar (B6b): how many independent sources must fail before each decision falls.
   One spoke per live plan/action; distance from the centre = poisoning cost (Q7). Anything inside the
   dashed policy ring is below the gate's minimum and is the part worth looking at.
   Plugs into the shell through window.RETCON (see ui/shell/README.md). Served at /static/radar.js. */
(function () {
  "use strict";
  const MAX_COST = 4, SIZE = 300, CX = SIZE / 2, CY = SIZE / 2, R = 104;
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const NS = "http://www.w3.org/2000/svg";

  function polar(i, n, r) {
    const a = -Math.PI / 2 + (2 * Math.PI * i) / Math.max(n, 1);
    return [CX + r * Math.cos(a), CY + r * Math.sin(a)];
  }

  /** Pure: items -> {points, below, summary}. Exported for tests. */
  function layout(items, policyMin) {
    const n = items.length;
    const pts = items.map((it, i) => {
      const cost = Math.min(it.independent_sources, MAX_COST);
      const [x, y] = polar(i, n, (cost / MAX_COST) * R);
      const [lx, ly] = polar(i, n, R + 14);
      return { id: it.id, x, y, lx, ly, cost: it.independent_sources, below: it.independent_sources < policyMin };
    });
    const below = pts.filter((p) => p.below).length;
    return { points: pts, below, n };
  }

  function mount(el, RETCON) {
    el.innerHTML = `
      <div class="row">
        <select id="radar-kinds" aria-label="What to score">
          <option value="plan,action">Decisions (plans, actions)</option>
          <option value="belief">Claims (beliefs)</option>
        </select>
      </div>
      <p id="radar-summary" class="muted" aria-live="polite">Loading…</p>
      <svg id="radar-svg" viewBox="-70 -6 ${SIZE + 140} ${SIZE + 14}" width="100%" role="img" aria-label="Fragility radar"></svg>
      <ul id="radar-list" class="tree" style="border:0;padding:0"></ul>`;
    const svg = el.querySelector("#radar-svg"), list = el.querySelector("#radar-list"),
          sum = el.querySelector("#radar-summary"), sel = el.querySelector("#radar-kinds");
    let timer = null, seq = 0, last = null;

    function cssVar(n) { return getComputedStyle(document.documentElement).getPropertyValue(n).trim(); }
    function node(tag, attrs, text) {
      const e = document.createElementNS(NS, tag);
      for (const [k, v] of Object.entries(attrs || {})) e.setAttribute(k, v);
      if (text != null) e.textContent = text;
      return e;
    }

    function render(data) {
      last = data;
      const min = (data.policy && data.policy.min) || 2;
      const items = data.items;
      const L = layout(items, min);
      svg.innerHTML = "";
      const muted = cssVar("--muted"), line = cssVar("--line"), bad = cssVar("--out"), good = cssVar("--in"), ink = cssVar("--ink");
      for (let c = 1; c <= MAX_COST; c++) {                       // cost rings
        svg.appendChild(node("circle", { cx: CX, cy: CY, r: (c / MAX_COST) * R, fill: "none", stroke: line, "stroke-width": 1 }));
        svg.appendChild(node("text", { x: CX + 3, y: CY - (c / MAX_COST) * R - 2, fill: muted, "font-size": 9 }, c === MAX_COST ? c + "+" : c));
      }
      svg.appendChild(node("circle", { cx: CX, cy: CY, r: (min / MAX_COST) * R, fill: "none", stroke: bad,
                                       "stroke-width": 1.4, "stroke-dasharray": "5 4" }));
      svg.appendChild(node("text", { x: CX, y: CY + R + 30, fill: bad, "font-size": 10, "text-anchor": "middle" }, `dashed ring = policy minimum (${min} sources)`));
      if (!L.n) { svg.appendChild(node("text", { x: CX, y: CY, fill: muted, "text-anchor": "middle", "font-size": 12 }, "nothing live to score")); return; }
      L.points.forEach((p, i) => svg.appendChild(node("line", { x1: CX, y1: CY, x2: polar(i, L.n, R)[0], y2: polar(i, L.n, R)[1], stroke: line })));
      if (L.n > 2) svg.appendChild(node("polygon", {
        points: L.points.map((p) => p.x.toFixed(1) + "," + p.y.toFixed(1)).join(" "),
        fill: L.below ? bad : good, "fill-opacity": 0.14, stroke: L.below ? bad : good, "stroke-width": 1.5 }));
      L.points.forEach((p, i) => {
        const dot = node("circle", { cx: p.x, cy: p.y, r: 5, fill: p.below ? bad : good, stroke: ink, "stroke-width": 0.6,
                                     tabindex: 0, role: "button", "aria-label": `${items[i].label}: ${p.cost} source(s)`,
                                     style: "cursor:pointer" });
        dot.addEventListener("click", () => { RETCON.select(p.id); RETCON.centerOn(p.id); });
        dot.addEventListener("keydown", (e) => { if (e.key === "Enter") { RETCON.select(p.id); RETCON.centerOn(p.id); } });
        dot.addEventListener("mouseenter", () => RETCON.highlight([p.id], "--accent"));
        dot.addEventListener("mouseleave", () => RETCON.highlight([p.id], null));
        svg.appendChild(dot);
        if (L.n <= 10) {
          const right = p.lx >= CX;
          svg.appendChild(node("text", { x: p.lx, y: p.ly + 3, fill: ink, "font-size": 9, "text-anchor": right ? "start" : "end" },
            items[i].label.length > 16 ? items[i].label.slice(0, 15) + "…" : items[i].label));
        }
      });
    }

    function renderList(data) {
      const min = (data.policy && data.policy.min) || 2;
      const below = data.items.filter((i) => i.independent_sources < min).length;
      sum.textContent = data.items.length
        ? `${below} of ${data.items.length} below the policy minimum of ${min} independent sources.`
        : "Nothing live of this kind yet.";
      list.innerHTML = data.items.slice(0, 12).map((i) =>
        `<li><button data-id="${esc(i.id)}"><strong>${i.independent_sources}</strong> ${esc(i.label)}</button>`
        + `<div class="muted">${i.independent_sources < min ? "weakest cut: " + esc(i.cut_set.join(", ")) : "needs " + i.independent_sources + " sources to fail"}`
        + `${i.bound === "upper" ? " (upper bound)" : ""}</div></li>`).join("");
    }
    list.addEventListener("click", (ev) => {
      const b = ev.target.closest("button[data-id]");
      if (b) { RETCON.select(b.dataset.id); RETCON.centerOn(b.dataset.id); }
    });

    async function refresh() {
      const mine = ++seq;
      try {
        const g = RETCON.graph();
        if (!g) return;
        const data = await RETCON.api(`/api/fragility?graph=${encodeURIComponent(g)}&kinds=${sel.value}&limit=40`);
        if (mine !== seq) return;
        render(data); renderList(data);
      } catch (e) {
        sum.textContent = "Can't score fragility: " + e.message;
      }
    }
    const later = () => { clearTimeout(timer); timer = setTimeout(refresh, 400); };
    RETCON.on("snapshot", later);
    RETCON.on("delta", later);
    sel.addEventListener("change", refresh);
    window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => last && render(last));
    refresh();
  }

  if (typeof module === "object" && module.exports) module.exports = { layout, polar, MAX_COST };
  if (typeof window !== "undefined" && window.RETCON) {
    window.RETCON.panels.add({ id: "radar", title: "Fragility radar", mount });
  }
})();
