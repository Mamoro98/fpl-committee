import pytest

from committee.ledger import Ledger


def test_new_ledger_starts_all_agents_at_prior():
    ledger = Ledger.new(agents=["scout", "risk", "hawk"], prior=17.0)
    assert ledger.scores() == {"scout": 17.0, "risk": 17.0, "hawk": 17.0}


def test_settle_moves_picked_agent_by_ewma():
    ledger = Ledger.new(agents=["scout", "risk", "hawk"], prior=17.0)
    ledger.record_pick(gw=1, agent="scout")

    ledger.settle(gw=1, reward=30.0)

    assert ledger.scores()["scout"] == pytest.approx(0.85 * 17.0 + 0.15 * 30.0)
    assert ledger.scores()["risk"] == 17.0
