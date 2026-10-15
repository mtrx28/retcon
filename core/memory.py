"""Memory service: Q1 write + Q2 retrieval wired through premise capture (B1 + B2).

One instance per tenant graph. `recall` records what it returned into the calling agent's
context; `remember` then justifies the new node by that context. Agents never pass parents.
"""
from core.errors import RetconError
from core.retrieve import q2
from core.write import q1
from core.write.capture import PremiseCapture


class MemoryService:
    def __init__(self, graph, embedder, capture=None):
        self.g, self.embedder = graph, embedder
        self.capture = capture or PremiseCapture()
        q2.ensure_vector_index(graph)

    def observe(self, source, text, observed_at, agent="intake"):
        vec = self.embedder.embed([text])[0]
        r = q1.write_observation(self.g, source=source, text=text, observed_at=observed_at,
                                 agent=agent, embedding=vec)
        self.capture.record(agent, [r["node_id"]])  # what the agent just read is in its context
        return r

    def recall(self, query, agent, k=8, contains=None):
        if k < 1:
            raise RetconError("INVALID_ARGUMENT", "k must be >= 1", {"k": k})
        hits = q2.recall(self.g, self.embedder.embed([query])[0], k, contains)
        self.capture.record(agent, [h["id"] for h in hits])
        if hits:  # the agent now holds these in memory: retraction events are routed by HOLDS
            q1.ensure_agent(self.g, agent)
            self.g.query("MATCH (a:Agent {id:$a}), (m:Mem) WHERE m.id IN $ids MERGE (a)-[:HOLDS]->(m)",
                         {"a": agent, "ids": [h["id"] for h in hits]})
        return hits

    def remember(self, text, kind, agent, rule=None, mtype=None):
        vec = self.embedder.embed([text])[0]
        r = q1.write_justified(self.g, text=text, kind=kind, agent=agent, premise_ids=self.capture.context(agent),
                               rule=rule, embedding=vec, mtype=mtype)
        return r

    def learn_rule(self, text, agent, episode_ids):
        """Store a procedural rule justified by the episode(s) it was learned from (B1+).
        The episodes become the agent's context, so the write goes through the same capture path."""
        self.capture.begin_turn(agent)
        self.capture.record(agent, episode_ids)
        return self.remember(text, "belief", agent, rule="infer", mtype="procedural")

    def begin_turn(self, agent):
        self.capture.begin_turn(agent)
