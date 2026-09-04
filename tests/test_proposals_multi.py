from committee.fpl import Player, Squad
from committee.web import build_proposals

NAMES = [
    ("Haaland", "FWD"), ("Isak", "FWD"), ("Watkins", "FWD"),
    ("Saka", "MID"), ("Palmer", "MID"), ("Salah", "MID"), ("Rice", "MID"), ("Rogers", "MID"),
    ("Gabriel", "DEF"), ("Timber", "DEF"), ("Senesi", "DEF"), ("Munoz", "DEF"), ("Romero", "DEF"),
    ("Raya", "GKP"), ("Sels", "GKP"),
]


def make_lookup():
    players = [
        Player(id=i + 1, name=n, team=f"Club{i % 8}", position=pos, price=6.0,
               form=0.0, status="a", ownership=20.0, total_points=0)
        for i, (n, pos) in enumerate(NAMES)
    ]
    lookup = {p.id: p for p in players}
    lookup[97] = Player(id=97, name="Cheap", team="A", position="FWD", price=5.0, form=1.0,
                        status="a", ownership=1.0, total_points=1)
    lookup[98] = Player(id=98, name="Pricey", team="B", position="MID", price=14.0, form=1.0,
                        status="a", ownership=1.0, total_points=1)
    return lookup


SLOTS = {14: 1, 9: 2, 10: 3, 11: 4, 12: 5, 4: 6, 5: 7, 6: 8, 7: 9, 1: 10, 2: 11,
         15: 12, 8: 13, 13: 14, 3: 15}


def test_two_transfers_cost_a_hit_and_over_budget_is_flagged(monkeypatch):
    monkeypatch.setenv("FREE_TRANSFERS", "1")
    squad = Squad(player_ids=list(range(1, 16)), bank=0.5, slots=SLOTS, captain=1)
    suggestion = {
        "agent": "scout",
        "transfers": [{"out": 2, "in": 97}, {"out": 4, "in": 98}],
        "captain": 1,
        "bench_order": [15, 8, 13, 3],
        "chip": None,
    }

    prop = build_proposals(squad, make_lookup(), {"scout": suggestion})["scout"]

    ids = {p["id"] for p in prop["players"]}
    assert 2 not in ids and 4 not in ids and 97 in ids and 98 in ids
    assert prop["hits"] == 1
    assert "1 hit, -4 pts" in prop["headline"]
    # 5.0 + 14.0 in vs 6.0 + 6.0 out + 0.5 bank: 6.5m over
    assert any(v.startswith("over budget by 6.5") for v in prop["violations"])


def test_wildcard_has_no_hits_and_headline_names_chip(monkeypatch):
    monkeypatch.setenv("FREE_TRANSFERS", "1")
    squad = Squad(player_ids=list(range(1, 16)), bank=20.0, slots=SLOTS, captain=1)
    suggestion = {
        "agent": "hawk",
        "transfers": [{"out": 2, "in": 97}, {"out": 4, "in": 98}],
        "captain": 1,
        "bench_order": [15, 8, 13, 3],
        "chip": "wildcard",
    }

    prop = build_proposals(squad, make_lookup(), {"hawk": suggestion})["hawk"]

    assert prop["hits"] == 0
    assert prop["violations"] == []
    assert "chip: wildcard" in prop["headline"]
    assert sum(1 for p in prop["players"] if p["incoming"]) == 2
