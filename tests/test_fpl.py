import json
from pathlib import Path

from committee.fpl import FplClient

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8-sig"))


def test_get_players_parses_bootstrap(monkeypatch):
    client = FplClient()
    monkeypatch.setattr(client, "_fetch_bootstrap", lambda: load_fixture("bootstrap_sample.json"))

    players = client.get_players()

    assert len(players) == 5
    haaland = next(p for p in players if p.name == "Haaland")
    assert haaland.price == 15.5
    assert haaland.team == "Man City"
    assert haaland.position == "FWD"
