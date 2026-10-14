// Applied by data/load_fixture.py and the server when a tenant graph is created.
// One statement per line; lines starting with // are ignored.
// The vector index is created separately because its dimension is a parameter (see docs/SPIKE.md).
CREATE INDEX FOR (m:Mem) ON (m.id)
CREATE INDEX FOR (m:Mem) ON (m.status)
CREATE INDEX FOR (s:Source) ON (s.id)
CREATE INDEX FOR (o:Observation) ON (o.observed_at)
CREATE INDEX FOR (j:Justification) ON (j.id)
