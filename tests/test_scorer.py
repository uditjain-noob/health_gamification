import pytest
from core.scorer import (
    score_parameter, score_organ, score_overall,
    get_rank, get_level, get_difficulty, get_xp_for_difficulty
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
