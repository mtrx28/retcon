"""FalkorDB connection helpers. One graph per tenant: `tenant_<id>` (docs/CONTRACT.md section 1)."""
import os

from falkordb import FalkorDB


def connect():
    return FalkorDB(host=os.getenv("FALKORDB_HOST", "localhost"),
                    port=int(os.getenv("FALKORDB_PORT", "6379")))


def tenant_graph(tenant=None, db=None):
    db = db or connect()
    return db.select_graph(f"tenant_{tenant or os.getenv('RETCON_TENANT', 'northwind')}")
