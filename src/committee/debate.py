import json

from committee.agents import AGENTS, Suggestion, run_agent
from committee.ledger import Ledger


def _round2_context(
    base: str, rivals: dict[str, Suggestion], scores: dict[str, float], name: str
) -> str:
    rival_block = json.dumps(
        {agent: s.model_dump() for agent, s in rivals.items() if agent != name},
        indent=2,
    )
    scoreboard = json.dumps(scores, indent=2)
    return (
        f"{base}\n\n"
        f"ROUND 2. Rival recommendations from round 1:\n{rival_block}\n\n"
        f"Current reputation scores:\n{scoreboard}\n\n"
        "Attack the weakest specific claim of EACH rival by name, quoting the "
        "claim, in the attacks list. State plainly if a rival changed your mind. "
        "Then give your final recommendation, kept or changed."
    )


def run_debate(client, context: str, ledger: Ledger, histories: dict | None = None) -> dict:
    histories = histories or {}
    base = {name: context + histories.get(name, "") for name in AGENTS}
    round1 = {name: run_agent(name, client, base[name]) for name in AGENTS}
    scores = ledger.scores()
    final = {
        name: run_agent(name, client, _round2_context(base[name], round1, scores, name))
        for name in AGENTS
    }
    return {"round1": round1, "final": final}
