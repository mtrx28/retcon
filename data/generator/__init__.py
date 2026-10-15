"""Seeded Northwind AP scenario generator (task B4a). Emits the fixture format of CONTRACT.md §8.

    from data.generator import generate
    spec = generate(seed=7, vendors=3)           # small, demo-shaped
    spec = generate(seed=7, vendors=420)         # ~10k Mem nodes (B7 scale runs)

Same seed + parameters => byte-identical output. Ground truth is computed by an independent
in-memory JTMS fixpoint (`reference_labels`), never by the graph engine under test.
"""
from data.generator.scenario import generate, reference_labels, validate, vendors_for_nodes  # noqa: F401
