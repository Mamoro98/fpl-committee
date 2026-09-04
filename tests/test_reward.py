from committee.reward import compute_reward

POINTS = {10: 8, 20: 2, 30: 6, 40: 5, 99: 12}


def test_single_transfer_no_hit():
    s = {"transfers": [{"out": 1, "in": 10}], "captain": 99, "chip": None, "bench_order": []}
    reward, b = compute_reward(s, POINTS, free_transfers=1)
    assert reward == 10 + 8 + 12
    assert b["hits"] == 0


def test_two_transfers_one_free_costs_a_hit():
    s = {"transfers": [{"out": 1, "in": 10}, {"out": 2, "in": 20}], "captain": 99, "chip": None}
    reward, b = compute_reward(s, POINTS, free_transfers=1)
    assert b["hits"] == 1
    assert reward == 10 + 8 + 2 + 12 - 4


def test_wildcard_makes_transfers_free():
    s = {
        "transfers": [{"out": 1, "in": 10}, {"out": 2, "in": 20}, {"out": 3, "in": 30}],
        "captain": 99,
        "chip": "wildcard",
    }
    reward, b = compute_reward(s, POINTS, free_transfers=1)
    assert b["hits"] == 0
    assert reward == 10 + 16 + 12


def test_triple_captain_doubles_captain_points_in_reward():
    s = {"transfers": [], "captain": 99, "chip": "3xc"}
    reward, _ = compute_reward(s, POINTS)
    assert reward == 10 + 24


def test_bench_boost_adds_bench_points():
    s = {"transfers": [], "captain": 99, "chip": "bboost", "bench_order": [30, 40]}
    reward, b = compute_reward(s, POINTS)
    assert b["bench_points"] == 11
    assert reward == 10 + 12 + 11


def test_legacy_single_field_shape_still_works():
    s = {"transfer_in": 10, "transfer_out": 1, "captain": 99}
    reward, _ = compute_reward(s, POINTS)
    assert reward == 10 + 8 + 12
