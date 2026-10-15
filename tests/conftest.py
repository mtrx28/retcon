import os

# Tests never download a model: the hash embedder has the same 384 dims as MiniLM.
os.environ.setdefault("RETCON_EMBEDDER", "hash")
