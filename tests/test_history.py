import json

from committee.debate import run_debate
from committee.history import build_agent_histories
from committee.ledger import Ledger

SUGGESTIONS_GW2 = {
    "scout": {"transfer_out": 5, "transfer_in": 7, "captain": 7,
              "bench_order": [], "rationale": "", "attacks": [], "agent": "scout"},
    "hawk": {"transfer_out": 5, "transfer_in": 9, "captain": 3,
             "bench_order": [], "rationale": "", "attacks": [], "agent": "hawk"},
}


class FakeFpl:
    def get_gw_points(self, gw):
        return {7: 2, 9: 12, 3: 8}


def make_ledger():
    ledger = Ledger.new(agents=["scout", "risk", "hawk"], prior=17.0)
    ledger.record_pick(gw=2, agent="hawk", suggestion=SUGGESTIONS_GW2["hawk"])
    ledger.settle(gw=2, reward=30.0)
    return ledger


def test_histories_report_outcomes_and_picks(tmp_path):
    memos = tmp_path / "memos"
    memos.mkdir()
    (memos / "gw2_suggestions.json").write_text(json.dumps(SUGGESTIONS_GW2))

    names = {5: "James", 7: "Gakpo", 9: "Mendy", 3: "Pedro"}
    histories = build_agent_histories(FakeFpl(), make_ledger(), 3, memos, names)

    assert "IN Gakpo" in histories["scout"]
    assert "worth 4 real points" in histories["scout"]  # 2 + 2, captain == transfer_in
    assert "did not pick you" in histories["scout"]
    assert "worth 20 real points" in histories["hawk"]  # 12 + 8
    assert "PICKED you" in histories["hawk"]
    assert histories["risk"] == ""


def test_debate_injects_history_only_into_own_context():
    prompts = {}

    class RecordingClient:
        def complete(self, model, system, user):
            prompts.setdefault(model, []).append(user)
            return json.dumps(
                {"transfer_in": 1, "transfer_out": 2, "captain": 1,
                 "bench_order": [], "rationale": "x"}
            )

    ledger = Ledger.new(agents=["scout", "risk", "hawk"], prior=17.0)
    histories = {"scout": "\n\nYOUR TRACK RECORD: GW2 test marker"}
    run_debate(RecordingClient(), "base", ledger, histories=histories)

    all_prompts = [p for plist in prompts.values() for p in plist]
    scout_prompts = [p for p in all_prompts if "test marker" in p]
    assert len(scout_prompts) == 2  # scout round 1 and round 2, nobody else
