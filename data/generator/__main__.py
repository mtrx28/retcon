"""python -m data.generator --seed 7 --vendors 3 [--nodes 10000] -o data/fixtures/ap_gen.json"""
import argparse
import json
import sys

from data.generator import generate, vendors_for_nodes, validate

p = argparse.ArgumentParser(description=__doc__)
p.add_argument("--seed", type=int, default=7)
p.add_argument("--vendors", type=int, default=3)
p.add_argument("--nodes", type=int, help="target Mem node count (overrides --vendors)")
p.add_argument("--invoices", type=int, default=2)
p.add_argument("--launder-depth", type=int, default=2)
p.add_argument("--poisoned", type=int, default=1)
p.add_argument("-o", "--out", help="output path (default stdout)")
a = p.parse_args()

vendors = vendors_for_nodes(a.nodes, a.invoices, a.launder_depth) if a.nodes else a.vendors
spec = generate(a.seed, vendors, a.invoices, a.launder_depth, a.poisoned)
problems = validate(spec)
if problems:
    sys.exit("invalid scenario:\n" + "\n".join(problems[:10]))
text = json.dumps(spec, indent=1, sort_keys=False)
if a.out:
    open(a.out, "w", encoding="utf8").write(text)
    n = len(spec["observations"]) + len({d["conclusion"]["id"] for d in spec["derivations"]}) + len(spec["actions"])
    print(f"wrote {a.out}: {vendors} vendors, {n} Mem nodes, {len(spec['ground_truth']['contaminated'])} contaminated")
else:
    print(text)
