"""Reward for the picked agent once real points are in."""

from committee.agents import transfers_of

SELECTION_BONUS = 10
HIT_COST = 4
FREE_CHIPS = ("wildcard", "freehit")


def compute_reward(
    suggestion: dict, gw_points: dict[int, int], free_transfers: int = 1
) -> tuple[float, dict]:
    ins = [pid for _, pid in transfers_of(suggestion)]
    chip = suggestion.get("chip")
    in_points = sum(gw_points.get(pid, 0) for pid in ins)
    captain_points = gw_points.get(suggestion["captain"], 0)
    if chip == "3xc":
        captain_points *= 2
    bench_points = 0
    if chip == "bboost":
        bench_points = sum(gw_points.get(pid, 0) for pid in suggestion.get("bench_order") or [])
    hits = 0 if chip in FREE_CHIPS else max(0, len(ins) - free_transfers)
    reward = SELECTION_BONUS + in_points + captain_points + bench_points - HIT_COST * hits
    return float(reward), {
        "selection": SELECTION_BONUS,
        "transfer_in_points": in_points,
        "captain_points": captain_points,
        "bench_points": bench_points,
        "hits": hits,
        "hit_cost": HIT_COST * hits,
        "chip": chip,
    }
