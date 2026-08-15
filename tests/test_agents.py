import json

import pytest

from committee.agents import AgentResponseError, run_agent

GOOD = json.dumps(
    {
        "transfer_in": 1,
        "transfer_out": 2,
        "captain": 1,
        "bench_order": [3, 4],
        "rationale": "form",
    }
)


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def complete(self, model, system, user):
        self.calls += 1
        return self.responses.pop(0)


def test_run_agent_parses_valid_json():
    client = FakeClient([GOOD])
    suggestion = run_agent("scout", client, "context")
    assert suggestion.agent == "scout"
    assert suggestion.transfer_in == 1
    assert suggestion.attacks == []


def test_run_agent_extracts_json_from_prose():
    client = FakeClient([f"Here is my pick:\n{GOOD}\nGood luck."])
    suggestion = run_agent("risk", client, "context")
    assert suggestion.captain == 1


def test_run_agent_retries_bad_json_then_succeeds():
    client = FakeClient(["not json at all", GOOD])
    suggestion = run_agent("scout", client, "context")
    assert client.calls == 2
    assert suggestion.transfer_out == 2


def test_run_agent_fails_after_two_bad_responses():
    client = FakeClient(["nope", "still nope"])
    with pytest.raises(AgentResponseError):
        run_agent("hawk", client, "context")
