"""Embeddings (384-dim, per docs/CONTRACT.md section 2).

`minilm` is the real model (sentence-transformers/all-MiniLM-L6-v2, local, no API key).
`hash` is a deterministic bag-of-words hasher with the same dimension: no download, used by
tests and offline runs. Select with RETCON_EMBEDDER=minilm|hash (default minilm). Vectors from
the two are not comparable, so a graph must be embedded with one embedder only.
"""
import hashlib
import math
import os
import re

DIM = 384
_TOKEN = re.compile(r"[a-z0-9]+")


class HashEmbedder:
    name = "hash"
    dim = DIM

    def embed(self, texts):
        return [self._one(t) for t in texts]

    def _one(self, text):
        v = [0.0] * DIM
        for tok in _TOKEN.findall(text.lower()):
            h = int.from_bytes(hashlib.blake2b(tok.encode(), digest_size=8).digest(), "big")
            v[h % DIM] += 1.0 if (h >> 32) & 1 else -1.0
        norm = math.sqrt(sum(x * x for x in v))
        if norm == 0:
            v[0], norm = 1.0, 1.0
        return [x / norm for x in v]


class MiniLMEmbedder:
    name = "minilm"
    dim = DIM

    def __init__(self):
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as e:
            raise RuntimeError("sentence-transformers is not installed; run "
                               "`pip install -e .[embed]` or set RETCON_EMBEDDER=hash") from e
        self._model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")

    def embed(self, texts):
        return [[float(x) for x in row]
                for row in self._model.encode(list(texts), normalize_embeddings=True)]


def get_embedder(name=None):
    name = (name or os.getenv("RETCON_EMBEDDER", "minilm")).lower()
    if name == "hash":
        return HashEmbedder()
    if name == "minilm":
        return MiniLMEmbedder()
    raise ValueError(f"unknown embedder {name!r} (expected 'minilm' or 'hash')")
