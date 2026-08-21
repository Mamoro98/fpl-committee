from committee.fpl import Fixture
from committee.pack import build_pack, select_pack_players
from tests.helpers import GW1, POOL, TEAMS


def test_select_pack_excludes_unavailable_unless_extra():
    injured = POOL[0].model_copy(update={"id": 50, "status": "u", "name": "Injured"})
    players = list(POOL) + [injured]
    selected = select_pack_players(players)
    assert 50 not in {p.id for p in selected}

    selected = select_pack_players(players, extra_ids=[50])
    assert 50 in {p.id for p in selected}


def test_build_pack_includes_fixtures_and_ids():
    fixtures = [
        Fixture(event=1, team_h=1, team_a=9, team_h_difficulty=4, team_a_difficulty=2, finished=False),
    ]
    text = build_pack(POOL, TEAMS, fixtures, GW1)
    assert "Gameweek 1" in text
    assert "13 Haaland" in text
    assert "MCI(H)4" in text or "MCI(H)" in text
    assert "ARS att" not in text
    assert "1 ARS" in text
