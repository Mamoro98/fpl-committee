from collections import Counter, defaultdict

from committee.fpl import Player
from committee.pack import player_score
from committee.schema import SquadProposal, TransferMove
from committee.validate import (
    MAX_PER_CLUB,
    SQUAD_COUNTS,
    XI_MAX,
    formation_from_xi,
    price_tenths,
)


def _state(ids: list[int], players_by_id: dict[int, Player]) -> tuple[dict[str, int], dict[int, int], int]:
    pos: dict[str, int] = defaultdict(int)
    club: dict[int, int] = defaultdict(int)
    cost = 0
    for pid in ids:
        player = players_by_id[pid]
        pos[player.position] += 1
        club[player.team_id] += 1
        cost += price_tenths(player)
    return pos, club, cost


def _structure_ok(
    player: Player,
    selected: list[int],
    players_by_id: dict[int, Player],
) -> bool:
    if player.id in selected:
        return False
    pos, club, _ = _state(selected, players_by_id)
    if pos[player.position] >= SQUAD_COUNTS[player.position]:
        return False
    if club[player.team_id] >= MAX_PER_CLUB:
        return False
    return True


def _fill_cheapest(
    selected: list[int],
    players: list[Player],
    players_by_id: dict[int, Player],
) -> list[int]:
    trial = list(selected)
    cheap = sorted(players, key=lambda p: (price_tenths(p), p.id))
    while len(trial) < 15:
        pos, _, _ = _state(trial, players_by_id)
        needed = [name for name, n in SQUAD_COUNTS.items() if pos[name] < n]
        if not needed:
            break
        pick = next(
            (p for p in cheap if p.position in needed and _structure_ok(p, trial, players_by_id)),
            None,
        )
        if pick is None:
            break
        trial.append(pick.id)
    return trial


def _can_afford(
    player: Player,
    selected: list[int],
    players: list[Player],
    players_by_id: dict[int, Player],
    budget_tenths: int,
) -> bool:
    if not _structure_ok(player, selected, players_by_id):
        return False
    filled = _fill_cheapest([*selected, player.id], players, players_by_id)
    if len(filled) < 15:
        return False
    return _state(filled, players_by_id)[2] <= budget_tenths


def complete_squad(
    locked_ids: list[int],
    players: list[Player],
    votes: Counter[int],
    budget_tenths: int,
) -> list[int]:
    players_by_id = {p.id: p for p in players}
    ranked = sorted(players, key=lambda p: (votes[p.id], player_score(p), -p.price), reverse=True)
    cheap = sorted(players, key=lambda p: (p.price, -player_score(p), p.id))

    selected: list[int] = []
    for pid in locked_ids:
        player = players_by_id.get(pid)
        if player is not None and _can_afford(player, selected, players, players_by_id, budget_tenths):
            selected.append(pid)

    def fill_from(pool: list[Player]) -> None:
        while len(selected) < 15:
            pos, _, _ = _state(selected, players_by_id)
            needed = [name for name, n in SQUAD_COUNTS.items() if pos[name] < n]
            if not needed:
                break
            pick = next(
                (
                    p
                    for p in pool
                    if p.position in needed
                    and _can_afford(p, selected, players, players_by_id, budget_tenths)
                ),
                None,
            )
            if pick is None:
                break
            selected.append(pick.id)

    fill_from(ranked)
    fill_from(cheap)

    for _ in range(20):
        if len(selected) == 15:
            break
        if not selected:
            fill_from(cheap)
            break
        worst = min(
            selected,
            key=lambda pid: (votes[pid], player_score(players_by_id[pid]), -price_tenths(players_by_id[pid])),
        )
        selected.remove(worst)
        fill_from(ranked)
        fill_from(cheap)

    return selected


def pick_xi(
    squad_ids: list[int],
    players_by_id: dict[int, Player],
    votes: Counter[int],
) -> list[int]:
    squad = [players_by_id[i] for i in squad_ids if i in players_by_id]

    def key(player: Player) -> tuple:
        return (votes[player.id], player_score(player))

    by_pos: dict[str, list[Player]] = defaultdict(list)
    for player in squad:
        by_pos[player.position].append(player)
    for position in by_pos:
        by_pos[position].sort(key=key, reverse=True)

    xi = [by_pos["GKP"][0]]
    for position, minimum in (("DEF", 3), ("MID", 2), ("FWD", 1)):
        xi.extend(by_pos[position][:minimum])
    rest: list[Player] = []
    for position in ("DEF", "MID", "FWD"):
        already = sum(1 for p in xi if p.position == position)
        rest.extend(by_pos[position][already : XI_MAX[position]])
    rest.sort(key=key, reverse=True)
    xi.extend(rest[: 11 - len(xi)])
    return [p.id for p in xi]


def pick_captains(
    xi_ids: list[int],
    players_by_id: dict[int, Player],
    captain_votes: Counter[int],
    squad_votes: Counter[int],
) -> tuple[int, int]:
    xi = [players_by_id[i] for i in xi_ids if i in players_by_id]
    ranked = sorted(
        xi,
        key=lambda p: (captain_votes[p.id], squad_votes[p.id], player_score(p)),
        reverse=True,
    )
    return ranked[0].id, ranked[1].id


def plan_transfers(
    current: list[int],
    desired: list[int],
    players_by_id: dict[int, Player],
    *,
    max_transfers: int = 3,
) -> tuple[list[int], list[TransferMove]]:
    current_set = set(current)
    desired_set = set(desired)
    if current_set == desired_set:
        return list(current), []

    outs = [pid for pid in current if pid not in desired_set]
    ins = [pid for pid in desired if pid not in current_set]
    moves: list[TransferMove] = []
    used_in: set[int] = set()
    for out_id in outs:
        out_player = players_by_id.get(out_id)
        if out_player is None:
            continue
        match = next(
            (
                in_id
                for in_id in ins
                if in_id not in used_in
                and in_id in players_by_id
                and players_by_id[in_id].position == out_player.position
            ),
            None,
        )
        if match is None:
            continue
        moves.append(TransferMove(out_id=out_id, in_id=match))
        used_in.add(match)
        if len(moves) >= max_transfers:
            break

    result = list(current)
    for move in moves:
        result.remove(move.out_id)
        result.append(move.in_id)
    return result, moves


def assemble_proposal(
    locked_ids: list[int],
    players: list[Player],
    votes: Counter[int],
    captain_votes: Counter[int],
    budget_tenths: int,
    *,
    current_squad: list[int] | None = None,
    free_transfers: int = 1,
) -> SquadProposal:
    players_by_id = {p.id: p for p in players}
    squad = complete_squad(locked_ids, players, votes, budget_tenths)
    transfers: list[TransferMove] = []
    hits = 0
    if current_squad is not None:
        squad, transfers = plan_transfers(current_squad, squad, players_by_id)
        hits = max(0, len(transfers) - free_transfers) * 4
    xi = pick_xi(squad, players_by_id, votes)
    captain, vice = pick_captains(xi, players_by_id, captain_votes, votes)
    xi_players = [players_by_id[i] for i in xi]
    locked_names = [players_by_id[i].name for i in locked_ids if i in players_by_id]
    return SquadProposal(
        squad=squad,
        xi=xi,
        captain=captain,
        vice_captain=vice,
        formation=formation_from_xi(xi_players),
        rationale="Vote-lock + greedy fill. Locked: " + (", ".join(locked_names) or "none"),
        transfers=transfers,
        hits=hits,
    )
