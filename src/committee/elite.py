import json
from pathlib import Path

import httpx

from committee.fpl import Player

DEFAULT_N = 1000


def build_elite_snapshot(fpl, gw: int, n: int = DEFAULT_N, log=print) -> dict:
    """Count ownership, starters and captains across the top n managers' GW squads."""
    entries = fpl.get_top_entries(n)
    ownership: dict[int, int] = {}
    starters: dict[int, int] = {}
    captains: dict[int, int] = {}
    counted = 0
    for i, entry_id in enumerate(entries, start=1):
        try:
            picks = fpl.get_picks_raw(entry_id, gw)
        except httpx.HTTPError:
            picks = None
        if not picks:
            continue
        counted += 1
        for p in picks["picks"]:
            pid = p["element"]
            ownership[pid] = ownership.get(pid, 0) + 1
            if p["position"] <= 11:
                starters[pid] = starters.get(pid, 0) + 1
            if p["is_captain"]:
                captains[pid] = captains.get(pid, 0) + 1
        if i % 100 == 0:
            log(f"[elite] {i}/{len(entries)} squads read")
    return {
        "gw": gw,
        "managers": counted,
        "ownership": ownership,
        "starters": starters,
        "captains": captains,
    }


def elite_path(memos_dir: Path, gw: int) -> Path:
    return memos_dir / f"elite_gw{gw}.json"


def save_elite_snapshot(snapshot: dict, memos_dir: Path) -> None:
    memos_dir.mkdir(exist_ok=True)
    elite_path(memos_dir, snapshot["gw"]).write_text(
        json.dumps(snapshot), encoding="utf-8"
    )


def load_elite_snapshot(memos_dir: Path, gw: int) -> dict | None:
    path = elite_path(memos_dir, gw)
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    for key in ("ownership", "starters", "captains"):
        data[key] = {int(k): v for k, v in data[key].items()}
    return data


def elite_block_for_gw(fpl, gw: int, players: list[Player], memos_dir: Path, n: int, log=print) -> str:
    """Block describing the elite after GW gw-1, built once per GW and cached."""
    last_gw = gw - 1
    if last_gw < 1:
        return ""
    snapshot = load_elite_snapshot(memos_dir, last_gw)
    if snapshot is None:
        log(f"[elite] building top-{n} snapshot for GW{last_gw}, a few minutes...")
        snapshot = build_elite_snapshot(fpl, last_gw, n, log=log)
        save_elite_snapshot(snapshot, memos_dir)
    return render_elite_block(snapshot, players)


def render_elite_block(snapshot: dict, players: list[Player]) -> str:
    n = snapshot["managers"]
    if n == 0:
        return ""
    lookup = {p.id: p for p in players}

    def pct(count: int) -> float:
        return round(100 * count / n, 1)

    def name(pid: int) -> str:
        return lookup[pid].name if pid in lookup else str(pid)

    def crowd(pid: int) -> float:
        return lookup[pid].ownership if pid in lookup else 0.0

    owned = sorted(snapshot["ownership"].items(), key=lambda kv: -kv[1])
    most_owned = ", ".join(
        f"{name(pid)} {pct(c)}% (crowd {crowd(pid)}%)" for pid, c in owned[:10]
    )

    caps = sorted(snapshot["captains"].items(), key=lambda kv: -kv[1])[:5]
    captains = ", ".join(f"{name(pid)} {pct(c)}%" for pid, c in caps)

    gaps = sorted(
        ((pid, pct(c) - crowd(pid)) for pid, c in snapshot["ownership"].items()),
        key=lambda kv: -kv[1],
    )
    over = ", ".join(
        f"{name(pid)} {pct(snapshot['ownership'][pid])}% vs {crowd(pid)}%"
        for pid, gap in gaps[:6]
        if gap > 5
    )
    avoided = sorted(
        (
            (pid, p.ownership - pct(snapshot["ownership"].get(pid, 0)))
            for pid, p in lookup.items()
            if p.ownership >= 10
        ),
        key=lambda kv: -kv[1],
    )
    avoid = ", ".join(
        f"{name(pid)} {pct(snapshot['ownership'].get(pid, 0))}% vs {crowd(pid)}%"
        for pid, gap in avoided[:5]
        if gap > 5
    )

    header = (
        f"\n\nTOP {n} MANAGERS OVERALL (their squads after GW{snapshot['gw']}; "
        "'crowd' = ownership across all managers). Mimicking them is safe, "
        "differing from them is how ranks move:"
    )
    lines = [
        header,
        f"Most owned: {most_owned}",
        f"Their captains last week: {captains}",
    ]
    if over:
        lines.append(f"They own far more than the crowd: {over}")
    if avoid:
        lines.append(f"They avoid what the crowd holds: {avoid}")
    return "\n".join(lines)
