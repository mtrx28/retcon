/* Incremental force layout with a left-to-right provenance bias:
   sources -> observations -> justifications -> beliefs -> plans -> actions.
   Pure functions over {id, kind, x, y, vx, vy, fixed} so the canvas can run it every frame and
   Node tests can check it. New nodes are seeded next to a neighbour so growth looks organic. */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.RetconLayout = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  const COLUMN = { source: 0, observation: 1, justification: 1.7, belief: 2.4, plan: 3.3, action: 4.2, mem: 2.4 };
  const DEFAULTS = {
    columnWidth: 230, columns: true, rest: 60, spring: 0.04, repulsion: 1400, cell: 100,
    columnPull: 0.14, rowSpring: 0.05, centerPull: 0.003, damping: 0.8, maxSpeed: 14,
  };

  function mulberry(seed) {            // deterministic jitter: same graph -> same first layout
    let a = seed >>> 0;
    return function () {
      a = (a + 0x6d2b79f5) >>> 0;
      let t = Math.imul(a ^ (a >>> 15), 1 | a);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  function hash(s) {
    let h = 2166136261;
    for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); }
    return h >>> 0;
  }

  /** Give a node a starting position: near the mean of already placed neighbours, else in its column. */
  function seed(node, placedNeighbours, opts) {
    const o = Object.assign({}, DEFAULTS, opts);
    const r = mulberry(hash(node.id));
    const col = (COLUMN[node.kind] === undefined ? 2 : COLUMN[node.kind]) * o.columnWidth;
    if (placedNeighbours.length) {
      let sx = 0, sy = 0;
      for (const p of placedNeighbours) { sx += p.x; sy += p.y; }
      node.x = sx / placedNeighbours.length + (r() - 0.5) * 40;
      node.y = sy / placedNeighbours.length + (r() - 0.5) * 40;
    } else {
      node.x = col + (r() - 0.5) * 60;
      node.y = (r() - 0.5) * 400;
    }
    node.vx = node.vy = 0;
    return node;
  }

  /** One simulation step. `alpha` in (0,1] scales every force (cooling). Returns the kinetic energy. */
  function step(nodes, edges, alpha, opts) {
    const o = Object.assign({}, DEFAULTS, opts);
    const byId = new Map(nodes.map((n) => [n.id, n]));
    // repulsion through a spatial hash: only same/adjacent cells interact
    const grid = new Map();
    const key = (cx, cy) => cx + "," + cy;
    for (const n of nodes) {
      const k = key(Math.floor(n.x / o.cell), Math.floor(n.y / o.cell));
      if (!grid.has(k)) grid.set(k, []);
      grid.get(k).push(n);
    }
    for (const n of nodes) {
      const cx = Math.floor(n.x / o.cell), cy = Math.floor(n.y / o.cell);
      for (let dx = -1; dx <= 1; dx++) for (let dy = -1; dy <= 1; dy++) {
        const cell = grid.get(key(cx + dx, cy + dy));
        if (!cell) continue;
        for (const m of cell) {
          if (m === n) continue;
          let rx = n.x - m.x, ry = n.y - m.y, d2 = rx * rx + ry * ry;
          if (d2 === 0) { rx = (hash(n.id) % 7) - 3 || 1; ry = (hash(m.id) % 5) - 2 || 1; d2 = rx * rx + ry * ry; }
          if (d2 > o.cell * o.cell * 4) continue;
          const f = (o.repulsion / d2) * alpha;
          const d = Math.sqrt(d2);
          n.vx += (rx / d) * f; n.vy += (ry / d) * f;
        }
      }
    }
    for (const e of edges) {                       // springs
      const a = byId.get(e.s), b = byId.get(e.t);
      if (!a || !b) continue;
      const rx = b.x - a.x, ry = b.y - a.y;
      if (o.columns) {
        // the columns own x; an edge only pulls its two ends level, so provenance reads left to right
        const fy = ry * o.rowSpring * alpha;
        a.vy += fy; b.vy -= fy;
        continue;
      }
      const d = Math.sqrt(rx * rx + ry * ry) || 0.01;
      const f = (d - o.rest) * o.spring * alpha;
      const fx = (rx / d) * f, fy = (ry / d) * f;
      a.vx += fx; a.vy += fy; b.vx -= fx; b.vy -= fy;
    }
    let energy = 0;
    for (const n of nodes) {
      if (o.columns) {
        const col = (COLUMN[n.kind] === undefined ? 2 : COLUMN[n.kind]) * o.columnWidth;
        n.vx += (col - n.x) * o.columnPull * alpha;
      }
      n.vy += -n.y * o.centerPull * alpha;
      n.vx *= o.damping; n.vy *= o.damping;
      const sp = Math.hypot(n.vx, n.vy);
      if (sp > o.maxSpeed) { n.vx *= o.maxSpeed / sp; n.vy *= o.maxSpeed / sp; }
      if (!n.fixed) { n.x += n.vx; n.y += n.vy; }
      energy += n.vx * n.vx + n.vy * n.vy;
    }
    return energy;
  }

  function bounds(nodes) {
    if (!nodes.length) return { x0: -100, y0: -100, x1: 100, y1: 100 };
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    for (const n of nodes) { x0 = Math.min(x0, n.x); y0 = Math.min(y0, n.y); x1 = Math.max(x1, n.x); y1 = Math.max(y1, n.y); }
    return { x0, y0, x1, y1 };
  }

  return { COLUMN, DEFAULTS, seed, step, bounds, hash };
});
