"""Poisson match model on FPL's overall team strength ratings (2 to 5 scale)."""

import math

HOME_BASE = 1.45  # average Premier League home goals per game
AWAY_BASE = 1.15  # average away goals per game
EXPONENT = 0.6  # how hard strength gaps push the expected goals
MAX_GOALS = 7


def expected_goals(home_strength: float, away_strength: float) -> tuple[float, float]:
    ratio = home_strength / away_strength
    return HOME_BASE * ratio**EXPONENT, AWAY_BASE * (1 / ratio) ** EXPONENT


def poisson(k: int, lam: float) -> float:
    return math.exp(-lam) * lam**k / math.factorial(k)


def match_probabilities(lam_h: float, lam_a: float) -> dict:
    home = draw = away = 0.0
    best, best_p = (0, 0), -1.0
    for h in range(MAX_GOALS + 1):
        for a in range(MAX_GOALS + 1):
            p = poisson(h, lam_h) * poisson(a, lam_a)
            if h > a:
                home += p
            elif h == a:
                draw += p
            else:
                away += p
            if p > best_p:
                best, best_p = (h, a), p
    return {
        "home_win": home,
        "draw": draw,
        "away_win": away,
        "likely_score": best,
        "home_clean_sheet": math.exp(-lam_a),
        "away_clean_sheet": math.exp(-lam_h),
    }


def predict_gameweek(teams: dict[int, dict], fixtures: list[dict]) -> list[dict]:
    """teams: {id: {"short": "MCI", "home": 4, "away": 5}}. fixtures: raw FPL rows."""
    predictions = []
    for f in fixtures:
        h, a = teams.get(f["team_h"]), teams.get(f["team_a"])
        if not h or not a:
            continue
        lam_h, lam_a = expected_goals(h["home"], a["away"])
        probs = match_probabilities(lam_h, lam_a)
        predictions.append(
            {"home": h["short"], "away": a["short"], "xg_home": lam_h, "xg_away": lam_a, **probs}
        )
    return predictions


def render_match_model_block(gw: int, predictions: list[dict]) -> str:
    if not predictions:
        return ""
    header = (
        f"\n\nMATCH MODEL for GW{gw} (Poisson on FPL team strength; use expected goals "
        "for attackers and captains, clean-sheet odds for defenders and keepers):"
    )
    lines = [header]
    for p in predictions:
        hs, as_ = p["likely_score"]
        lines.append(
            f"{p['home']} vs {p['away']}: xG {p['xg_home']:.1f} vs {p['xg_away']:.1f}, "
            f"likely {hs}-{as_}, win {p['home_win']:.0%}/draw {p['draw']:.0%}/"
            f"away {p['away_win']:.0%}, clean sheet {p['home']} {p['home_clean_sheet']:.0%} "
            f"/ {p['away']} {p['away_clean_sheet']:.0%}"
        )
    return "\n".join(lines)


def match_model_block_for_gw(fpl, gw: int) -> str:
    teams = fpl.get_team_strengths()
    fixtures = fpl.get_gw_fixtures_raw(gw)
    return render_match_model_block(gw, predict_gameweek(teams, fixtures))
