"""python -m core.retrieve.embed_cli : create the vector index and embed all Mem nodes of the tenant."""
from core.db import tenant_graph
from core.retrieve.embed import get_embedder
from core.retrieve.q2 import embed_graph

if __name__ == "__main__":
    n = embed_graph(tenant_graph(), get_embedder())
    print(f"embedded {n} Mem nodes")
