// node --test tests/ui : pure logic of the operator panels (A6), no browser needed.
const test = require("node:test");
const assert = require("node:assert");
const L = require("../../ui/ops/static/ops_logic.js");

const res = {
  flipped: { observations: 2, beliefs: 5, plans: 2, actions: 2 },
  hops: { "0": ["o1", "o2"], "2": ["p1"], "1": ["b1", "b2"] },
  blocked_action_ids: ["a2"], recall_list: [{ action_id: "a1", amount: 18400 }], survived_ids: ["b_addr"],
};

test("cascadeLine reads like the demo script", () => {
  assert.strictEqual(L.cascadeLine(res), "1 source → 2 observations → 5 beliefs → 2 plans → 2 actions");
  assert.strictEqual(L.cascadeLine({ flipped: { observations: 1, beliefs: 1, plans: 1, actions: 1 } }),
    "1 source → 1 observation → 1 belief → 1 plan → 1 action");
  assert.strictEqual(L.cascadeLine({}), "1 source → 0 observations → 0 beliefs → 0 plans → 0 actions");
});

test("consequenceLine counts blocked, recalled and kept", () => {
  assert.strictEqual(L.consequenceLine(res),
    "1 pending action blocked · 1 executed action to recall · 1 kept by independent support");
  assert.strictEqual(L.consequenceLine({}),
    "0 pending actions blocked · 0 executed actions to recall · 0 kept by independent support");
});

test("hopGroups sorts numerically, not lexically", () => {
  assert.deepStrictEqual(L.hopGroups({ "10": ["x"], "2": ["y"], "0": ["z"] }).map((g) => g.hop), [0, 2, 10]);
  assert.deepStrictEqual(L.hopGroups(null), []);
});

test("schedule spaces hops by stepMs in hop order", () => {
  const s = L.schedule(res.hops, 700);
  assert.deepStrictEqual(s.map((x) => [x.at, x.hop, x.ids.length]), [[0, 0, 2], [700, 1, 2], [1400, 2, 1]]);
});

test("byKind groups a preview diff", () => {
  const g = L.byKind([{ id: "a", kind: "belief" }, { id: "b", kind: "plan" }, { id: "c", kind: "belief" }]);
  assert.deepStrictEqual(g, { belief: ["a", "c"], plan: ["b"] });
});

test("datetime-local <-> ISO round trip in UTC", () => {
  assert.strictEqual(L.localToIso("2026-10-02T00:00"), "2026-10-02T00:00:00Z");
  assert.strictEqual(L.localToIso("2026-10-09T23:59:30"), "2026-10-09T23:59:30Z");
  assert.strictEqual(L.localToIso(""), null);
  assert.strictEqual(L.localToIso("not a date"), null);
  assert.strictEqual(L.epochToLocal(Date.UTC(2026, 9, 2) / 1000), "2026-10-02T00:00");
  assert.strictEqual(L.epochToLocal(null), "");
});

test("formatting", () => {
  assert.strictEqual(L.fmtMs(null), "n/a");
  assert.strictEqual(L.fmtMs(0.004), "0.004 ms");
  assert.strictEqual(L.fmtMs(11.84), "11.8 ms");
  assert.strictEqual(L.fmtMs(250), "250 ms");
  assert.strictEqual(L.money(18400), "$18,400");
  assert.strictEqual(L.money(null), "no amount");
});
