# Running and deploying RETCON

The supported way to run it is **one command from a clean clone**. There is no hosted instance; rule 10's "full
local setup" is this file.

```bash
git clone https://github.com/mtrx28/retcon.git && cd retcon
docker compose up --build
```

Then open <http://127.0.0.1:8200> (front page; press **Retract** for the guided demo) and, if you want to look at
the raw graph, the FalkorDB Browser at <http://127.0.0.1:3000>. The first build downloads a Python image and three
small packages; later starts take seconds. No API key and no `.env` file are needed.

## What starts

| Service | What it does | Port on your machine |
|---|---|---|
| `falkordb` | the only store; image pinned by digest; data kept in the `falkordb-data` volume | `6379` (graph), `3000` (Browser) |
| `seed` | runs once: loads the 24-memory accounts-payable fixture as graph `tenant_northwind`, then exits | none |
| `app` | front page, graph canvas, guided demo, operator API (`python -m ui.shell.server`) | `127.0.0.1:8200` |

`app` waits for FalkorDB to be healthy and for `seed` to finish, so the graph is there when the page opens.

## Settings

| Variable | Default | Meaning |
|---|---|---|
| `RETCON_UI_PORT` | `8200` | host port for the app |
| `FALKORDB_HOST_PORT` / `FALKORDB_BROWSER_PORT` | `6379` / `3000` | host ports for FalkorDB (move them if taken) |
| `RETCON_EMBEDDER` | `hash` (in the image) | offline embedder. The real model (`minilm`) needs `pip install -e ".[embed]"`, which pulls PyTorch, so it is not in the image |
| `RETCON_TENANT` | `northwind` | the graph `tenant_<id>` the app opens first |
| `GEMINI_API_KEY` | unset | only to **record** a new Payments-agent transcript; replay needs none |

Example with moved ports: `FALKORDB_HOST_PORT=6390 RETCON_UI_PORT=8290 docker compose up --build`.

## Everyday commands

```bash
docker compose up -d --build           # start in the background
docker compose logs -f app             # watch it
docker compose down                    # stop (the graph stays in the volume)
docker compose down -v                 # stop and forget everything, back to a clean start
docker compose run --rm app python -m agents.demo --brain replay      # the agent day in a terminal, no key
docker compose run --rm app python -m bench.baselines.run --scenarios ap_tiny,ap_prec_1k --out /tmp/b.json
```

`python tasks.py up` (the development shortcut) still starts only FalkorDB, so you can run Python on the host
against it. The development guide in the README uses that path.

## Using it as an MCP server from Claude Code or another client

Run the server on the host (see [MCP_CLIENT.md](MCP_CLIENT.md)), pointed at the compose FalkorDB on `6379`, or run
it in the container over stdio:

```bash
claude mcp add retcon -- docker compose -f /full/path/to/retcon/docker-compose.yml run --rm -T app \
  python -m mcp_server.server
```

The server opens graph `tenant_<RETCON_TENANT>`; build one first with the `agents.demo` line above.

## A hosted FalkorDB (for example FalkorDB Cloud)

The app reads its connection from the environment, so pointing at a hosted instance needs no code change:

```bash
FALKORDB_HOST=<host> FALKORDB_PORT=<port> FALKORDB_USERNAME=<user> FALKORDB_PASSWORD=<password> FALKORDB_SSL=1 \
  python -m ui.shell.server --port 8200
```

Be straight about what has been tested: the variables are wired and unit-tested (`core/db.py`), and **everything
else here was run against the local FalkorDB container only**. We have not deployed to FalkorDB Cloud.

## Security notes

- The operator API (preview, commit, reinstate, approve) is for a person at the keyboard. Compose publishes it to
  `127.0.0.1` only, and every write also needs a per-process token the page fetches for itself. Do not expose port
  8200 to a network you do not trust.
- The image runs as an unprivileged user, contains no `.env` and no raw downloads (`.dockerignore`), and the only
  secret anywhere in the project is the optional Gemini key in your own `.env`.
- Payments go to a mock bank and e-mails to a sandbox inbox; the data is synthetic or public ([DATA.md](../DATA.md)).

## If something does not start

| Symptom | Fix |
|---|---|
| `error during connect: ... dockerDesktopLinuxEngine` | Docker Desktop is not running; start it and retry |
| `port is already allocated` on 6379 or 3000 | another Redis or FalkorDB is using it; set `FALKORDB_HOST_PORT` / `FALKORDB_BROWSER_PORT` |
| Page opens but the graph list is empty | `docker compose logs seed`; `docker compose up seed` re-runs it |
| Front page numbers are blank | `bench/results/latest.json` is missing; run the benchmark (`python tasks.py bench`) |
