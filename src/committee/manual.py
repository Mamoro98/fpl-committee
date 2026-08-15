import json
from pathlib import Path

from committee.fpl import Player, Squad

MANUAL_PATH = Path("manual-squad.json")


def resolve_names(names: list[str], players: list[Player]):
    """Match typed names to players. Returns (resolved, unmatched)."""
    resolved: list[Player] = []
    unmatched: list[dict] = []
    for raw in names:
        name = raw.strip()
        if not name:
            continue
        lowered = name.lower()
        exact = [p for p in players if p.name.lower() == lowered]
        partial = [p for p in players if lowered in p.name.lower()]
        pick = None
        if len(exact) == 1:
            pick = exact[0]
        elif len(partial) == 1:
            pick = partial[0]
        if pick:
            resolved.append(pick)
        else:
            unmatched.append(
                {
                    "name": name,
                    "candidates": [
                        f"{p.name} ({p.team}, {p.position}, {p.price}m)"
                        for p in partial[:6]
                    ],
                }
            )
    return resolved, unmatched


def save_manual_squad(player_ids: list[int], bank: float) -> None:
    MANUAL_PATH.write_text(
        json.dumps({"player_ids": player_ids, "bank": bank}, indent=2),
        encoding="utf-8",
    )


def load_manual_squad() -> Squad | None:
    if not MANUAL_PATH.exists():
        return None
    data = json.loads(MANUAL_PATH.read_text(encoding="utf-8"))
    return Squad(player_ids=data["player_ids"], bank=data["bank"])
