// node --test tests/ui : pure logic of the shell (layout + store), no browser needed.
const test = require("node:test");
const assert = require("node:assert");
const Layout = require("../../ui/shell/static/layout.js");
const { GraphStore } = require("../../ui/shell/static/store.js");

function demo() {
  const nodes = [
    { id: "s1", kind: "source" }, { id: "o1", kind: "observation" }, { id: "o2", kind: "observation" },
    { id: "j1", kind: "justification" }, { id: "b1", kind: "belief" }, { id: "p1", kind: "plan" }, { id: "a1", kind: "action" },
  ];
  const edges = [
    { s: "s1", t: "o1" }, { s: "s1", t: "o2" }, { s: "o1", t: "j1" }, { s: "o2", t: "j1" },
    { s: "j1", t: "b1" }, { s: "b1", t: "p1" }, { s: "p1", t: "a1" },
  ];
  nodes.forEach((n) => Layout.seed(n, [], {}));
  return { nodes, edges };
}

test("layout is deterministic and finite", () => {
  const a = demo(), b = demo();
  for (let i = 0; i < 200; i++) { Layout.step(a.nodes, a.edges, 1, {}); Layout.step(b.nodes, b.edges, 1, {}); }
  assert.deepStrictEqual(a.nodes.map((n) => [n.x, n.y]), b.nodes.map((n) => [n.x, n.y]));
  for (const n of a.nodes) assert.ok(Number.isFinite(n.x) && Number.isFinite(n.y));
});

test("columns order provenance left to right", () => {
  const { nodes, edges } = demo();
  for (let i = 0; i < 300; i++) Layout.step(nodes, edges, 1, { columns: true });
  const x = Object.fromEntries(nodes.map((n) => [n.id, n.x]));
  assert.ok(x.s1 < x.o1 && x.o1 < x.j1 && x.j1 < x.b1 && x.b1 < x.p1 && x.p1 < x.a1, JSON.stringify(x));
});

test("nodes in one column do not sit on top of each other", () => {
  const nodes = [];
  for (let i = 0; i < 30; i++) nodes.push({ id: "o" + i, kind: "observation" });
  nodes.forEach((n) => Layout.seed(n, [], {}));
  for (let i = 0; i < 400; i++) Layout.step(nodes, [], 1, {});
  let min = Infinity;
  for (let i = 0; i < nodes.length; i++) for (let j = i + 1; j < nodes.length; j++)
    min = Math.min(min, Math.hypot(nodes[i].x - nodes[j].x, nodes[i].y - nodes[j].y));
  assert.ok(min > 8, "closest pair " + min);
});

test("a new node is seeded next to its neighbour", () => {
  const nb = { id: "x", kind: "belief", x: 500, y: 300 };
  const n = Layout.seed({ id: "new", kind: "plan" }, [nb], {});
  assert.ok(Math.hypot(n.x - 500, n.y - 300) < 40);
});

function store() {
  const s = new GraphStore();
  s.load({
    version: 3,
    nodes: [
      { id: "src", kind: "source", status: null }, { id: "o", kind: "observation", status: "IN", agent: "intake", label: "Portal says X" },
      { id: "j", kind: "justification" }, { id: "b", kind: "belief", status: "IN", agent: "intake", mtype: "semantic", label: "Belief B" },
      { id: "p", kind: "plan", status: "IN", agent: "payments", label: "Pay it" },
    ],
    edges: [
      { s: "src", t: "o", type: "SUPPORTS" }, { s: "o", t: "j", type: "PREMISE_OF" },
      { s: "j", t: "b", type: "JUSTIFIES" }, { s: "b", t: "j2", type: "PREMISE_OF" }, { s: "j2", t: "p", type: "JUSTIFIES" },
    ],
  });
  s.nodes.set("j2", { id: "j2", kind: "justification" });
  return s;
}

test("store: justification liveness is an AND over premises", () => {
  const s = store();
  assert.strictEqual(s.state(s.nodes.get("j")), "IN");
  s.applyDelta({ updates: [{ id: "o", status: "OUT" }], version: 4 });
  assert.strictEqual(s.state(s.nodes.get("j")), "OUT");
  assert.strictEqual(s.version, 4);
});

test("store: delta adds nodes and edges once and reports status changes", () => {
  const s = store();
  const d = { nodes: [{ id: "a", kind: "action", status: "IN" }], edges: [{ s: "p", t: "a", type: "JUSTIFIES" }],
              updates: [{ id: "b", status: "OUT", run: "r1" }], version: 9 };
  const r1 = s.applyDelta(d);
  assert.deepStrictEqual(r1.added, ["a"]);
  assert.strictEqual(r1.edges, 1);
  assert.deepStrictEqual(r1.changed, [{ id: "b", from: "IN", to: "OUT" }]);
  const r2 = s.applyDelta(d);                        // replay is idempotent
  assert.deepStrictEqual(r2.added, []);
  assert.strictEqual(r2.edges, 0);
  assert.strictEqual(s.state(s.nodes.get("b")), "TENTATIVE");   // run tag => mid-cascade
});

test("store: lineage walks both directions", () => {
  const s = store();
  const { up, down } = s.lineage("b");
  assert.ok(up.has("o") && up.has("src") && up.has("j"));
  assert.ok(down.has("p") && !down.has("o"));
});

test("store: filters by kind, state, agent and text", () => {
  const s = store();
  assert.deepStrictEqual([...s.visible({ kinds: new Set(["belief"]) })], ["b"]);
  assert.ok(s.visible({ agent: "payments" }).has("p") && !s.visible({ agent: "payments" }).has("b"));
  assert.ok(s.visible({ query: "portal" }).has("o") && !s.visible({ query: "portal" }).has("b"));
  s.applyDelta({ updates: [{ id: "p", status: "OUT" }] });
  assert.ok(s.visible({ states: new Set(["OUT"]) }).has("p"));
});

test("store: counts exclude sources and justifications from IN/OUT", () => {
  const c = store().counts();
  assert.strictEqual(c.IN, 3);
  assert.strictEqual(c.OUT, 0);
  assert.strictEqual(c.byKind.source, 1);
});
