import json

from committee.draft import (
    SquadDraft,
    build_draft_context,
    run_draft_debate,
    validate_draft,
)
from committee.fpl import Player
from committee.ledger import Ledger


def make_player(pid, position, price=5.0, team=None, ownership=20.0):
    return Player(
        id=pid,
        name=f"P{pid}",
        team=team or f"Club{pid % 10}",
        position=position,
        price=price,
        form=0.0,
        status="a",
        ownership=ownership,
        total_points=0,
    )


def make_pool():
    players = []
    pid = 1
    for position, count in [("GKP", 4), ("DEF", 10), ("MID", 10), ("FWD", 6)]:
        for _ in range(count):
            players.append(make_player(pid, position))
            pid += 1
    return players


def legal_draft(agent="scout"):
    # ids: GKP 1-4, DEF 5-14, MID 15-24, FWD 25-30
    squad = [1, 2, 5, 6, 7, 8, 9, 15, 16, 17, 18, 19, 25, 26, 27]
    starting_xi = [1, 5, 6, 7, 8, 15, 16, 17, 18, 25, 26]
    return SquadDraft(
        agent=agent,
        formation="4-4-2",
        squad=squad,
        starting_xi=starting_xi,
        captain=25,
        rationale="balanced",
    )


def test_legal_draft_passes():
    assert validate_draft(legal_draft(), make_pool()) == []


def test_budget_violation_caught():
    pool = [
        make_player(p.id, p.position, price=10.0, team=p.team) for p in make_pool()
    ]
    violations = validate_draft(legal_draft(), pool)
    assert any("budget exceeded" in v for v in violations)


def test_position_quota_violation_caught():
    draft = legal_draft()
    draft.squad[1] = 28  # swap second GKP for a FWD
    draft.starting_xi = [pid for pid in draft.starting_xi]
    violations = validate_draft(draft, make_pool())
    assert any("need 2 GKP" in v for v in violations)


def test_club_limit_violation_caught():
    pool = [make_player(p.id, p.position, team="Arsenal") for p in make_pool()]
    violations = validate_draft(legal_draft(), pool)
    assert any("max 3" in v for v in violations)


def test_formation_mismatch_caught():
    draft = legal_draft()
    draft.formation = "3-5-2"
    violations = validate_draft(draft, make_pool())
    assert any("formation 3-5-2 needs" in v for v in violations)


def test_captain_outside_xi_caught():
    draft = legal_draft()
    draft.captain = 27
    violations = validate_draft(draft, make_pool())
    assert any("captain" in v for v in violations)


def test_draft_context_lists_rules_and_format():
    context = build_draft_context(make_pool())
    assert "budget 100.0m" in context
    assert "starting_xi" in context


class FakeClient:
    def __init__(self, bad_first=False):
        self.bad_first = bad_first
        self.calls = 0

    def complete(self, model, system, user):
        self.calls += 1
        draft = legal_draft().model_dump()
        if self.bad_first and self.calls == 1:
            draft["captain"] = 27  # rule break, forces the retry path
        return json.dumps(draft)


def test_draft_debate_retries_on_violation():
    client = FakeClient(bad_first=True)
    ledger = Ledger.new(agents=["scout", "risk", "hawk"], prior=17.0)
    result = run_draft_debate(client, make_pool(), ledger)
    assert result["violations"] == {"scout": [], "risk": [], "hawk": []}
    # 3 agents x 2 rounds = 6 minimum, +1 for scout's round 1 retry
    assert client.calls == 7
