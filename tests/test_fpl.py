import json
from pathlib import Path

from committee.fpl import FplClient

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8-sig"))


def test_get_team_fixtures_builds_readable_lines(monkeypatch):
    client = FplClient()
    monkeypatch.setattr(
        client,
        "_fetch_bootstrap",
        lambda: {
            "teams": [
                {"id": 1, "name": "Arsenal", "short_name": "ARS"},
                {"id": 15, "name": "Man City", "short_name": "MCI"},
            ]
        },
    )
    monkeypatch.setattr(
        client,
        "_fetch_fixtures",
        lambda: [
            {"event": 3, "team_h": 15, "team_a": 1,
             "team_h_difficulty": 4, "team_a_difficulty": 5},
            {"event": None, "team_h": 1, "team_a": 15,
             "team_h_difficulty": 2, "team_a_difficulty": 2},
        ],
    )

    fixtures = client.get_team_fixtures()

    assert fixtures["Man City"] == ["GW3 ARS (H, diff 4)"]
    assert fixtures["Arsenal"] == ["GW3 MCI (A, diff 5)"]


def test_get_players_parses_bootstrap(monkeypatch):
    client = FplClient()
    monkeypatch.setattr(client, "_fetch_bootstrap", lambda: load_fixture("bootstrap_sample.json"))

    players = client.get_players()

    assert len(players) == 5
    haaland = next(p for p in players if p.name == "Haaland")
    assert haaland.price == 15.5
    assert haaland.team == "Man City"
    assert haaland.position == "FWD"
