import json

from pydantic import BaseModel

from committee.agents import AGENTS, run_agent
from committee.fpl import Player
from committee.ledger import Ledger

BUDGET = 100.0
SQUAD_QUOTA = {"GKP": 2, "DEF": 5, "MID": 5, "FWD": 3}
MAX_PER_CLUB = 3

DRAFT_FORMAT = (
    "Respond with ONE JSON object only:\n"
    '{"formation": "<D-M-F, e.g. 3-4-3>", "squad": [15 player ids], '
    '"starting_xi": [11 player ids from squad], "captain": <player id from '
    'starting_xi>, "rationale": "<max 120 words>", "attacks": '
    '["<round 2 only: specific criticism of a rival draft>"]}'
)


class SquadDraft(BaseModel):
    agent: str
    formation: str
    squad: list[int]
    starting_xi: list[int]
    captain: int
    rationale: str = ""
    attacks: list[str] = []


def build_draft_context(players: list[Player]) -> str:
    by_position: dict[str, list[Player]] = {pos: [] for pos in SQUAD_QUOTA}
    for p in players:
        by_position[p.position].append(p)

    pool: list[Player] = []
    top_n = {"GKP": 8, "DEF": 15, "MID": 15, "FWD": 10}
    for pos, group in by_position.items():
        popular = sorted(group, key=lambda p: p.ownership, reverse=True)[: top_n[pos]]
        cheap = sorted(group, key=lambda p: p.price)[:4]
        for p in [*popular, *cheap]:
            if p not in pool:
                pool.append(p)

    lines = [
        f"id={p.id} {p.name} {p.team} {p.position} price={p.price} "
        f"owned={p.ownership}% status={p.status}"
        for p in pool
    ]
    return (
        "Draft a full FPL squad for gameweek 1 of the new season. Rules: budget "
        f"{BUDGET}m total for 15 players, exactly 2 GKP, 5 DEF, 5 MID, 3 FWD, at "
        f"most {MAX_PER_CLUB} players per club. Pick a starting eleven and a "
        "formation. Cheap bench enablers are listed too. Use only players from "
        "this list:\n" + "\n".join(lines) + f"\n\n{DRAFT_FORMAT}"
    )


def _formation_counts(formation: str) -> dict[str, int] | None:
    try:
        d, m, f = (int(x) for x in formation.split("-"))
    except ValueError:
        return None
    if d + m + f != 10:
        return None
    return {"GKP": 1, "DEF": d, "MID": m, "FWD": f}


def validate_draft(draft: SquadDraft, players: list[Player]) -> list[str]:
    lookup = {p.id: p for p in players}
    violations: list[str] = []

    if len(draft.squad) != 15 or len(set(draft.squad)) != 15:
        violations.append("squad must be 15 unique player ids")
    unknown = [pid for pid in draft.squad if pid not in lookup]
    if unknown:
        violations.append(f"unknown player ids: {unknown}")
        return violations

    squad = [lookup[pid] for pid in draft.squad]

    cost = round(sum(p.price for p in squad), 1)
    if cost > BUDGET:
        violations.append(f"budget exceeded: {cost}m > {BUDGET}m")

    for pos, quota in SQUAD_QUOTA.items():
        have = sum(1 for p in squad if p.position == pos)
        if have != quota:
            violations.append(f"need {quota} {pos}, drafted {have}")

    clubs: dict[str, int] = {}
    for p in squad:
        clubs[p.team] = clubs.get(p.team, 0) + 1
    for team, count in clubs.items():
        if count > MAX_PER_CLUB:
            violations.append(f"{count} players from {team}, max {MAX_PER_CLUB}")

    if len(draft.starting_xi) != 11 or not set(draft.starting_xi) <= set(draft.squad):
        violations.append("starting_xi must be 11 ids taken from the squad")
    else:
        counts = _formation_counts(draft.formation)
        if counts is None:
            violations.append(f"formation {draft.formation!r} is not valid")
        else:
            xi = [lookup[pid] for pid in draft.starting_xi]
            for pos, need in counts.items():
                have = sum(1 for p in xi if p.position == pos)
                if have != need:
                    violations.append(
                        f"formation {draft.formation} needs {need} {pos} in the "
                        f"starting eleven, drafted {have}"
                    )

    if draft.captain not in draft.starting_xi:
        violations.append("captain must be in the starting eleven")

    return violations


def _draft_once(name: str, client, context: str, players: list[Player]):
    draft = run_agent(name, client, context, response_model=SquadDraft)
    violations = validate_draft(draft, players)
    if violations:
        feedback = (
            f"{context}\n\nYour previous draft broke these rules, fix them:\n- "
            + "\n- ".join(violations)
        )
        draft = run_agent(name, client, feedback, response_model=SquadDraft)
        violations = validate_draft(draft, players)
    return draft, violations


def _round2_context(
    base: str, rivals: dict[str, SquadDraft], scores: dict[str, float], name: str
) -> str:
    rival_block = json.dumps(
        {agent: d.model_dump() for agent, d in rivals.items() if agent != name},
        indent=2,
    )
    return (
        f"{base}\n\nROUND 2. Rival drafts from round 1:\n{rival_block}\n\n"
        f"Current reputation scores:\n{json.dumps(scores, indent=2)}\n\n"
        "Attack the weakest specific choice of EACH rival by name, quoting the "
        "choice, in the attacks list. State plainly if a rival changed your mind. "
        "Then give your final draft, kept or changed."
    )


def run_draft_debate(client, players: list[Player], ledger: Ledger) -> dict:
    context = build_draft_context(players)
    round1 = {}
    for name in AGENTS:
        draft, _ = _draft_once(name, client, context, players)
        round1[name] = draft

    scores = ledger.scores()
    final = {}
    violations = {}
    for name in AGENTS:
        ctx = _round2_context(context, round1, scores, name)
        draft, remaining = _draft_once(name, client, ctx, players)
        final[name] = draft
        violations[name] = remaining
    return {"round1": round1, "final": final, "violations": violations}
