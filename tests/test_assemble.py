from collections import Counter

from committee.assemble import assemble_proposal, complete_squad, plan_transfers
from committee.schema import TransferMove
from committee.validate import validate_squad
from tests.helpers import LEGAL_SQUAD, POOL, POOL_BY_ID


def test_complete_squad_keeps_locks_and_fills_fifteen():
    votes = Counter({i: 3 for i in range(1, 11)})
    locked = list(range(1, 11))
    squad = complete_squad(locked, POOL, votes, 1000)
    assert locked == squad[:10]
    assert len(squad) == 15
    assert len(set(squad)) == 15


def test_complete_squad_drops_unaffordable_locks():
    expensive = [13, 8, 9, 14]
    votes = Counter({i: 3 for i in expensive})
    squad = complete_squad(expensive, POOL, votes, 1000)
    assert len(squad) == 15
    proposal = assemble_proposal(expensive, POOL, votes, Counter({13: 3}), 1000)
    assert validate_squad(proposal, POOL_BY_ID) == []


def test_assemble_proposal_is_legal():
    votes = Counter({i: 2 for i in LEGAL_SQUAD})
    captain_votes = Counter({13: 5})
    proposal = assemble_proposal(list(LEGAL_SQUAD), POOL, votes, captain_votes, 1000)
    assert validate_squad(proposal, POOL_BY_ID) == []
    assert proposal.captain == 13


def test_plan_transfers_pairs_same_position():
    current = list(LEGAL_SQUAD)
    desired = [i for i in LEGAL_SQUAD if i != 15] + [24]
    squad, moves = plan_transfers(current, desired, POOL_BY_ID, max_transfers=3)
    assert moves == [TransferMove(out_id=15, in_id=24)]
    assert 24 in squad
    assert 15 not in squad
