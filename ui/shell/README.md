# UI shell (B6a)

A canvas over the live FalkorDB graph. Dependency-free (stdlib server, vanilla JS, no build step), so it
works offline.

```bash
python tasks.py up                 # FalkorDB (dev box: FALKORDB_PORT=6380)
python tasks.py ui                 # prints http://127.0.0.1:8200
python tasks.py demo --live        # agents work and the graph grows; after a pause the portal is distrusted
```

Open `http://127.0.0.1:8200/#graph=<name>`; the selector lists every graph (`tenant_*` first).

## What you see
- Left to right: **sources → observations → justifications → beliefs → plans → actions** (Columns toggle).
- Colour = state: **IN** green, **OUT** red with a ✕ (second cue besides colour), **tentative** amber dashed (mid-cascade).
- Ring = memory type: episodic blue, semantic purple, procedural orange. Small diamond = one justification (an AND).
- Click a node: what it rests on lights up blue, what rests on it amber; the inspector shows the justification
  tree (`why`) and the poisoning cost (`fragility`).
- Live: the page polls `/api/delta` every 0.8 s; new nodes pulse, flipped nodes flash.

## HTTP API (read-only)
| Route | Returns |
|---|---|
| `GET /api/graphs` | `[{name}]` |
| `GET /api/graph?graph=` | `{version, nodes, edges, counts, truncated}` |
| `GET /api/delta?graph=&since=` | `{version, nodes, edges, updates:[{id, status, run, executed, gate, retracted_at}], counts}` or `{reset:true}` |
| `GET /api/node?graph=&id=` | `{why, fragility}` |
| `GET /api/retractions?graph=` | `{retractions:[{id, source, from, to, reason, flipped, reinstated}]}` |

Errors are the contract shape `{"error": {code, message, details}}`.

## Extending it (A6: cascade / preview / recall; B6b: fragility radar)
`window.RETCON` is available after the `ready` event:

```js
RETCON.on("ready", (R) => {
  R.panels.add({ id: "recall", title: "Recall list", mount(el, R) { el.textContent = "..."; } });
});
RETCON.on("delta", ({ result, delta }) => { /* result.added, result.changed[{id, from, to}] */ });
RETCON.on("select", ({ id, node }) => {});
RETCON.on("draw", ({ ctx, sx, sy, k, now }) => { /* paint overlays: sx/sy map graph x/y to screen */ });
RETCON.highlight(ids, "--accent");   // outline nodes; highlight(ids, null) clears, clearHighlights()
RETCON.flash(ids, "out");            // one-off ring: "new" | "in" | "out" | "tent"
RETCON.select(id); RETCON.centerOn(id); RETCON.fit();
RETCON.api("/api/retractions?graph=" + RETCON.graph());   // fetch helper (throws on {error})
RETCON.store     // GraphStore: nodes (Map), edges, state(n), lineage(id), counts(), visible(filter)
RETCON.positions // id -> {x, y, kind, fixed}: for animations that need coordinates
```

Cascade hop animation (A6) can use `distrust().hops` (`{hop: [ids]}`) with `RETCON.flash` per hop; the
shell already shows the final state through the delta feed.

## Tests
`python tasks.py accept B6A` (API + static files) and `node --test tests/ui` (layout + store logic).
The canvas rendering itself is checked by eye in a browser (see STATUS for the manual script).

## Operator console (A6, `ui/ops/`)
Three panels (Operator, Recall list and compensations, Retractions) and a header badge, added through the
extension API above. They talk to `/api/ops/*` (token-guarded writes: preview, commit, reinstate, approve /
reject). See `ui/ops/__init__.py` for the routes. Set `RETCON_SANDBOX_URL` so approved recalls reach the
sandbox bank; without it an approval is recorded and nothing is sent.
