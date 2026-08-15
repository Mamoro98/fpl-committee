from committee.fpl import Player
from committee.ledger import Ledger


def draft_text(d, lookup: dict[int, Player]) -> str:
    cost = round(sum(lookup[pid].price for pid in d.squad if pid in lookup), 1)
    xi = ", ".join(lookup[pid].name for pid in d.starting_xi if pid in lookup)
    captain = lookup[d.captain].name if d.captain in lookup else str(d.captain)
    return f"{d.formation}, {cost}m. XI: {xi}. Captain {captain}. {d.rationale}"


def draft_thread(result: dict, players: list[Player]) -> list[dict]:
    lookup = {p.id: p for p in players}
    thread = []
    for agent, d in result["round1"].items():
        thread.append({"round": 1, "agent": agent, "text": draft_text(d, lookup)})
    for agent, d in result["final"].items():
        thread.append(
            {
                "round": 2,
                "agent": agent,
                "attacks": list(d.attacks),
                "text": draft_text(d, lookup),
            }
        )
    return thread


def render_draft_memo(result: dict, ledger: Ledger, players: list[Player]) -> str:
    lookup = {p.id: p for p in players}

    def name(pid: int) -> str:
        p = lookup.get(pid)
        return f"{p.name} ({p.price}m)" if p else str(pid)

    lines = ["# Committee draft memo, GW1 squad", ""]
    for agent, d in result["final"].items():
        squad_cost = round(sum(lookup[pid].price for pid in d.squad if pid in lookup), 1)
        bench = [pid for pid in d.squad if pid not in d.starting_xi]
        lines += [
            f"## {agent}: {d.formation}, {squad_cost}m",
            "",
            f"- Starting XI: {', '.join(name(pid) for pid in d.starting_xi)}",
            f"- Bench: {', '.join(name(pid) for pid in bench)}",
            f"- Captain: {name(d.captain)}",
            f"- Why: {d.rationale}",
        ]
        if result["violations"].get(agent):
            lines.append(
                f"- **UNRESOLVED RULE BREAKS**: {'; '.join(result['violations'][agent])}"
            )
        lines.append("")

    attacks = [
        f"- **{agent}**: {attack}"
        for agent, d in result["final"].items()
        for attack in d.attacks
    ]
    if attacks:
        lines += ["## The disagreement", ""] + attacks + [""]

    lines += ["## Scoreboard", ""]
    for agent, score in sorted(ledger.scores().items(), key=lambda kv: -kv[1]):
        lines.append(f"- {agent}: {score:.2f}")
    lines.append("")
    return "\n".join(lines)
