import pytest
from core.organs import OrganMapper


@pytest.fixture
def mapper():
    return OrganMapper()


def test_exact_match(mapper):
    assert mapper.get_organ("SGOT") == "liver"


def test_fuzzy_match_long_name(mapper):
    # Real lab name from sample_organ_data.json
    assert mapper.get_organ("ASPARTATE AMINOTRANSFERASE (SGOT )") == "liver"


def test_fuzzy_match_alkaline(mapper):
    assert mapper.get_organ("ALKALINE PHOSPHATASE") == "liver"


def test_kidney_exact(mapper):
    assert mapper.get_organ("CREATININE") == "kidney"


def test_blood_hemoglobin(mapper):
    assert mapper.get_organ("HEMOGLOBIN") == "blood"


def test_unknown_returns_other(mapper):
    assert mapper.get_organ("COMPLETELY UNKNOWN MARKER") == "other"


def test_is_critical(mapper):
    assert mapper.is_critical("CREATININE") is True
    assert mapper.is_critical("SGOT") is False


def test_get_organ_weight(mapper):
    assert mapper.get_organ_weight("liver") == 0.15
    assert mapper.get_organ_weight("heart") == 0.20


def test_normalize_name_strips_whitespace_and_upper(mapper):
    assert mapper.get_organ("  sgot  ") == "liver"
