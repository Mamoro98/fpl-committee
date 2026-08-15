from committee.fpl import Player
from committee.ledger import Ledger


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
