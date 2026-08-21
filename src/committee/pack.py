from collections import defaultdict

from committee.fpl import Event, Fixture, Player, Team

TOP_N = {"GKP": 12, "DEF": 24, "MID": 28, "FWD": 16}
CHEAP_MAX_PRICE = 4.5
CHEAP_EXTRA = 6
AVAILABLE_STATUS = {"a", "d"}


def player_score(player: Player) -> float:
    ep = player.ep_next if player.ep_next is not None else player.form
    chance = player.chance_of_playing_next_round
    if chance is None:
        multiplier = 1.0 if player.status == "a" else 0.5
    else:
        multiplier = chance / 100
    if player.status in {"i", "s", "u"}:
        multiplier *= 0.1
    return ep * multiplier


def select_pack_players(
    players: list[Player],
    extra_ids: list[int] | None = None,
) -> list[Player]:
    extra = set(extra_ids or [])
    by_id = {p.id: p for p in players}
    chosen: dict[int, Player] = {}

    grouped: dict[str, list[Player]] = defaultdict(list)
    for player in players:
        grouped[player.position].append(player)

    for position, cap in TOP_N.items():
        ranked = sorted(grouped.get(position, []), key=player_score, reverse=True)
        available = [p for p in ranked if p.status in AVAILABLE_STATUS]
        for player in available[:cap]:
            chosen[player.id] = player
        cheap = [
            p
            for p in available
            if p.price <= CHEAP_MAX_PRICE and p.id not in chosen
        ]
        for player in cheap[:CHEAP_EXTRA]:
            chosen[player.id] = player

    for pid in extra:
        if pid in by_id:
            chosen[pid] = by_id[pid]

    order = {"GKP": 0, "DEF": 1, "MID": 2, "FWD": 3}
    return sorted(chosen.values(), key=lambda p: (order.get(p.position, 9), -player_score(p), p.id))


def _fixtures_for_team(
    team_id: int,
    fixtures: list[Fixture],
    teams: dict[int, Team],
    event_id: int,
    n: int = 3,
) -> str:
    upcoming = [
        f
        for f in fixtures
        if not f.finished
        and f.event is not None
        and f.event >= event_id
        and (f.team_h == team_id or f.team_a == team_id)
    ]
    upcoming.sort(key=lambda f: (f.event or 99, f.kickoff_time or ""))
    parts: list[str] = []
    for fixture in upcoming[:n]:
        home = fixture.team_h == team_id
        opp_id = fixture.team_a if home else fixture.team_h
        opp = teams.get(opp_id)
        opp_name = opp.short_name if opp else str(opp_id)
        fdr = fixture.team_h_difficulty if home else fixture.team_a_difficulty
        loc = "H" if home else "A"
        fdr_s = str(fdr) if fdr is not None else "?"
        parts.append(f"{opp_name}({loc}){fdr_s}")
    return ",".join(parts) if parts else "-"


def build_pack(
    players: list[Player],
    teams: list[Team],
    fixtures: list[Fixture],
    event: Event,
    extra_ids: list[int] | None = None,
) -> str:
    selected = select_pack_players(players, extra_ids=extra_ids)
    team_by_id = {t.id: t for t in teams}
    lines = [
        f"Gameweek {event.id} ({event.name}). Deadline: {event.deadline_time or 'unknown'}.",
        "Columns: id name pos club £ form ep_next sel% status next3",
    ]
    for player in selected:
        ep = player.ep_next if player.ep_next is not None else player.form
        chance = player.chance_of_playing_next_round
        status = player.status if chance is None else f"{player.status}/{chance}"
        nxt = _fixtures_for_team(player.team_id, fixtures, team_by_id, event.id)
        news = f" | {player.news}" if player.news and player.status != "a" else ""
        lines.append(
            f"{player.id} {player.name} {player.position} {player.team_short} "
            f"{player.price:.1f} {player.form:.1f} {ep:.1f} {player.selected_by_percent:.1f} "
            f"{status} {nxt}{news}"
        )

    lines.append("Teams (id short attH attA defH defA):")
    for team in teams:
        lines.append(
            f"{team.id} {team.short_name} {team.strength_attack_home} {team.strength_attack_away} "
            f"{team.strength_defence_home} {team.strength_defence_away}"
        )
    return "\n".join(lines)
