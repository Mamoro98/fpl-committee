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


def test_squad_endpoint_empty_state_invites_manual_entry(client, monkeypatch):
    monkeypatch.delenv("FPL_ENTRY_ID", raising=False)
    data = client.get("/api/squad").json()
    assert data["squad"] is None
    assert "Paste your team" in data["reason"]


def test_squad_endpoint_returns_players_with_xi_detail(client, monkeypatch):
    monkeypatch.setenv("FPL_ENTRY_ID", "12345")

    from committee.fpl import Player, Squad

    class FakeFpl:
        def get_current_gw(self):
            return 3

        def get_squad(self, entry_id, gw):
            assert (entry_id, gw) == (12345, 3)
            return Squad(player_ids=[1], bank=2.0, slots={1: 11}, captain=1)

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
    assert data["has_xi"] is True
    assert data["squad"][0]["slot"] == 11
    assert data["squad"][0]["is_captain"] is True


def make_players():
    from committee.fpl import Player

    names = [
        ("Haaland", "FWD"), ("Isak", "FWD"), ("Watkins", "FWD"),
        ("Saka", "MID"), ("Palmer", "MID"), ("Salah", "MID"), ("Rice", "MID"), ("Rogers", "MID"),
        ("Gabriel", "DEF"), ("Timber", "DEF"), ("Senesi", "DEF"), ("Munoz", "DEF"), ("Romero", "DEF"),
        ("Raya", "GKP"), ("Sels", "GKP"),
    ]
    return [
        Player(id=i + 1, name=n, team=f"Club{i % 8}", position=pos, price=6.0,
               form=0.0, status="a", ownership=20.0, total_points=0)
        for i, (n, pos) in enumerate(names)
    ]


def test_manual_squad_roundtrip(client, monkeypatch):
    monkeypatch.delenv("FPL_ENTRY_ID", raising=False)

    class FakeFpl:
        def get_players(self):
            return make_players()

        def get_current_gw(self):
            return None

    monkeypatch.setattr(web, "FplClient", FakeFpl)

    names = [p.name for p in make_players()]
    r = client.post("/api/squad/manual", json={"names": names, "bank": 1.5}).json()
    assert r["ok"] is True

    data = client.get("/api/squad").json()
    assert data["source"] == "manual"
    assert data["bank"] == 1.5
    assert len(data["squad"]) == 15


def test_manual_squad_reports_unmatched(client, monkeypatch):
    class FakeFpl:
        def get_players(self):
            return make_players()

    monkeypatch.setattr(web, "FplClient", FakeFpl)
    r = client.post(
        "/api/squad/manual", json={"names": ["Hааland-typo"], "bank": 0}
    ).json()
    assert r["ok"] is False
    assert r["unmatched"][0]["name"] == "Hааland-typo"


def test_manual_squad_requires_15(client, monkeypatch):
    class FakeFpl:
        def get_players(self):
            return make_players()

    monkeypatch.setattr(web, "FplClient", FakeFpl)
    r = client.post("/api/squad/manual", json={"names": ["Haaland"], "bank": 0}).json()
    assert r["ok"] is False
    assert "15 players" in r["detail"]


def test_memo_runs_as_background_job(client, monkeypatch):
    import time as _time

    from committee.agents import Suggestion

    class FakeFpl:
        def get_players(self):
            return make_players()

        def get_team_fixtures(self):
            return {}

    def fake_debate(llm_client, context, ledger):
        s = Suggestion(**SUGGESTION)
        return {"round1": {"scout": s}, "final": {"scout": s}}

    monkeypatch.setattr(web, "FplClient", FakeFpl)
    monkeypatch.setattr(web, "LlmClient", lambda: object())
    monkeypatch.setattr(web, "get_squad_for_gw", lambda fpl, gw: None)
    monkeypatch.setattr(web, "run_debate", fake_debate)

    job = client.post("/api/memo/1").json()
    assert "job_id" in job

    for _ in range(50):
        s = client.get(f"/api/job/{job['job_id']}").json()
        if s["state"] != "running":
            break
        _time.sleep(0.05)

    assert s["state"] == "done"
    assert "thread" in s["result"]
    assert s["result"]["agents"] == ["scout", "risk", "hawk"]


def test_job_failure_is_reported(client, monkeypatch):
    import time as _time

    class ExplodingFpl:
        def get_players(self):
            raise RuntimeError("fpl is down")

    monkeypatch.setattr(web, "FplClient", ExplodingFpl)
    monkeypatch.setattr(web, "LlmClient", lambda: object())

    job = client.post("/api/memo/1").json()
    for _ in range(50):
        s = client.get(f"/api/job/{job['job_id']}").json()
        if s["state"] != "running":
            break
        _time.sleep(0.05)

    assert s["state"] == "error"
    assert "fpl is down" in s["error"]


def test_unknown_job_404s(client):
    assert client.get("/api/job/nope").status_code == 404


def test_debates_archive_lists_and_serves_saved_debate(client, tmp_path):
    memos = tmp_path / "memos"
    memos.mkdir()
    (memos / "gw3.md").write_text("# Committee memo, GW3", encoding="utf-8")
    (memos / "gw3_thread.json").write_text(
        json.dumps([{"round": 1, "agent": "scout", "text": "OUT a, IN b"}]),
        encoding="utf-8",
    )
    (memos / "gw3_suggestions.json").write_text(json.dumps({"scout": SUGGESTION}))
    (memos / "draft.md").write_text("# Committee draft memo", encoding="utf-8")

    listing = client.get("/api/debates").json()["debates"]
    assert [d["name"] for d in listing] == ["draft", "gw3"]

    detail = client.get("/api/debates/gw3").json()
    assert detail["thread"][0]["agent"] == "scout"
    assert detail["can_pick"] is True
    assert "GW3" in detail["memo"]

    client.post("/api/pick/3/scout")
    assert client.get("/api/debates/gw3").json()["can_pick"] is False
    assert client.get("/api/debates").json()["debates"][1]["picked"] == "scout"


def test_build_proposals_applies_transfer_and_formation():
    from committee.fpl import Squad
    from committee.web import build_proposals

    players = make_players()
    lookup = {p.id: p for p in players}
    # squad: ids 1-15. XI slots 1-11, bench 12-15. FWDs are ids 1-3, MIDs 4-8, DEFs 9-13, GKPs 14-15.
    slots = {14: 1, 9: 2, 10: 3, 11: 4, 12: 5, 4: 6, 5: 7, 6: 8, 7: 9, 1: 10, 2: 11,
             15: 12, 8: 13, 13: 14, 3: 15}
    squad = Squad(player_ids=list(range(1, 16)), bank=1.0, slots=slots, captain=1)

    suggestion = {
        "agent": "scout",
        "transfer_out": 2,   # a FWD leaves the XI
        "transfer_in": 99,
        "captain": 1,
        "bench_order": [15, 8, 13, 3],
        "rationale": "",
        "attacks": [],
    }
    from committee.fpl import Player

    lookup[99] = Player(id=99, name="NewGuy", team="Spurs", position="MID", price=5.0,
                        form=3.0, status="a", ownership=5.0, total_points=20, team_code=6)

    proposals = build_proposals(squad, lookup, {"scout": suggestion})
    prop = proposals["scout"]

    ids = [p["id"] for p in prop["players"]]
    assert 2 not in ids and 99 in ids
    incoming = next(p for p in prop["players"] if p["id"] == 99)
    assert incoming["incoming"] is True
    assert incoming["slot"] == 1  # in the XI, not benched
    # XI was 4 DEF, 4 MID, 2 FWD; out a FWD, in a MID
    assert prop["formation"] == "4-5-1"
    assert prop["transfer_out"] == "Isak"
    assert prop["transfer_in"] == "NewGuy"


def test_debate_detail_rejects_bad_names(client):
    assert client.get("/api/debates/evil-path").status_code == 400
    assert client.get("/api/debates/gw99").status_code == 404


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
