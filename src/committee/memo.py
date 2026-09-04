from committee.ledger import Ledger


def suggestion_text(s, players: dict[int, str] | None = None) -> str:
    moves = ", ".join(
        f"OUT {_name(players, t.out)} IN {_name(players, t.in_)}" for t in s.transfers
    ) or "no transfer"
    chip = f" Chip: {s.chip}." if s.chip else ""
    hits = f" ({len(s.transfers)} transfers)" if len(s.transfers) > 1 else ""
    return f"{moves}{hits}, captain {_name(players, s.captain)}.{chip} {s.rationale}"


def debate_thread(result: dict, players: dict[int, str] | None = None) -> list[dict]:
    thread = []
    for agent, s in result["round1"].items():
        thread.append({"round": 1, "agent": agent, "text": suggestion_text(s, players)})
    for agent, s in result["final"].items():
        thread.append(
            {
                "round": 2,
                "agent": agent,
                "attacks": list(s.attacks),
                "text": suggestion_text(s, players),
            }
        )
    return thread


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
        outs = ", ".join(_name(players, t.out) for t in s.transfers) or "none"
        ins = ", ".join(_name(players, t.in_) for t in s.transfers) or "none"
        chip = f" [{s.chip}]" if s.chip else ""
        lines.append(
            f"| {agent} | {outs} | {ins}{chip} | {_name(players, s.captain)} | {s.rationale} |"
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
