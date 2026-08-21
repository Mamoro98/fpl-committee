from collections import Counter, defaultdict

from committee.fpl import Player
from committee.schema import SquadProposal, TransferMove

SQUAD_COUNTS = {"GKP": 2, "DEF": 5, "MID": 5, "FWD": 3}
XI_MIN = {"GKP": 1, "DEF": 3, "MID": 2, "FWD": 1}
XI_MAX = {"GKP": 1, "DEF": 5, "MID": 5, "FWD": 3}
BUDGET_TENTHS = 1000
MAX_PER_CLUB = 3
VALID_CHIPS = {None, "wildcard", "freehit", "bboost", "3xc"}


def price_tenths(player: Player) -> int:
    return round(player.price * 10)


def formation_from_xi(xi: list[Player]) -> str:
    counts = Counter(p.position for p in xi)
    return f"{counts.get('DEF', 0)}-{counts.get('MID', 0)}-{counts.get('FWD', 0)}"


def budget_used(players: list[Player]) -> float:
    return sum(price_tenths(p) for p in players) / 10


def apply_transfers(squad_ids: list[int], transfers: list[TransferMove]) -> list[int]:
    result = list(squad_ids)
    for move in transfers:
        if move.out_id not in result:
            raise ValueError(f"transfer out {move.out_id} is not in the current squad")
        if move.in_id in result:
            raise ValueError(f"transfer in {move.in_id} is already in the squad")
        result.remove(move.out_id)
        result.append(move.in_id)
    return result


def validate_squad(
    proposal: SquadProposal,
    players_by_id: dict[int, Player],
    *,
    budget_tenths: int = BUDGET_TENTHS,
    current_squad: list[int] | None = None,
    free_transfers: int = 1,
) -> list[str]:
    errors: list[str] = []
    unknown = [i for i in proposal.squad if i not in players_by_id]
    if unknown:
        errors.append(f"unknown player ids: {unknown}")
        return errors

    if len(proposal.squad) != 15:
        errors.append(f"squad must have 15 players, got {len(proposal.squad)}")
    if len(set(proposal.squad)) != len(proposal.squad):
        errors.append("squad contains duplicate ids")

    squad = [players_by_id[i] for i in proposal.squad if i in players_by_id]
    by_pos = defaultdict(int)
    by_club = defaultdict(int)
    for player in squad:
        by_pos[player.position] += 1
        by_club[player.team_id] += 1

    for position, needed in SQUAD_COUNTS.items():
        got = by_pos.get(position, 0)
        if got != needed:
            errors.append(f"need {needed} {position}, got {got}")

    for team_id, count in by_club.items():
        if count > MAX_PER_CLUB:
            name = next(p.team_short for p in squad if p.team_id == team_id)
            errors.append(f"{name} has {count} players (max {MAX_PER_CLUB})")

    used = sum(price_tenths(p) for p in squad)
    if used > budget_tenths:
        errors.append(f"budget {used / 10:.1f} exceeds {budget_tenths / 10:.1f}")

    if len(proposal.xi) != 11:
        errors.append(f"XI must have 11 players, got {len(proposal.xi)}")
    if len(set(proposal.xi)) != len(proposal.xi):
        errors.append("XI contains duplicate ids")

    missing_xi = [i for i in proposal.xi if i not in proposal.squad]
    if missing_xi:
        errors.append(f"XI players not in squad: {missing_xi}")

    xi_players = [players_by_id[i] for i in proposal.xi if i in players_by_id]
    xi_pos = Counter(p.position for p in xi_players)
    for position, minimum in XI_MIN.items():
        if xi_pos.get(position, 0) < minimum:
            errors.append(f"XI needs at least {minimum} {position}")
    for position, maximum in XI_MAX.items():
        if xi_pos.get(position, 0) > maximum:
            errors.append(f"XI can have at most {maximum} {position}")

    if proposal.captain not in proposal.xi:
        errors.append("captain must be in the XI")
    if proposal.vice_captain not in proposal.xi:
        errors.append("vice-captain must be in the XI")
    if proposal.captain == proposal.vice_captain:
        errors.append("captain and vice-captain must differ")

    if proposal.chip not in VALID_CHIPS:
        errors.append(f"unknown chip {proposal.chip!r}")

    if current_squad is not None:
        try:
            applied = apply_transfers(current_squad, proposal.transfers)
        except ValueError as exc:
            errors.append(str(exc))
            applied = None
        if applied is not None and sorted(applied) != sorted(proposal.squad):
            errors.append("squad does not match current squad after transfers")
        wildcard = proposal.chip in {"wildcard", "freehit"}
        expected_hits = 0 if wildcard else max(0, len(proposal.transfers) - free_transfers) * 4
        if proposal.hits != expected_hits:
            errors.append(f"hits should be {expected_hits}, got {proposal.hits}")

    return errors


def legal_locks(
    vote_counts: Counter[int],
    players_by_id: dict[int, Player],
    min_votes: int = 2,
) -> list[int]:
    selected: list[int] = []
    pos_count: dict[str, int] = defaultdict(int)
    club_count: dict[int, int] = defaultdict(int)
    ranked = [pid for pid, n in vote_counts.most_common() if n >= min_votes]
    for pid in ranked:
        player = players_by_id.get(pid)
        if player is None:
            continue
        if pos_count[player.position] >= SQUAD_COUNTS[player.position]:
            continue
        if club_count[player.team_id] >= MAX_PER_CLUB:
            continue
        selected.append(pid)
        pos_count[player.position] += 1
        club_count[player.team_id] += 1
    return selected
