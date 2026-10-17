"""FalkorDB connection helpers shared by both lanes."""
import os

from falkordb import FalkorDB


def connection_args(env=None) -> dict:
    """Keyword arguments for `FalkorDB(...)` from the environment.

    FALKORDB_HOST (localhost), FALKORDB_PORT (6379) always; FALKORDB_USERNAME, FALKORDB_PASSWORD and
    FALKORDB_SSL=1 only when set, for a hosted instance such as FalkorDB Cloud. The local docker-compose
    needs none of them."""
    env = os.environ if env is None else env
    args = {"host": env.get("FALKORDB_HOST", "localhost"), "port": int(env.get("FALKORDB_PORT", "6379"))}
    if env.get("FALKORDB_USERNAME"):
        args["username"] = env["FALKORDB_USERNAME"]
    if env.get("FALKORDB_PASSWORD"):
        args["password"] = env["FALKORDB_PASSWORD"]
    if env.get("FALKORDB_SSL", "").lower() in ("1", "true", "yes"):
        args["ssl"] = True
    return args


def connect() -> FalkorDB:
    return FalkorDB(**connection_args())


def tenant_graph(tenant: str | None = None, db: FalkorDB | None = None):
    """Graph for a tenant. One graph per tenant, named tenant_<id> (docs/CONTRACT.md section 1)."""
    tenant = tenant or os.getenv("RETCON_TENANT", "northwind")
    return (db or connect()).select_graph(f"tenant_{tenant}")


# FalkorDB's RESULTSET_SIZE defaults to 10000 and, when exceeded, silently drops the remaining rows: no
# error, no warning (found by bench/harness at 10k nodes; see docs/SPIKE.md). Any read that can return more
# than that must page.
RESULTSET_SIZE = 10_000


def fetch_all(g, cypher: str, params: dict | None = None, order_by: str | None = None, page: int = 5_000):
    """All rows of a read query, paged with SKIP/LIMIT so the server's result-set cap cannot truncate it.

    `order_by` is required (paging over an unordered result can skip or repeat rows) and is appended as
    `ORDER BY <order_by>`; it must be valid after the query's RETURN (an output alias or a variable still in
    scope). Do not pass a query that already has ORDER BY/SKIP/LIMIT, or an aggregation without aliases.
    """
    if not order_by:
        raise ValueError("fetch_all needs order_by so paging is deterministic")
    rows, skip = [], 0
    while True:
        chunk = g.query(f"{cypher} ORDER BY {order_by} SKIP $_skip LIMIT $_limit",
                        {**(params or {}), "_skip": skip, "_limit": page}).result_set
        rows += chunk
        if len(chunk) < page:
            return rows
        skip += page
