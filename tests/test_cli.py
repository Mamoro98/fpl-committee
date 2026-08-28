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


def make_player(pid, form, ownership, price=8.0, total_points=50):
    from committee.fpl import Player

    return Player(
        id=pid,
        name=f"P{pid}",
        team="Chelsea",
        position="MID",
        price=price,
        form=form,
        status="a",
        ownership=ownership,
        total_points=total_points,
    )


def test_build_context_includes_low_ownership_differentials():
    crowd = [make_player(pid, form=5.0, ownership=45.0) for pid in range(1, 26)]
    differential = make_player(99, form=4.0, ownership=3.2)

    context = cli.build_context(crowd + [differential], gw=2)

    assert "id=99" in context
    assert "owned=3.2%" in context


def test_build_context_with_squad_lists_it_and_constrains_transfer_out():
    from committee.fpl import Squad

    players = [make_player(pid, form=5.0, ownership=45.0) for pid in range(1, 30)]
    squad = Squad(player_ids=[1, 2, 3], bank=1.5)

    context = cli.build_context(players, gw=2, squad=squad)

    assert "MY CURRENT SQUAD" in context
    assert "transfer_out MUST be one of these ids" in context
    assert "bank 1.5m" in context


def test_build_context_without_squad_has_no_squad_block():
    players = [make_player(pid, form=5.0, ownership=45.0) for pid in range(1, 30)]
    context = cli.build_context(players, gw=1)
    assert "MY CURRENT SQUAD" not in context


def test_get_squad_for_gw1_returns_none(monkeypatch):
    monkeypatch.setenv("FPL_ENTRY_ID", "12345")
    assert cli.get_squad_for_gw(object(), gw=1) is None


def test_get_squad_fetches_previous_gw(monkeypatch):
    monkeypatch.setenv("FPL_ENTRY_ID", "12345")

    class FakeFpl:
        def get_squad(self, entry_id, gw):
            assert entry_id == 12345
            assert gw == 4
            return "squad-sentinel"

    assert cli.get_squad_for_gw(FakeFpl(), gw=5) == "squad-sentinel"


def test_build_context_includes_fixtures_and_news():
    players = [make_player(pid, form=5.0, ownership=45.0) for pid in range(1, 20)]
    players[0].news = "Hamstring injury - 75% chance of playing"
    fixtures = {"Chelsea": ["GW3 BOU (H, diff 2)", "GW4 MUN (A, diff 3)"]}

    context = cli.build_context(players, gw=3, fixtures=fixtures)

    assert "UPCOMING FIXTURES" in context
    assert "Chelsea: GW3 BOU (H, diff 2), GW4 MUN (A, diff 3)" in context
    assert "news=Hamstring injury" in context


def test_build_context_has_no_duplicate_players():
    players = [make_player(pid, form=5.0, ownership=5.0) for pid in range(1, 15)]
    context = cli.build_context(players, gw=2)
    assert context.count("id=1 ") == 1


def test_memo_writes_files(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("FPL_ENTRY_ID", raising=False)

    class FakePlayer:
        def __init__(self, pid, name):
            self.id = pid
            self.name = name
            self.team = "Man City"
            self.position = "FWD"
            self.price = 15.5
            self.form = 5.0
            self.status = "a"
            self.ownership = 50.0
            self.total_points = 100

    class FakeFpl:
        def get_players(self):
            return [FakePlayer(1, "Haaland"), FakePlayer(2, "Palmer")]

        def get_team_fixtures(self):
            return {}

    from committee.agents import Suggestion

    def fake_debate(client, context, ledger, histories=None):
        s = Suggestion(**SUGGESTION)
        return {"round1": {"scout": s}, "final": {"scout": s}}

    monkeypatch.setattr(cli, "FplClient", FakeFpl)
    monkeypatch.setattr(cli, "LlmClient", lambda: object())
    monkeypatch.setattr(cli, "run_debate", fake_debate)
    monkeypatch.setattr(cli, "get_squad_for_gw", lambda fpl, gw: None)

    cli.main(["memo", "--gw", "3"])

    assert (tmp_path / "memos" / "gw3.md").exists()
    saved = json.loads((tmp_path / "memos" / "gw3_suggestions.json").read_text())
    assert saved["scout"]["captain"] == 1
