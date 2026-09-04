from committee.elite import (
    build_elite_snapshot,
    elite_block_for_gw,
    load_elite_snapshot,
    render_elite_block,
    save_elite_snapshot,
)
from committee.fpl import Player


def make_player(pid, name, ownership):
    return Player(id=pid, name=name, team="X", position="MID", price=5.0, form=1.0,
                  status="a", ownership=ownership, total_points=0)


class FakeFpl:
    def __init__(self):
        self.calls = 0

    def get_top_entries(self, n):
        return list(range(1, n + 1))

    def get_picks_raw(self, entry_id, gw):
        self.calls += 1
        if entry_id == 3:
            return None  # one manager's picks unavailable
        captain = 10 if entry_id % 2 else 20
        return {
            "picks": [
                {"element": 10, "position": 1, "is_captain": captain == 10},
                {"element": 20, "position": 2, "is_captain": captain == 20},
                {"element": 30, "position": 12, "is_captain": False},
            ]
        }


def test_snapshot_counts_ownership_starters_captains():
    snap = build_elite_snapshot(FakeFpl(), gw=2, n=5, log=lambda s: None)
    assert snap["managers"] == 4
    assert snap["ownership"] == {10: 4, 20: 4, 30: 4}
    assert snap["starters"] == {10: 4, 20: 4}
    assert snap["captains"] == {10: 2, 20: 2}


def test_snapshot_roundtrip_and_block(tmp_path):
    snap = build_elite_snapshot(FakeFpl(), gw=2, n=5, log=lambda s: None)
    save_elite_snapshot(snap, tmp_path)
    loaded = load_elite_snapshot(tmp_path, 2)
    assert loaded["ownership"][10] == 4  # keys back to ints

    players = [make_player(10, "Bruno", 40.0), make_player(20, "Pedro", 95.0),
               make_player(30, "Bench", 60.0), make_player(40, "Crowd", 50.0)]
    block = render_elite_block(loaded, players)

    assert "TOP 4 MANAGERS" in block
    assert "Bruno 100.0% (crowd 40.0%)" in block
    assert "Their captains last week: Bruno 50.0%, Pedro 50.0%" in block
    assert "They own far more than the crowd: Bruno 100.0% vs 40.0%" in block
    assert "Crowd 0.0% vs 50.0%" in block  # elite avoid a crowd favourite


def test_elite_block_uses_cache_on_second_call(tmp_path):
    fpl = FakeFpl()
    players = [make_player(10, "Bruno", 40.0)]
    elite_block_for_gw(fpl, 3, players, tmp_path, n=5, log=lambda s: None)
    first_calls = fpl.calls
    elite_block_for_gw(fpl, 3, players, tmp_path, n=5, log=lambda s: None)
    assert fpl.calls == first_calls  # cached, no refetch


def test_elite_block_empty_before_gw2(tmp_path):
    assert elite_block_for_gw(FakeFpl(), 1, [], tmp_path, n=5) == ""
