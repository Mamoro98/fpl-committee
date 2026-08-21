from collections import Counter

from committee.schema import SquadProposal, TransferMove
from committee.validate import legal_locks, validate_squad
from tests.helpers import LEGAL_SQUAD, LEGAL_XI, POOL_BY_ID


def _proposal(**overrides) -> SquadProposal:
    data = dict(
        squad=list(LEGAL_SQUAD),
        xi=list(LEGAL_XI),
        captain=13,
        vice_captain=8,
        formation="3-5-2",
        rationale="test",
    )
    data.update(overrides)
    return SquadProposal(**data)


def test_legal_squad_has_no_errors():
    assert validate_squad(_proposal(), POOL_BY_ID) == []


def test_rejects_over_budget():
    squad = list(LEGAL_SQUAD)
    squad[14] = 20
    errors = validate_squad(_proposal(squad=squad), POOL_BY_ID)
    assert any("budget" in e for e in errors)


def test_rejects_fourth_player_from_same_club():
    players = dict(POOL_BY_ID)
    extra = players[5].model_copy(update={"id": 99, "name": "White", "team_id": 1, "team_short": "ARS"})
    players[99] = extra
    squad = list(LEGAL_SQUAD)
    squad[4] = 99
    errors = validate_squad(_proposal(squad=squad), players)
    assert any("ARS" in e for e in errors)


def test_rejects_captain_not_in_xi():
    errors = validate_squad(_proposal(captain=2), POOL_BY_ID)
    assert any("captain" in e for e in errors)


def test_rejects_wrong_position_counts():
    squad = list(LEGAL_SQUAD)
    squad[1] = 24
    errors = validate_squad(
        _proposal(squad=squad, xi=[1, 3, 4, 5, 8, 9, 10, 11, 13, 14, 24]),
        POOL_BY_ID,
    )
    assert any("GKP" in e for e in errors)


def test_weekly_hits_and_transfer_consistency():
    current = list(LEGAL_SQUAD)
    proposal = _proposal(
        squad=list(LEGAL_SQUAD),
        transfers=[TransferMove(out_id=15, in_id=24)],
        hits=0,
    )
    errors = validate_squad(proposal, POOL_BY_ID, current_squad=current, free_transfers=1)
    assert any("does not match" in e for e in errors)

    new_squad = [i for i in LEGAL_SQUAD if i != 15] + [24]
    proposal = _proposal(squad=new_squad, transfers=[TransferMove(out_id=15, in_id=24)], hits=0)
    assert (
        validate_squad(
            proposal,
            POOL_BY_ID,
            budget_tenths=1005,
            current_squad=current,
            free_transfers=1,
        )
        == []
    )

    proposal = _proposal(
        squad=new_squad,
        transfers=[TransferMove(out_id=15, in_id=24)],
        hits=0,
    )
    errors = validate_squad(
        proposal,
        POOL_BY_ID,
        budget_tenths=1005,
        current_squad=current,
        free_transfers=0,
    )
    assert any("hits should be 4" in e for e in errors)


def test_legal_locks_caps_club_and_position():
    votes = Counter(
        {
            1: 3,
            3: 3,
            8: 3,
            2: 2,
            4: 2,
            5: 2,
            6: 2,
            7: 2,
            9: 2,
            10: 2,
            11: 2,
            12: 2,
            13: 2,
            14: 2,
            15: 2,
            99: 2,
        }
    )
    players = dict(POOL_BY_ID)
    players[99] = players[12].model_copy(
        update={"id": 99, "name": "Rice", "team_id": 1, "team_short": "ARS", "position": "MID"}
    )
    locked = legal_locks(votes, players)
    ars = [pid for pid in locked if players[pid].team_id == 1]
    assert len(ars) <= 3
    assert 1 in locked and 3 in locked and 8 in locked
    assert 99 not in locked
