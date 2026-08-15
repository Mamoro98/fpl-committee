from committee.ledger import Ledger


def _name(players: dict[int, str] | None, player_id: int) -> str:
    if players and player_id in players:
        return f"{players[player_id]} ({player_id})"
    return str(player_id)


def render_memo(
    result: dict, ledger: Ledger, gw: int, players: dict[int, str] | None = None
) -> str:
    lines = [f"# Committee memo, GW{gw}", ""]

    lines += ["## Recommendations", ""]
    lines += ["| Agent | Out | In | Captain | Rationale |", "|---|---|---|---|---|"]
    for agent, s in result["final"].items():
        lines.append(
            f"| {agent} | {_name(players, s.transfer_out)} | {_name(players, s.transfer_in)} "
            f"| {_name(players, s.captain)} | {s.rationale} |"
        )

    attacks = [
        f"- **{agent}**: {attack}"
        for agent, s in result["final"].items()
        for attack in s.attacks
    ]
    if attacks:
        lines += ["", "## The disagreement", ""] + attacks

    lines += ["", "## Scoreboard", ""]
    for agent, score in sorted(ledger.scores().items(), key=lambda kv: -kv[1]):
        lines.append(f"- {agent}: {score:.2f}")

    lines += ["", f"Pick with: `committee pick <agent> --gw {gw}`", ""]
    return "\n".join(lines)
