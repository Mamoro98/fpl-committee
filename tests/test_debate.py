import json

from committee.agents import AGENTS
from committee.debate import run_debate
from committee.ledger import Ledger
from committee.memo import render_memo

GOOD = json.dumps(
    {
        "transfer_in": 1,
        "transfer_out": 2,
        "captain": 1,
        "bench_order": [3],
        "rationale": "steady points",
        "attacks": ["rival ignores rotation"],
    }
)


class RecordingClient:
    def __init__(self):
        self.prompts = []

    def complete(self, model, system, user):
        self.prompts.append(user)
        return GOOD


def make_result_and_ledger():
    client = RecordingClient()
    ledger = Ledger.new(agents=AGENTS, prior=17.0)
    result = run_debate(client, "base context", ledger)
    return client, ledger, result


def test_debate_runs_two_rounds_for_all_agents():
    client, _, result = make_result_and_ledger()
    assert set(result["final"]) == set(AGENTS)
    assert len(client.prompts) == 6


def test_round2_prompts_contain_rivals_and_scoreboard():
    client, _, _ = make_result_and_ledger()
    round2 = client.prompts[3:]
    assert all("ROUND 2" in p for p in round2)
    assert all("17.0" in p for p in round2)
    assert all("rationale" in p for p in round2)


def test_memo_contains_agents_scoreboard_and_attacks():
    _, ledger, result = make_result_and_ledger()
    memo = render_memo(result, ledger, gw=1)
    for agent in AGENTS:
        assert agent in memo
    assert "## Scoreboard" in memo
    assert "rival ignores rotation" in memo
    assert "committee pick" in memo


def test_debate_thread_orders_rounds_and_carries_attacks():
    from committee.memo import debate_thread

    _, _, result = make_result_and_ledger()
    thread = debate_thread(result, players={1: "Haaland", 2: "Palmer"})

    assert [t["round"] for t in thread] == [1, 1, 1, 2, 2, 2]
    assert "Haaland" in thread[0]["text"]
    assert thread[3]["attacks"] == ["rival ignores rotation"]
    assert "attacks" not in thread[0]


def test_memo_resolves_player_names_when_given():
    _, ledger, result = make_result_and_ledger()
    memo = render_memo(result, ledger, gw=1, players={1: "Haaland", 2: "Palmer"})
    assert "Haaland (1)" in memo
    assert "Palmer (2)" in memo
