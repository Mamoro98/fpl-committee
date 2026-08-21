import json
from pathlib import Path

from committee.fpl import FplClient

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict | list:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8-sig"))


def test_get_players_parses_bootstrap(monkeypatch):
    client = FplClient()
    monkeypatch.setattr(client, "_fetch_bootstrap", lambda: load_fixture("bootstrap_sample.json"))

    players = client.get_players()

    assert len(players) == 5
    haaland = next(p for p in players if p.name == "Haaland")
    assert haaland.price == 15.5
    assert haaland.team == "Man City"
    assert haaland.team_short == "MCI"
    assert haaland.team_id == 15
    assert haaland.position == "FWD"
    assert haaland.ep_next == 7.8
    assert haaland.selected_by_percent == 71.2
    assert haaland.form == 8.0


def test_get_target_event_prefers_next_when_no_current(monkeypatch):
    client = FplClient()
    monkeypatch.setattr(client, "_fetch_bootstrap", lambda: load_fixture("bootstrap_sample.json"))
    event = client.get_target_event()
    assert event.id == 1
    assert event.is_next


def test_get_teams_includes_strength(monkeypatch):
    client = FplClient()
    monkeypatch.setattr(client, "_fetch_bootstrap", lambda: load_fixture("bootstrap_sample.json"))
    arsenal = next(t for t in client.get_teams() if t.short_name == "ARS")
    assert arsenal.strength_attack_home == 1350


def test_get_fixtures(monkeypatch):
    client = FplClient()
    monkeypatch.setattr(client, "_fetch_fixtures", lambda: load_fixture("fixtures_sample.json"))
    fixtures = client.get_fixtures()
    assert fixtures[0].team_h == 1
    assert fixtures[0].team_a_difficulty == 2


def test_get_entry_and_picks(monkeypatch):
    client = FplClient()

    def fake_get(url: str):
        if "event" in url:
            return load_fixture("picks_sample.json")
        return load_fixture("entry_sample.json")

    monkeypatch.setattr(client, "_get_json", fake_get)
    entry = client.get_entry(99, free_transfers=2)
    assert entry.name == "Test XI"
    assert entry.bank == 1.5
    assert entry.squad_ids == [12, 154, 411, 379]
    assert entry.xi_ids == [12, 154, 411]
    assert entry.captain_id == 411
    assert entry.vice_captain_id == 154
    assert entry.free_transfers == 2
