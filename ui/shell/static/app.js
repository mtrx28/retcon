/* RETCON graph shell (B6a): canvas over the live FalkorDB graph.
   Extension points for the other panels (A6 cascade/preview/recall, B6b radar): window.RETCON, see ui/shell/README.md */
(function () {
  "use strict";
  const { GraphStore } = window.RetconStore;
  const Layout = window.RetconLayout;
  const $ = (id) => document.getElementById(id);

  const store = new GraphStore();
  const pos = new Map();                       // id -> layout node {id, kind, x, y, vx, vy, fixed, born}
  const flashes = new Map();                   // id -> {t, kind}
  const handlers = {};
  const S = {
    graph: null, live: true, columns: true, selected: null, hover: null, lineage: null,
    view: { x: 0, y: 0, k: 1 }, alpha: 0, userMoved: false, visible: new Set(), polling: false,
    filter: { kinds: null, states: null, mtypes: null, agent: null, query: "" },
    extraHighlight: new Map(),               // id -> css-var colour, set by other panels
  };

  // ---- tiny event bus -------------------------------------------------------------------
  function on(evt, fn) { (handlers[evt] = handlers[evt] || []).push(fn); }
  function emit(evt, arg) { (handlers[evt] || []).forEach((fn) => { try { fn(arg); } catch (e) { console.error(e); } }); }

  // ---- data -----------------------------------------------------------------------------
  async function api(path) {
    const r = await fetch(path, { cache: "no-store" });
    const body = await r.json();
    if (body && body.error) throw Object.assign(new Error(body.error.message), { code: body.error.code, body });
    return body;
  }
  const q = (o) => Object.entries(o).filter(([, v]) => v != null).map(([k, v]) => k + "=" + encodeURIComponent(v)).join("&");

  async function loadGraphs() {
    const list = await api("/api/graphs");
    const sel = $("graph-select");
    sel.innerHTML = "";
    for (const g of list) {
      const o = document.createElement("option");
      o.value = o.textContent = g.name;
      sel.appendChild(o);
    }
    const want = new URLSearchParams(location.hash.slice(1)).get("graph");
    const pick = (want && list.some((g) => g.name === want)) ? want
      : (list.find((g) => g.name === "tenant_northwind") || list[0] || {}).name;
    sel.value = pick || "";
    return pick;
  }

  async function loadSnapshot() {
    if (!S.graph) { showEmpty(true); return; }
    const snap = await api("/api/graph?" + q({ graph: S.graph }));
    store.load(snap);
    pos.clear();
    flashes.clear();
    seedAll();
    S.selected = null; S.lineage = null;
    S.alpha = 1; S.userMoved = false;
    refreshVisible(); renderSummary(); renderInspector(); showEmpty(store.nodes.size === 0);
    simulate(500, 400);                 // pre-settle: the first paint is already laid out
    banner(snap.truncated ? `Showing ${snap.counts.shown} of ${snap.counts.mem} memories (retracted and newest first).` : "");
    emit("snapshot", { graph: S.graph, store });
    fit();
  }

  async function poll() {
    if (!S.live || S.polling || !S.graph) return;
    S.polling = true;
    try {
      const d = await api("/api/delta?" + q({ graph: S.graph, since: store.version }));
      setLive(true);
      if (d.reset) { await loadSnapshot(); return; }
      const res = store.applyDelta(d);
      if (res.added.length || res.changed.length || res.edges) {
        seedNew(res.added);
        const now = performance.now();
        for (const c of res.changed) flashes.set(c.id, { t: now, kind: c.to === "OUT" ? "out" : c.to === "IN" ? "in" : "tent" });
        for (const id of res.added) flashes.set(id, { t: now, kind: "new" });
        S.alpha = Math.max(S.alpha, 0.6);
        refreshVisible(); renderSummary(); showEmpty(false);
        simulate(80, 40);               // new nodes glide to place even if frames are slow
        if (!S.userMoved && res.added.length) fit();
        if (S.selected && res.changed.some((c) => c.id === S.selected)) renderInspector();
        emit("delta", { result: res, delta: d });
      }
    } catch (e) {
      setLive(false, e.message);
    } finally { S.polling = false; }
  }

  // ---- layout ---------------------------------------------------------------------------
  function neighbours(id) {
    const ids = [];
    for (const e of store.out.get(id) || []) ids.push(e.t);
    for (const e of store.inc.get(id) || []) ids.push(e.s);
    return ids.map((i) => pos.get(i)).filter(Boolean);
  }
  function seedNew(ids) {
    for (const id of ids) {
      const n = store.nodes.get(id);
      if (!n || pos.has(id)) continue;
      const p = { id, kind: n.kind, x: 0, y: 0, vx: 0, vy: 0, fixed: false, born: performance.now() };
      Layout.seed(p, neighbours(id), { });
      pos.set(id, p);
    }
  }
  function seedAll() {
    // place column by column so every node has a placed neighbour when possible
    const order = ["source", "observation", "justification", "belief", "plan", "action", "mem"];
    const all = [...store.nodes.values()].sort((a, b) => order.indexOf(a.kind) - order.indexOf(b.kind) || (a.id < b.id ? -1 : 1));
    seedNew(all.map((n) => n.id));
    for (const p of pos.values()) p.born = 0;
  }
  // The layout must not depend on the frame rate (background tabs throttle requestAnimationFrame):
  // simulate in bursts bounded by a time budget, both before the first paint and on every frame.
  function simulate(budgetMs, maxSteps) {
    if (S.alpha < 0.02) return 0;
    const nodes = [...S.visible].map((id) => pos.get(id)).filter(Boolean);
    const edges = store.edges.filter((e) => S.visible.has(e.s) && S.visible.has(e.t));
    const t0 = performance.now();
    let n = 0;
    while (n < maxSteps && S.alpha >= 0.02 && (n === 0 || performance.now() - t0 < budgetMs)) {
      const energy = Layout.step(nodes, edges, S.alpha, { columns: S.columns });
      S.alpha *= energy < nodes.length * 0.02 ? 0.93 : 0.99;
      n++;
    }
    return n;
  }
  function simStep() { simulate(10, 3); }
  function fit(soft) {
    const nodes = [...S.visible].map((id) => pos.get(id)).filter(Boolean);
    const b = Layout.bounds(nodes);
    const c = $("canvas"), w = c.clientWidth, h = c.clientHeight, pad = 60;
    const k = Math.max(0.15, Math.min(2.2, Math.min((w - pad * 2) / Math.max(40, b.x1 - b.x0), (h - pad * 2) / Math.max(40, b.y1 - b.y0))));
    const target = { k, x: w / 2 - ((b.x0 + b.x1) / 2) * k, y: h / 2 - ((b.y0 + b.y1) / 2) * k };
    if (soft) {
      S.view.k += (target.k - S.view.k) * 0.15; S.view.x += (target.x - S.view.x) * 0.15; S.view.y += (target.y - S.view.y) * 0.15;
    } else { S.view = target; S.userMoved = false; }
  }

  // ---- filters --------------------------------------------------------------------------
  function refreshVisible() {
    S.visible = store.visible(S.filter);
    if (S.selected && !S.visible.has(S.selected)) { /* keep selection visible so the inspector stays valid */ S.visible.add(S.selected); }
  }

  // ---- drawing --------------------------------------------------------------------------
  let C = {};
  function readColors() {
    const cs = getComputedStyle(document.documentElement);
    const v = (n) => cs.getPropertyValue(n).trim();
    C = { in: v("--in"), out: v("--out"), tent: v("--tent"), accent: v("--accent"), ep: v("--ep"), se: v("--se"),
          pr: v("--pr"), src: v("--src"), just: v("--just"), ink: v("--ink"), muted: v("--muted"), canvas: v("--canvas"),
          grid: v("--grid") };
  }
  const R = { source: 9, observation: 5.5, belief: 7.5, plan: 8.5, action: 9, justification: 3.6, mem: 6 };
  const MT = () => ({ episodic: C.ep, semantic: C.se, procedural: C.pr });

  function fillFor(n) {
    const st = store.state(n);
    if (n.kind === "source") return st === "OUT" ? C.out : C.src;
    if (st === "IN") return C.in;
    if (st === "OUT") return C.out;
    if (st === "TENTATIVE") return C.tent;
    return C.muted;
  }

  function shape(ctx, kind, x, y, r) {
    ctx.beginPath();
    if (kind === "source") { const s = r * 0.9; ctx.roundRect(x - s, y - s, s * 2, s * 2, 3); }
    else if (kind === "plan") {
      for (let i = 0; i < 6; i++) { const a = Math.PI / 3 * i + Math.PI / 6; ctx[i ? "lineTo" : "moveTo"](x + r * Math.cos(a), y + r * Math.sin(a)); }
      ctx.closePath();
    } else if (kind === "action") { ctx.moveTo(x, y - r); ctx.lineTo(x + r, y + r * 0.8); ctx.lineTo(x - r, y + r * 0.8); ctx.closePath(); }
    else if (kind === "justification") { ctx.moveTo(x, y - r); ctx.lineTo(x + r, y); ctx.lineTo(x, y + r); ctx.lineTo(x - r, y); ctx.closePath(); }
    else ctx.arc(x, y, r, 0, Math.PI * 2);
  }

  function draw(now) {
    const canvas = $("canvas"), ctx = canvas.getContext("2d");
    const dpr = window.devicePixelRatio || 1;
    const w = canvas.clientWidth, h = canvas.clientHeight;
    if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(h * dpr)) {
      canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr);
    }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.fillStyle = C.canvas; ctx.fillRect(0, 0, w, h);
    const { x: vx, y: vy, k } = S.view;
    const sx = (x) => x * k + vx, sy = (y) => y * k + vy;

    // column guides
    if (S.columns) {
      ctx.font = "11px " + getComputedStyle(document.body).fontFamily;
      ctx.fillStyle = C.muted; ctx.strokeStyle = C.grid; ctx.lineWidth = 1;
      const cols = [["Sources", 0], ["Observations", 1], ["Beliefs", 2.4], ["Plans", 3.3], ["Actions", 4.2]];
      for (const [label, c] of cols) {
        const x = sx(c * Layout.DEFAULTS.columnWidth);
        ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, h); ctx.stroke();
        ctx.fillText(label, x + 6, 16);
      }
    }

    const dim = S.lineage ? 0.14 : 1;
    const inLine = (id) => !S.lineage || id === S.selected || S.lineage.up.has(id) || S.lineage.down.has(id);
    // edges
    ctx.lineWidth = 1;
    for (const e of store.edges) {
      if (!S.visible.has(e.s) || !S.visible.has(e.t)) continue;
      const a = pos.get(e.s), b = pos.get(e.t);
      if (!a || !b) continue;
      const tn = store.nodes.get(e.t), sn = store.nodes.get(e.s);
      const dead = (store.state(tn) === "OUT") || (store.state(sn) === "OUT");
      const lit = S.lineage && inLine(e.s) && inLine(e.t);
      ctx.globalAlpha = lit ? 0.95 : (S.lineage ? 0.06 : (dead ? 0.55 : 0.42));
      // upstream of the selection (what it rests on) = accent, downstream (what rests on it) = tentative amber
      const upstream = lit && (S.lineage.up.has(e.t) || e.t === S.selected);
      ctx.strokeStyle = lit ? (upstream ? C.accent : C.tent) : (dead ? C.out : C.just);
      ctx.lineWidth = lit ? 1.8 : 1;
      ctx.beginPath(); ctx.moveTo(sx(a.x), sy(a.y)); ctx.lineTo(sx(b.x), sy(b.y)); ctx.stroke();
      if (e.type !== "SUPPORTS" && k > 0.5) { // arrow head
        const ang = Math.atan2(sy(b.y) - sy(a.y), sx(b.x) - sx(a.x)), rr = (R[tn.kind] || 6) * k + 3;
        const ex = sx(b.x) - Math.cos(ang) * rr, ey = sy(b.y) - Math.sin(ang) * rr;
        ctx.beginPath(); ctx.moveTo(ex, ey);
        ctx.lineTo(ex - 6 * Math.cos(ang - 0.4), ey - 6 * Math.sin(ang - 0.4));
        ctx.lineTo(ex - 6 * Math.cos(ang + 0.4), ey - 6 * Math.sin(ang + 0.4));
        ctx.closePath(); ctx.fillStyle = ctx.strokeStyle; ctx.fill();
      }
    }
    ctx.lineWidth = 1;

    // nodes
    const ring = MT();
    for (const id of S.visible) {
      const n = store.nodes.get(id), p = pos.get(id);
      if (!n || !p) continue;
      const born = p.born ? Math.min(1, (now - p.born) / 420) : 1;
      const r = (R[n.kind] || 6) * k * (0.35 + 0.65 * born) * (id === S.selected ? 1.25 : 1);
      const x = sx(p.x), y = sy(p.y);
      if (x < -30 || y < -30 || x > w + 30 || y > h + 30) continue;
      const faded = S.lineage && !inLine(id);
      ctx.globalAlpha = faded ? dim : (store.state(n) === "OUT" && n.kind !== "source" ? 0.88 : 1);
      shape(ctx, n.kind, x, y, Math.max(2, r));
      ctx.fillStyle = fillFor(n); ctx.fill();
      const extra = S.extraHighlight.get(id);
      const mt = n.mtype && ring[n.mtype];
      ctx.lineWidth = mt || extra ? 2.6 : 1;
      ctx.strokeStyle = extra || mt || C.ink;
      if (!mt && !extra) ctx.globalAlpha *= 0.35;
      if (store.state(n) === "TENTATIVE") ctx.setLineDash([3, 2]);
      ctx.stroke(); ctx.setLineDash([]);
      ctx.globalAlpha = faded ? dim : 1;
      if (store.state(n) === "OUT" && n.kind !== "justification" && r > 4) {   // second cue besides colour
        ctx.strokeStyle = "#fff"; ctx.lineWidth = 1.6;
        const d = r * 0.42;
        ctx.beginPath(); ctx.moveTo(x - d, y - d); ctx.lineTo(x + d, y + d); ctx.moveTo(x + d, y - d); ctx.lineTo(x - d, y + d); ctx.stroke();
      }
      if (id === S.selected || id === S.hover) {
        ctx.globalAlpha = 1; ctx.strokeStyle = C.accent; ctx.lineWidth = 2;
        shape(ctx, n.kind, x, y, r + 5); ctx.stroke();
      }
      const always = n.kind === "source" || n.kind === "action";
      if ((k > 1.15 || id === S.selected || id === S.hover || (always && k > 0.45)) && n.kind !== "justification" && !faded) {
        ctx.globalAlpha = 0.9; ctx.fillStyle = C.ink; ctx.font = "11px " + getComputedStyle(document.body).fontFamily;
        const text = n.kind === "source" ? n.id : (n.kind === "action" ? `${n.tool || "act"} ${n.amount ?? ""}` : n.label);
        ctx.fillText(text.length > 34 ? text.slice(0, 33) + "…" : text, x + r + 5, y + 4);
      }
    }
    // flashes (a ring that expands and fades: shows what just changed)
    for (const [id, f] of flashes) {
      const t = (now - f.t) / 1100;
      const p = pos.get(id);
      if (t >= 1 || !p || !S.visible.has(id)) { if (t >= 1) flashes.delete(id); continue; }
      ctx.globalAlpha = (1 - t) * 0.9;
      ctx.strokeStyle = f.kind === "out" ? C.out : f.kind === "in" ? C.in : f.kind === "tent" ? C.tent : C.accent;
      ctx.lineWidth = 2.5;
      ctx.beginPath(); ctx.arc(sx(p.x), sy(p.y), (8 + t * 26) * Math.max(0.6, k), 0, Math.PI * 2); ctx.stroke();
    }
    ctx.globalAlpha = 1;
    emit("draw", { ctx, sx, sy, k, now });      // overlays from other panels (cascade hops, diff outlines)
  }

  function frame(now) {
    simStep();
    if (!S.userMoved && S.visible.size) fit(true);   // keep the whole graph in view until the user takes over
    draw(now);
    requestAnimationFrame(frame);
  }

  // ---- interaction ----------------------------------------------------------------------
  function toWorld(ev) {
    const r = $("canvas").getBoundingClientRect();
    return { x: (ev.clientX - r.left - S.view.x) / S.view.k, y: (ev.clientY - r.top - S.view.y) / S.view.k, px: ev.clientX - r.left, py: ev.clientY - r.top };
  }
  function hit(wx, wy) {
    let best = null, bd = Infinity;
    for (const id of S.visible) {
      const p = pos.get(id), n = store.nodes.get(id);
      if (!p || !n) continue;
      const d = Math.hypot(p.x - wx, p.y - wy), r = (R[n.kind] || 6) + 5 / S.view.k;
      if (d <= r && d < bd) { best = id; bd = d; }
    }
    return best;
  }
  function setupInteraction() {
    const c = $("canvas");
    let drag = null;
    c.addEventListener("mousedown", (ev) => {
      const w = toWorld(ev), id = hit(w.x, w.y);
      drag = { id, startX: ev.clientX, startY: ev.clientY, moved: false, vx: S.view.x, vy: S.view.y };
      c.classList.add("dragging");
    });
    window.addEventListener("mousemove", (ev) => {
      if (drag) {
        const dx = ev.clientX - drag.startX, dy = ev.clientY - drag.startY;
        if (Math.abs(dx) + Math.abs(dy) > 3) drag.moved = true;
        if (drag.moved) {
          if (drag.id) {
            const p = pos.get(drag.id), w = toWorld(ev);
            p.x = w.x; p.y = w.y; p.vx = p.vy = 0; p.fixed = true; S.alpha = Math.max(S.alpha, 0.25);
          } else { S.view.x = drag.vx + dx; S.view.y = drag.vy + dy; S.userMoved = true; }
        }
        return;
      }
      if (ev.target !== c) return;
      const w = toWorld(ev), id = hit(w.x, w.y);
      if (id !== S.hover) { S.hover = id; showTooltip(id, w.px, w.py); }
      else if (id) showTooltip(id, w.px, w.py);
    });
    window.addEventListener("mouseup", () => {
      if (drag && !drag.moved) select(drag.id);
      drag = null; c.classList.remove("dragging");
    });
    c.addEventListener("dblclick", (ev) => {
      const w = toWorld(ev), id = hit(w.x, w.y);
      if (id) { pos.get(id).fixed = false; S.alpha = Math.max(S.alpha, 0.3); } else fit();
    });
    c.addEventListener("mouseleave", () => { S.hover = null; showTooltip(null); });
    c.addEventListener("wheel", (ev) => {
      ev.preventDefault();
      const w = toWorld(ev), f = Math.exp(-ev.deltaY * 0.0012), k = Math.max(0.08, Math.min(4, S.view.k * f));
      S.view.x = w.px - w.x * k; S.view.y = w.py - w.y * k; S.view.k = k; S.userMoved = true;
    }, { passive: false });
    c.addEventListener("keydown", (ev) => {
      if (ev.key === "Escape") select(null);
      if (ev.key === "f") fit();
    });
  }
  function showTooltip(id, x, y) {
    const t = $("tooltip");
    if (!id) { t.hidden = true; return; }
    const n = store.nodes.get(id);
    const st = store.state(n);
    t.innerHTML = `<strong>${esc(n.kind)}</strong> ${st ? `<span class="pill ${st.toLowerCase()}">${st}</span>` : ""}<br>${esc(n.label || n.id)}`
      + (n.agent ? `<br><span class="muted">${esc(n.agent)}${n.mtype ? " · " + esc(n.mtype) : ""}</span>` : "");
    t.hidden = false;
    t.style.left = Math.min(x + 14, $("canvas").clientWidth - 330) + "px";
    t.style.top = Math.max(8, y + 14) + "px";
  }

  // ---- selection + inspector ------------------------------------------------------------
  function select(id) {
    S.selected = id;
    S.lineage = id ? store.lineage(id) : null;
    refreshVisible(); renderInspector();
    emit("select", { id, node: id ? store.nodes.get(id) : null });
  }
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const pill = (st) => st ? `<span class="pill ${String(st).toLowerCase()}">${esc(st)}</span>` : "";

  function treeHtml(n, depth) {
    if (!n) return "";
    if (n.cycle) return `<li class="muted">${esc(n.id)} (cycle)</li>`;
    const js = n.justifications || [];
    let h = `<li><button data-id="${esc(n.id)}">${esc((n.text || n.id).slice(0, 70))}</button> ${pill(n.status)}`;
    if (n.source) h += ` <span class="muted">from ${esc(n.source.id)} (trust ${esc(n.source.trust)})</span>`;
    if (js.length && depth < 5) {
      h += "<ul class='tree'>";
      js.forEach((j, i) => {
        h += `<li><span class="j">${js.length > 1 ? `option ${i + 1} · ` : ""}${esc(j.rule)} by ${esc(j.agent)} · needs all of:</span><ul class="tree">`
          + (j.premises || []).map((p) => treeHtml(p, depth + 1)).join("") + "</ul></li>";
      });
      h += "</ul>";
    }
    return h + "</li>";
  }

  async function renderInspector() {
    const el = $("inspector");
    if (!el) return;
    const id = S.selected;
    if (!id) { el.innerHTML = `<p class="muted">Click a node to see what it rests on. Everything it depends on lights up; everything that depends on it lights up in a second colour.</p>`; return; }
    const n = store.nodes.get(id);
    if (!n) { el.innerHTML = ""; return; }
    const st = store.state(n);
    let h = `<div class="row"><strong>${esc(n.kind)}</strong> ${pill(st)}</div><p>${esc(n.label || n.id)}</p><dl class="kv">`;
    const kv = (k, v) => { if (v != null && v !== "") h += `<dt>${k}</dt><dd>${esc(v)}</dd>`; };
    kv("id", n.id); kv("agent", n.agent); kv("memory type", n.mtype);
    kv("amount", n.amount); kv("executed", n.executed); kv("gate", n.gate);
    kv("trust", n.trust); kv("source kind", n.skind); kv("rule", n.rule);
    h += "</dl>";
    if (S.lineage) h += `<p class="muted">Rests on ${S.lineage.up.size} node(s) · ${S.lineage.down.size} depend on it.</p>`;
    el.innerHTML = h + `<p class="muted" id="insp-more">Loading justification…</p>`;
    if (n.kind === "source" || n.kind === "justification") { const m = $("insp-more"); if (m) m.remove(); return; }
    try {
      const d = await api("/api/node?" + q({ graph: S.graph, id }));
      if (S.selected !== id) return;
      let more = "";
      const f = d.fragility;
      if (f && st !== "OUT") {
        more += `<h2>Poisoning cost</h2><p><strong>${f.independent_sources}</strong> source(s) must fail before this falls `
          + `<span class="muted">(${esc(f.bound)}${f.cut_set && f.cut_set.length ? "; weakest cut: " + esc(f.cut_set.join(", ")) : ""})</span></p>`;
      }
      more += `<h2>Why is this ${esc(String(st || "").toLowerCase() || "here")}?</h2><ul class="tree" style="border:0;padding:0">${treeHtml(d.why, 0)}</ul>`;
      const m = $("insp-more");
      if (m) m.outerHTML = more;
    } catch (e) {
      const m = $("insp-more");
      if (m) m.outerHTML = `<p class="err">${esc(e.message)}</p>`;
    }
  }

  // ---- sidebar --------------------------------------------------------------------------
  function buildSidebar() {
    const side = $("side");
    side.innerHTML = `
      <section><h2>Summary</h2><div id="summary" class="checks"></div></section>
      <section><h2>Selection</h2><div id="inspector"></div></section>
      <div id="panels"></div>
      <section><h2>Filter</h2>
        <div class="checks" id="f-kinds"></div>
        <div class="checks" id="f-states" style="margin-top:8px"></div>
        <div class="row" style="margin-top:8px">
          <select id="f-agent" aria-label="Agent"><option value="">All agents</option></select>
          <input id="f-query" type="search" placeholder="Find text or id" aria-label="Find a node" style="flex:1;min-width:120px">
        </div>
        <ul id="f-results" class="tree" style="border:0;padding:0"></ul>
      </section>
      <section><h2>Legend</h2><div class="legend">
        <span><i class="sw" style="background:var(--in)"></i>IN: supported</span>
        <span><i class="sw" style="background:var(--out)"></i>OUT: retracted ✕</span>
        <span><i class="sw" style="background:var(--tent)"></i>tentative (mid-cascade)</span>
        <span><i class="sw" style="background:var(--recall)"></i>recall: already executed</span>
        <span><i class="sw" style="background:var(--src)"></i>source (square)</span>
        <span><i class="sw" style="background:none;border:3px solid var(--ep);border-radius:50%"></i>episodic</span>
        <span><i class="sw" style="background:none;border:3px solid var(--se);border-radius:50%"></i>semantic</span>
        <span><i class="sw" style="background:none;border:3px solid var(--pr);border-radius:50%"></i>procedural</span>
        <span>◆ small diamond: one justification (an AND)</span>
      </div></section>`;
    const kinds = ["source", "observation", "belief", "plan", "action", "justification"];
    $("f-kinds").innerHTML = kinds.map((k) => `<label><input type="checkbox" data-kind="${k}" checked>${k}</label>`).join("");
    $("f-states").innerHTML = ["IN", "OUT", "TENTATIVE"].map((s) => `<label><input type="checkbox" data-state="${s}" checked>${s}</label>`).join("");
    side.addEventListener("change", (ev) => {
      const t = ev.target;
      if (t.dataset.kind || t.dataset.state) {
        const ks = [...document.querySelectorAll("[data-kind]")], ss = [...document.querySelectorAll("[data-state]")];
        S.filter.kinds = ks.every((c) => c.checked) ? null : new Set(ks.filter((c) => c.checked).map((c) => c.dataset.kind));
        S.filter.states = ss.every((c) => c.checked) ? null : new Set(ss.filter((c) => c.checked).map((c) => c.dataset.state));
      }
      if (t.id === "f-agent") S.filter.agent = t.value || null;
      refreshVisible(); S.alpha = Math.max(S.alpha, 0.5);
    });
    $("f-query").addEventListener("input", (ev) => {
      S.filter.query = ev.target.value;
      refreshVisible(); S.alpha = Math.max(S.alpha, 0.5);
      const res = ev.target.value.trim() ? [...S.visible].slice(0, 8) : [];
      $("f-results").innerHTML = res.map((id) => `<li><button data-id="${esc(id)}">${esc((store.nodes.get(id).label || id).slice(0, 60))}</button></li>`).join("");
    });
    side.addEventListener("click", (ev) => {
      const b = ev.target.closest("button[data-id]");
      if (b) { select(b.dataset.id); const p = pos.get(b.dataset.id); if (p) { const c = $("canvas"); S.view.x = c.clientWidth / 2 - p.x * S.view.k; S.view.y = c.clientHeight / 2 - p.y * S.view.k; S.userMoved = true; } }
    });
  }

  function renderSummary() {
    const c = store.counts();
    const el = $("chips");
    const chip = (color, label, n) => `<span class="chip"><i style="background:${color}"></i>${label} <strong>${n}</strong></span>`;
    el.innerHTML = chip("var(--muted)", "memories", c.nodes - (c.byKind.source || 0))
      + chip("var(--in)", "IN", c.IN) + chip("var(--out)", "OUT", c.OUT)
      + (c.TENTATIVE ? chip("var(--tent)", "tentative", c.TENTATIVE) : "")
      + `<span class="chip">edges <strong>${c.edges}</strong></span>`;
    const s = $("summary");
    if (s) s.innerHTML = Object.entries(c.byKind).map(([k, n]) => `<span>${esc(k)} <strong>${n}</strong></span>`).join(" · ");
    const ag = $("f-agent");
    if (ag) {
      const cur = ag.value, agents = store.agents();
      if (ag.options.length - 1 !== agents.length) {
        ag.innerHTML = `<option value="">All agents</option>` + agents.map((a) => `<option>${esc(a)}</option>`).join("");
        ag.value = cur;
      }
    }
  }

  function banner(text) { const b = $("banner"); b.hidden = !text; b.textContent = text || ""; }
  function showEmpty(v) { $("empty").hidden = !v; }
  function setLive(ok, msg) {
    const btn = $("btn-live");
    $("live-text").textContent = !S.live ? "Paused" : ok ? "Live" : "Reconnecting…";
    btn.setAttribute("aria-pressed", String(S.live && ok));
    if (!ok && S.live) banner("Can't reach the graph server: " + (msg || "") + " Retrying…");
    else if (ok && $("banner").textContent.startsWith("Can't")) banner("");
  }

  // ---- extension API --------------------------------------------------------------------
  window.RETCON = {
    store, state: S, positions: pos, on, emit,
    api, graph: () => S.graph,
    select, fit, refresh: poll, reload: loadSnapshot,
    centerOn(id) { const p = pos.get(id), c = $("canvas"); if (p) { S.view.x = c.clientWidth / 2 - p.x * S.view.k; S.view.y = c.clientHeight / 2 - p.y * S.view.k; S.userMoved = true; } },
    /** Outline nodes in a colour (a CSS var name like "--accent" or any colour); pass null to clear. */
    highlight(ids, colour) {
      readColors();
      for (const id of ids) {
        if (colour == null) S.extraHighlight.delete(id);
        else S.extraHighlight.set(id, colour.startsWith("--") ? C[colour.slice(2)] || getComputedStyle(document.documentElement).getPropertyValue(colour).trim() : colour);
      }
    },
    clearHighlights() { S.extraHighlight.clear(); },
    flash(ids, kind) { const now = performance.now(); ids.forEach((id) => flashes.set(id, { t: now, kind: kind || "new" })); },
    panels: {
      /** add({id, title, mount(el, RETCON)}): a collapsible section in the sidebar. */
      add(def) {
        const host = $("panels");
        const sec = document.createElement("section");
        sec.id = "panel-" + def.id;
        sec.innerHTML = `<h2>${esc(def.title)}</h2><div class="body"></div>`;
        host.appendChild(sec);
        def.mount(sec.querySelector(".body"), window.RETCON);
        return sec;
      },
    },
  };

  // ---- boot -----------------------------------------------------------------------------
  async function boot() {
    buildSidebar();
    readColors();
    window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", readColors);
    setupInteraction();
    new ResizeObserver(() => { if (!S.userMoved) fit(); }).observe($("canvas"));
    $("btn-live").addEventListener("click", () => { S.live = !S.live; setLive(true); if (S.live) poll(); });
    $("btn-fit").addEventListener("click", () => fit());
    $("btn-layout").addEventListener("click", (ev) => {
      S.columns = !S.columns; ev.currentTarget.setAttribute("aria-pressed", String(S.columns)); S.alpha = 1;
    });
    window.addEventListener("hashchange", () => {
      const g = new URLSearchParams(location.hash.slice(1)).get("graph");
      if (g && g !== S.graph && [...$("graph-select").options].some((o) => o.value === g)) {
        $("graph-select").value = g; S.graph = g; loadSnapshot();
      }
    });
    $("graph-select").addEventListener("change", (ev) => {
      location.hash = "graph=" + encodeURIComponent(ev.target.value);
      S.graph = ev.target.value; loadSnapshot();
    });
    try {
      S.graph = await loadGraphs();
      await loadSnapshot();
    } catch (e) { banner("Can't reach the graph server: " + e.message); }
    requestAnimationFrame(frame);
    setInterval(poll, 800);
    emit("ready", window.RETCON);
  }
  boot();
})();
