"""Research agents (task A10): Reader and Synthesizer on the B3 agent loop.

The same machinery as the accounts-payable team (Orchestrator, toolbox, premise capture, the graph
deciding IN/OUT); only the policies differ.

Reader        task {"type": "read_paper", source, paper, index, text, observed_at, cited_texts, topic_text}
              recall each cited (retracted-later) claim so it enters the context -> observe the
              sentence -> remember the claim. The claim's justification is an AND of the sentence and
              whatever it relied on, found automatically: the Reader never names parents.
Synthesizer   {"type": "synthesize", claim_text, topic_text}
              recall one paper's claim -> remember the topic-level position. Each paper that supports
              the topic adds one justification (an OR), so independent papers corroborate.
              {"type": "review_topics", topic_texts}
              after a retraction: for each topic it holds, call `fragility` (a graph algorithm used as
              a tool) and report whether the position stands and on how many independent papers.

ResearchBrain handles the two research roles and delegates every other role to the RuleBrain.
"""
from agents.brain import GeneratorSession, RuleBrain
from agents.common import call, failed, ok_list

TOPIC_PREFIX = "Literature position on "


def reader_policy(task, params):
    yield call("begin_turn")
    relied_on = []
    for text in task.get("cited_texts", []):
        hits = ok_list((yield call("recall", query=text, k=1)))
        if hits and hits[0].get("text") == text:       # only an exact match counts as the cited claim
            relied_on.append(hits[0]["id"])
    obs = yield call("observe", source=task["source"], text=task["text"], observed_at=task["observed_at"])
    if failed(obs):
        return {"summary": f"observe failed: {obs['error']['code']}"}
    claim = yield call("remember", text=task["text"], kind="belief", mtype="semantic")
    if failed(claim):
        return {"summary": f"remember failed: {claim['error']['code']}"}
    outbox = []
    if task.get("topic_text"):
        outbox.append(("synthesizer", {"type": "synthesize", "claim_text": task["text"],
                                       "topic_text": task["topic_text"], "paper": task.get("paper")}))
    return {"summary": f"read {task.get('paper')}#{task.get('index')}"
                       + (f", relies on {len(relied_on)} cited claim(s)" if relied_on else ""),
            "outbox": outbox,
            "data": {"observation_id": obs["node_id"], "claim_id": claim["node_id"],
                     "relied_on": relied_on, "premise_ids": claim["premise_ids"]}}


def synthesizer_policy(task, params):
    yield call("begin_turn")
    if task["type"] == "synthesize":
        hits = ok_list((yield call("recall", query=task["claim_text"], k=1)))
        if not hits or hits[0].get("text") != task["claim_text"]:
            return {"summary": "claim no longer in memory; nothing to synthesize"}
        topic = yield call("remember", text=task["topic_text"], kind="belief", mtype="semantic")
        if failed(topic):
            return {"summary": f"remember failed: {topic['error']['code']}"}
        return {"summary": f"topic supported by {task.get('paper')}", "data": {"topic_id": topic["node_id"]}}

    if task["type"] == "review_topics":
        standing, withdrawn = [], []
        for text in task["topic_texts"]:
            hits = ok_list((yield call("recall", query=text, k=1)))
            if not hits or hits[0].get("text") != text:
                withdrawn.append(text)
                continue
            f = yield call("fragility", node_id=hits[0]["id"])
            standing.append({"text": text, "id": hits[0]["id"],
                             "independent_sources": None if failed(f) else f["independent_sources"]})
        return {"summary": f"{len(standing)} topic(s) stand, {len(withdrawn)} withdrawn",
                "data": {"standing": standing, "withdrawn": withdrawn}}
    return {"summary": f"synthesizer has no policy for task {task['type']!r}"}


class ResearchBrain:
    """Same interface as RuleBrain (`start(role, task) -> Session`)."""

    def __init__(self, params=None):
        self.params = params or {}
        self._rules = RuleBrain(params)

    def start(self, role, task):
        if role == "reader":
            return GeneratorSession(reader_policy(task, self.params))
        if role == "synthesizer":
            return GeneratorSession(synthesizer_policy(task, self.params))
        return self._rules.start(role, task)
