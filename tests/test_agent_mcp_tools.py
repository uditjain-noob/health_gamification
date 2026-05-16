import pytest
from db.store import Store
from core.organs import OrganMapper
from agent.mcp_tools import (
    GetParamsByOrganInput,
    get_params_by_organ_fn,
    PrioritizeOrgansInput,
    prioritize_organs_fn,
    FinishDashboardInput,
    finish_dashboard_fn,
)


@pytest.fixture
def store():
    s = Store(db_path=":memory:")
    s.initialize()
    return s


@pytest.fixture
def patient_id(store):
    pid = store.create_patient(name="Test Patient")
    store.save_report(
        patient_id=pid,
        source_file="test.json",
        parameters=[
            {
                "name": "SGOT",
                "raw_name": "SGOT",
                "unit": "U/L",
                "organ": "liver",
                "ref_min": 0.0,
                "ref_max": 31.0,
                "readings": [{"date": "2025-01-01", "value": 15.5, "status": "normal"}],
            },
            {
                "name": "SGPT",
                "raw_name": "SGPT",
                "unit": "U/L",
                "organ": "liver",
                "ref_min": 0.0,
                "ref_max": 34.0,
                "readings": [{"date": "2025-01-01", "value": 45.0, "status": "high"}],
            },
        ],
    )
    return pid


@pytest.fixture
def mapper():
    return OrganMapper()


# --- get_params_by_organ ---

def test_get_params_by_organ_returns_organ_and_params(store, patient_id, mapper):
    result = get_params_by_organ_fn(
        GetParamsByOrganInput(patient_id=patient_id, organ="liver"),
        store, mapper,
    )
    assert result["organ"] == "liver"
    assert len(result["parameters"]) == 2


def test_get_params_by_organ_counts_flagged(store, patient_id, mapper):
    result = get_params_by_organ_fn(
        GetParamsByOrganInput(patient_id=patient_id, organ="liver"),
        store, mapper,
    )
    assert result["flagged_count"] == 1  # SGPT is high


def test_get_params_by_organ_returns_score(store, patient_id, mapper):
    result = get_params_by_organ_fn(
        GetParamsByOrganInput(patient_id=patient_id, organ="liver"),
        store, mapper,
    )
    assert 0 <= result["organ_score"] <= 100


def test_get_params_by_organ_unknown_organ_returns_empty(store, patient_id, mapper):
    result = get_params_by_organ_fn(
        GetParamsByOrganInput(patient_id=patient_id, organ="pancreas"),
        store, mapper,
    )
    assert result["parameters"] == []
    assert result["flagged_count"] == 0


# --- prioritize_organs ---

def test_prioritize_organs_sorts_by_flagged_count():
    summaries = [
        {"organ": "liver", "flagged_count": 2, "score": 60},
        {"organ": "kidney", "flagged_count": 5, "score": 40},
        {"organ": "heart", "flagged_count": 0, "score": 90},
    ]
    result = prioritize_organs_fn(
        PrioritizeOrgansInput(context="", organ_summaries=summaries)
    )
    assert result[0]["organ"] == "kidney"
    assert result[1]["organ"] == "liver"


def test_prioritize_organs_limits_to_four():
    summaries = [
        {"organ": f"organ_{i}", "flagged_count": i, "score": 80 - i}
        for i in range(6)
    ]
    result = prioritize_organs_fn(
        PrioritizeOrgansInput(context="weight loss", organ_summaries=summaries)
    )
    assert len(result) <= 4


def test_prioritize_organs_includes_priority_rank():
    summaries = [{"organ": "liver", "flagged_count": 1, "score": 70}]
    result = prioritize_organs_fn(
        PrioritizeOrgansInput(context="", organ_summaries=summaries)
    )
    assert result[0]["priority_rank"] == 1


# --- finish_dashboard ---

def test_finish_dashboard_returns_done_status():
    result = finish_dashboard_fn(
        FinishDashboardInput(sections_complete=3, overall_summary="Good health")
    )
    assert result["status"] == "done"


def test_finish_dashboard_preserves_section_count():
    result = finish_dashboard_fn(
        FinishDashboardInput(sections_complete=5, overall_summary="")
    )
    assert result["sections"] == 5


def test_finish_dashboard_preserves_summary():
    result = finish_dashboard_fn(
        FinishDashboardInput(sections_complete=1, overall_summary="Focus on liver")
    )
    assert result["summary"] == "Focus on liver"


# --- Pydantic validation ---

def test_get_params_by_organ_input_requires_patient_id():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        GetParamsByOrganInput(organ="liver")  # missing patient_id
