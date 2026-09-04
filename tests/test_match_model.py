import math

from committee.match_model import (
    AWAY_BASE,
    HOME_BASE,
    expected_goals,
    match_probabilities,
    predict_gameweek,
    render_match_model_block,
)


def test_equal_teams_get_league_average_goals():
    lam_h, lam_a = expected_goals(3, 3)
    assert lam_h == HOME_BASE
    assert lam_a == AWAY_BASE


def test_stronger_home_side_scores_more_and_concedes_less():
    lam_h, lam_a = expected_goals(4, 2)  # e.g. Man City home vs Coventry away
    assert lam_h > HOME_BASE
    assert lam_a < AWAY_BASE
    assert lam_h > 2 * lam_a


def test_probabilities_are_coherent():
    probs = match_probabilities(1.45, 1.15)
    total = probs["home_win"] + probs["draw"] + probs["away_win"]
    assert abs(total - 1.0) < 0.01
    assert probs["home_win"] > probs["away_win"]
    assert abs(probs["home_clean_sheet"] - math.exp(-1.15)) < 1e-9
    assert probs["likely_score"] == (1, 1)


def test_predict_and_render_gameweek():
    teams = {15: {"short": "MCI", "home": 4, "away": 5}, 7: {"short": "COV", "home": 2, "away": 2}}
    fixtures = [{"team_h": 15, "team_a": 7}, {"team_h": 99, "team_a": 7}]  # unknown team skipped
    preds = predict_gameweek(teams, fixtures)
    assert len(preds) == 1
    block = render_match_model_block(3, preds)
    assert "MATCH MODEL for GW3" in block
    assert "MCI vs COV: xG" in block
    assert "clean sheet MCI" in block
