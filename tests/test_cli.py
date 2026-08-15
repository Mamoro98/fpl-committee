import json

import pytest

from committee import cli
from committee.ledger import Ledger

SUGGESTION = {
    "agent": "scout",
    "transfer_in": 1,
    "transfer_out": 2,
    "captain": 1,
    "bench_order": [],
    "rationale": "",
    "attacks": [],
}


def write_suggestions(tmp_path, gw=1):
    memos = tmp_path / "memos"
    memos.mkdir()
    (memos / f"gw{gw}_suggestions.json").write_text(json.dumps({"scout": SUGGESTION}))


def test_pick_records_choice(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    write_suggestions(tmp_path)

    cli.main(["pick", "scout", "--gw", "1"])

    ledger = Ledger.load(tmp_path / "ledger.json")
    entry = ledger.history()[0]
    assert entry["picked"] == "scout"
    assert entry["suggestion"]["transfer_in"] == 1
    assert entry["reward"] is None


def test_pick_without_memo_exits(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit):
        cli.main(["pick", "scout", "--gw", "1"])


def test_settle_applies_reward_and_ewma(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    write_suggestions(tmp_path)
    cli.main(["pick", "scout", "--gw", "1"])

    class FakeFpl:
        def get_gw_points(self, gw):
            return {1: 12}

    monkeypatch.setattr(cli, "FplClient", FakeFpl)
    cli.main(["settle", "--gw", "1"])

    ledger = Ledger.load(tmp_path / "ledger.json")
    expected = 0.85 * 17.0 + 0.15 * (10 + 12 + 12)
    assert ledger.scores()["scout"] == pytest.approx(expected)
    assert ledger.scores()["risk"] == 17.0


def test_memo_writes_files(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    class FakePlayer:
        def __init__(self, pid, name):
            self.id = pid
            self.name = name
            self.team = "Man City"
            self.position = "FWD"
            self.price = 15.5
            self.form = 5.0
            self.status = "a"

    class FakeFpl:
        def get_players(self):
            return [FakePlayer(1, "Haaland"), FakePlayer(2, "Palmer")]

    from committee.agents import Suggestion

    def fake_debate(client, context, ledger):
        s = Suggestion(**SUGGESTION)
        return {"round1": {"scout": s}, "final": {"scout": s}}

    monkeypatch.setattr(cli, "FplClient", FakeFpl)
    monkeypatch.setattr(cli, "LlmClient", lambda: object())
    monkeypatch.setattr(cli, "run_debate", fake_debate)

    cli.main(["memo", "--gw", "3"])

    assert (tmp_path / "memos" / "gw3.md").exists()
    saved = json.loads((tmp_path / "memos" / "gw3_suggestions.json").read_text())
    assert saved["scout"]["captain"] == 1
