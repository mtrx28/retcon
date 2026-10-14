"""FalkorDB connection helpers shared by both lanes."""
import os

from falkordb import FalkorDB


def connect() -> FalkorDB:
    return FalkorDB(host=os.getenv("FALKORDB_HOST", "localhost"),
                    port=int(os.getenv("FALKORDB_PORT", "6379")))


def tenant_graph(tenant: str | None = None, db: FalkorDB | None = None):
    """Graph for a tenant. One graph per tenant, named tenant_<id> (docs/CONTRACT.md section 1)."""
    tenant = tenant or os.getenv("RETCON_TENANT", "northwind")
    return (db or connect()).select_graph(f"tenant_{tenant}")
