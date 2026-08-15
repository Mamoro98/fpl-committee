import json

import pytest
from fastapi.testclient import TestClient

from committee import web
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


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return TestClient(web.app)


def test_index_serves_dashboard(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "FPL" in response.text


def test_scoreboard_starts_fresh(client):
    data = client.get("/api/scoreboard").json()
    assert data["scores"] == {"scout": 17.0, "risk": 17.0, "hawk": 17.0}
    assert data["history"] == []


def test_pick_without_memo_404s(client):
    assert client.post("/api/pick/1/scout").status_code == 404


def test_pick_records_and_double_pick_409s(client, tmp_path):
    memos = tmp_path / "memos"
    memos.mkdir()
    (memos / "gw1_suggestions.json").write_text(json.dumps({"scout": SUGGESTION}))

    assert client.post("/api/pick/1/scout").status_code == 200
    assert client.post("/api/pick/1/scout").status_code == 409

    ledger = Ledger.load(tmp_path / "ledger.json")
    assert ledger.history()[0]["picked"] == "scout"


def test_squad_endpoint_without_entry_id(client, monkeypatch):
    monkeypatch.delenv("FPL_ENTRY_ID", raising=False)
    data = client.get("/api/squad").json()
    assert data["squad"] is None
    assert "FPL_ENTRY_ID" in data["reason"]


def test_squad_endpoint_preseason(client, monkeypatch):
    monkeypatch.setenv("FPL_ENTRY_ID", "12345")

    class FakeFpl:
        def get_current_gw(self):
            return None

    monkeypatch.setattr(web, "FplClient", FakeFpl)
    data = client.get("/api/squad").json()
    assert data["squad"] is None
    assert "season" in data["reason"]


def test_squad_endpoint_returns_players(client, monkeypatch):
    monkeypatch.setenv("FPL_ENTRY_ID", "12345")

    from committee.fpl import Player, Squad

    class FakeFpl:
        def get_current_gw(self):
            return 3

        def get_squad(self, entry_id, gw):
            assert (entry_id, gw) == (12345, 3)
            return Squad(player_ids=[1], bank=2.0)

        def get_players(self):
            return [
                Player(
                    id=1,
                    name="Haaland",
                    team="Man City",
                    position="FWD",
                    price=15.5,
                    form=0.0,
                    status="a",
                    ownership=60.0,
                    total_points=0,
                )
            ]

    monkeypatch.setattr(web, "FplClient", FakeFpl)
    data = client.get("/api/squad").json()
    assert data["gw"] == 3
    assert data["bank"] == 2.0
    assert data["squad"][0]["name"] == "Haaland"


def test_settle_applies_reward(client, tmp_path, monkeypatch):
    memos = tmp_path / "memos"
    memos.mkdir()
    (memos / "gw1_suggestions.json").write_text(json.dumps({"scout": SUGGESTION}))
    client.post("/api/pick/1/scout")

    class FakeFpl:
        def get_gw_points(self, gw):
            return {1: 12}

    monkeypatch.setattr(web, "FplClient", FakeFpl)
    data = client.post("/api/settle/1").json()
    assert data["reward"] == 34.0
    assert data["scores"]["scout"] == pytest.approx(0.85 * 17.0 + 0.15 * 34.0)

    assert client.post("/api/settle/1").status_code == 409
