// node --test tests/ui : the radar's pure layout (no DOM).
const test = require("node:test");
const assert = require("node:assert");
const { layout, MAX_COST } = require("../../ui/radar/radar.js");

const item = (id, n) => ({ id, independent_sources: n });

test("distance from the centre grows with poisoning cost and is capped", () => {
  const L = layout([item("a", 1), item("b", 2), item("c", 3), item("d", 9)], 2);
  const dist = (p) => Math.hypot(p.x - 150, p.y - 150);
  const [a, b, c, d] = L.points;
  assert.ok(dist(a) < dist(b) && dist(b) < dist(c));
  assert.ok(Math.abs(dist(d) - dist(layout([item("x", MAX_COST)], 2).points[0])) < 1e-9);   // 9 is drawn as 4+
});

test("only costs below the policy minimum are flagged", () => {
  const L = layout([item("a", 1), item("b", 2), item("c", 5)], 2);
  assert.deepStrictEqual(L.points.map((p) => p.below), [true, false, false]);
  assert.strictEqual(L.below, 1);
});

test("spokes are evenly spaced and start at twelve o'clock", () => {
  const L = layout([item("a", 4), item("b", 4), item("c", 4), item("d", 4)], 2);
  assert.ok(Math.abs(L.points[0].x - 150) < 1e-9 && L.points[0].y < 150);
  assert.ok(Math.abs(L.points[1].y - 150) < 1e-9 && L.points[1].x > 150);
});

test("empty and single-item inputs do not break", () => {
  assert.strictEqual(layout([], 2).n, 0);
  const one = layout([item("a", 1)], 2);
  assert.strictEqual(one.n, 1);
  assert.ok(Number.isFinite(one.points[0].x));
});
