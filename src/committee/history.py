import json
from pathlib import Path

import httpx

from committee.agents import AGENTS
from committee.ledger import Ledger


def build_agent_histories(
    fpl, ledger: Ledger, up_to_gw: int, memos_dir: Path, names: dict[int, str]
) -> dict[str, str]:
    """Per agent: a private track-record block of past advice and real outcomes."""
    picks = {e["gw"]: e for e in ledger.history()}
    scores = ledger.scores()
    per_agent: dict[str, list[str]] = {agent: [] for agent in AGENTS}

    for gw in range(1, up_to_gw):
        path = memos_dir / f"gw{gw}_suggestions.json"
        if not path.exists():
            continue
        suggestions = json.loads(path.read_text(encoding="utf-8"))
        try:
            points = fpl.get_gw_points(gw)
        except httpx.HTTPError:
            points = {}
        entry = picks.get(gw)

        for agent, s in suggestions.items():
            if agent not in per_agent:
                continue
            earned = points.get(s["transfer_in"], 0) + points.get(s["captain"], 0)
            picked = entry is not None and entry["picked"] == agent

            def name(pid: int) -> str:
                return names.get(pid, str(pid))

            per_agent[agent].append(
                f"GW{gw}: you advised OUT {name(s['transfer_out'])}, "
                f"IN {name(s['transfer_in'])}, captain {name(s['captain'])}. "
                f"That advice was worth {earned} real points. "
                + ("The manager PICKED you." if picked else "The manager did not pick you.")
            )

    return {
        agent: (
            "\n\nYOUR TRACK RECORD (real outcomes of your past advice; learn from "
            f"it; your reputation score is {scores.get(agent, 0):.2f}):\n"
            + "\n".join(lines)
            if lines
            else ""
        )
        for agent, lines in per_agent.items()
    }
