import pytest
from core.scorer import (
    score_parameter, score_organ, score_overall,
    get_rank, get_level, get_difficulty, get_xp_for_difficulty,
    compute_trend, trend_series,
)


def test_score_parameter_midpoint_is_100():
    assert score_parameter(value=15.5, ref_min=0.0, ref_max=31.0) == 100


def test_score_parameter_in_range():
    s = score_parameter(value=27.76, ref_min=0.0, ref_max=31.0)
    assert 70 <= s <= 100


def test_score_parameter_above_range():
    s = score_parameter(value=50.0, ref_min=0.0, ref_max=31.0)
    assert s < 70


def test_score_parameter_at_range_max_is_70():
    s = score_parameter(value=31.0, ref_min=0.0, ref_max=31.0)
    assert s == 70


def test_score_parameter_far_above_range_clamps_to_zero():
    s = score_parameter(value=1000.0, ref_min=0.0, ref_max=31.0)
    assert s == 0


def test_score_organ_average():
    params = [
        {"name": "SGOT", "ref_min": 0.0, "ref_max": 31.0,
         "readings": [{"value": 15.5, "status": "normal"}]},
        {"name": "SGPT", "ref_min": 0.0, "ref_max": 34.0,
         "readings": [{"value": 17.0, "status": "normal"}]},
    ]
    score = score_organ(params, critical_params=set())
    assert score == 100


def test_score_organ_critical_param_weighted_2x():
    params = [
        {"name": "HEMOGLOBIN", "ref_min": 13.0, "ref_max": 17.0,
         "readings": [{"value": 10.0, "status": "low"}]},
        {"name": "MCV", "ref_min": 80.0, "ref_max": 100.0,
         "readings": [{"value": 90.0, "status": "normal"}]},
    ]
    score_with_critical = score_organ(params, critical_params={"HEMOGLOBIN"})
    score_without_critical = score_organ(params, critical_params=set())
    assert score_with_critical < score_without_critical


def test_get_rank():
    assert get_rank(350) == "Bronze"
    assert get_rank(500) == "Silver"
    assert get_rank(700) == "Gold"
    assert get_rank(900) == "Platinum"
    assert get_rank(980) == "Diamond"


def test_get_level():
    assert 1 <= get_level(0) <= 4
    assert 5 <= get_level(400) <= 8
    assert 17 <= get_level(950) <= 20


def test_get_difficulty():
    assert get_difficulty(value=27.0, ref_min=0.0, ref_max=31.0) == "Easy"
    assert get_difficulty(value=40.0, ref_min=0.0, ref_max=31.0) == "Medium"
    assert get_difficulty(value=80.0, ref_min=0.0, ref_max=31.0) == "Hard"


def test_get_xp_for_difficulty():
    assert get_xp_for_difficulty("Easy") == 10
    assert get_xp_for_difficulty("Medium") == 20
    assert get_xp_for_difficulty("Hard") == 30


# --- compute_trend ---

def _readings(values_oldest_first):
    """Build readings list (newest first) from a chronological list of values."""
    dates = [f"2025-{i+1:02d}-01" for i in range(len(values_oldest_first))]
    return [
        {"result_date": d, "value": v}
        for d, v in zip(reversed(dates), reversed(values_oldest_first))
    ]


def test_compute_trend_none_with_single_reading():
    r = _readings([20.0])
    assert compute_trend(r, ref_min=0.0, ref_max=31.0) is None


def test_compute_trend_improving():
    # Values moving from near edge toward midpoint: 27 → 15.5 (midpoint)
    r = _readings([27.0, 15.5])
    assert compute_trend(r, ref_min=0.0, ref_max=31.0) == "improving"


def test_compute_trend_declining():
    # Values moving from midpoint toward edge: 15.5 → 27 → out of range
    r = _readings([5.0, 27.0, 40.0])
    assert compute_trend(r, ref_min=0.0, ref_max=31.0) == "declining"


def test_compute_trend_stable():
    # Values barely changing inside range
    r = _readings([20.0, 20.5, 20.2, 20.1])
    result = compute_trend(r, ref_min=0.0, ref_max=31.0)
    assert result == "stable"


def test_compute_trend_lookback_limits_window():
    # First 2 readings are declining, last 2 are sharply improving
    # With lookback=2 we should see improving (the recent window)
    r = _readings([5.0, 5.0, 5.0, 5.0, 30.0, 15.5])
    assert compute_trend(r, ref_min=0.0, ref_max=31.0, lookback=2) == "improving"


def test_compute_trend_uses_full_window_by_default():
    # lookback=5 default: 6 readings but only 5 used
    r = _readings([30.0, 28.0, 25.0, 20.0, 15.0, 10.0])
    assert compute_trend(r, ref_min=0.0, ref_max=31.0) == "improving"


# --- trend_series ---

def test_trend_series_chronological_order():
    r = _readings([27.0, 14.0])
    series = trend_series(r, ref_min=0.0, ref_max=31.0)
    assert series[0]["date"] < series[1]["date"]


def test_trend_series_contains_score():
    r = _readings([15.5])
    series = trend_series(r, ref_min=0.0, ref_max=31.0)
    assert series[0]["score"] == 100


def test_trend_series_lookback_limits_output():
    r = _readings([10.0, 15.0, 20.0, 25.0, 27.0, 28.0])
    series = trend_series(r, ref_min=0.0, ref_max=31.0, lookback=3)
    assert len(series) == 3


def test_trend_series_includes_value_and_date():
    r = _readings([20.0, 10.0])
    series = trend_series(r, ref_min=0.0, ref_max=31.0)
    for point in series:
        assert "date" in point
        assert "value" in point
        assert "score" in point
