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


# --- Real parameter names from sample_organ_data.json ---

def test_bilirubin_total_maps_to_liver(mapper):
    assert mapper.get_organ("BILIRUBIN - TOTAL") == "liver"


def test_bilirubin_indirect_maps_to_liver(mapper):
    assert mapper.get_organ("BILIRUBIN (INDIRECT)") == "liver"


def test_bilirubin_direct_maps_to_liver(mapper):
    assert mapper.get_organ("BILIRUBIN -DIRECT") == "liver"


def test_protein_total_maps_to_liver(mapper):
    assert mapper.get_organ("PROTEIN - TOTAL") == "liver"


def test_alb_globulin_ratio_maps_to_liver(mapper):
    assert mapper.get_organ("SERUM ALB/GLOBULIN RATIO") == "liver"


def test_ldl_hdl_ratio_maps_to_heart(mapper):
    assert mapper.get_organ("LDL / HDL RATIO") == "heart"


def test_hdl_ldl_ratio_maps_to_heart(mapper):
    assert mapper.get_organ("HDL / LDL RATIO") == "heart"


def test_trig_hdl_ratio_maps_to_heart(mapper):
    assert mapper.get_organ("TRIG / HDL RATIO") == "heart"


def test_tc_hdl_ratio_maps_to_heart(mapper):
    assert mapper.get_organ("TC/ HDL CHOLESTEROL RATIO") == "heart"


def test_ldl_cholesterol_direct_maps_to_heart(mapper):
    assert mapper.get_organ("LDL CHOLESTEROL - DIRECT") == "heart"


def test_hdl_cholesterol_direct_maps_to_heart(mapper):
    assert mapper.get_organ("HDL CHOLESTEROL - DIRECT") == "heart"


def test_lymphocyte_singular_maps_to_blood(mapper):
    assert mapper.get_organ("LYMPHOCYTE") == "blood"


def test_immature_granulocyte_maps_to_blood(mapper):
    assert mapper.get_organ("IMMATURE GRANULOCYTE PERCENTAGE(IG%)") == "blood"


def test_plateletcrit_maps_to_blood(mapper):
    assert mapper.get_organ("PLATELETCRIT(PCT)") == "blood"


def test_specific_gravity_maps_to_kidney(mapper):
    assert mapper.get_organ("SPECIFIC GRAVITY") == "kidney"


def test_epithelial_cells_maps_to_kidney(mapper):
    assert mapper.get_organ("EPITHELIAL CELLS") == "kidney"


def test_vitamin_d_25oh_maps_to_bone(mapper):
    assert mapper.get_organ("25-OH VITAMIN D (TOTAL)") == "bone"


def test_vitamin_b12_maps_to_bone(mapper):
    assert mapper.get_organ("VITAMIN B-12") == "bone"


def test_tsh_ultrasensitive_maps_to_thyroid(mapper):
    assert mapper.get_organ("TSH - ULTRASENSITIVE") == "thyroid"


def test_hba1c_maps_to_metabolic(mapper):
    assert mapper.get_organ("HbA1c") == "metabolic"


def test_creatinine_serum_is_critical(mapper):
    # is_critical must use substring match — "CREATININE" in "CREATININE - SERUM"
    assert mapper.is_critical("CREATININE - SERUM") is True


def test_tsh_ultrasensitive_is_critical(mapper):
    assert mapper.is_critical("TSH - ULTRASENSITIVE") is True


def test_vitamin_d_25oh_is_critical(mapper):
    assert mapper.is_critical("25-OH VITAMIN D (TOTAL)") is True


def test_ldl_cholesterol_direct_is_critical(mapper):
    assert mapper.is_critical("LDL CHOLESTEROL - DIRECT") is True
