from datetime import datetime
import pytest
from core.models import Patient, ParameterReading, Parameter, LabResult, OrganSummary


def test_parameter_reading_computes_status_high():
    r = ParameterReading(date=datetime(2025, 10, 15), value=45.0, status="high")
    assert r.status == "high"


def test_parameter_reading_rejects_invalid_status():
    with pytest.raises(Exception):
        ParameterReading(date=datetime(2025, 10, 15), value=45.0, status="unknown")


def test_parameter_has_required_fields():
    p = Parameter(
        name="SGOT",
        raw_name="ASPARTATE AMINOTRANSFERASE (SGOT )",
        unit="U/L",
        organ="liver",
        reference_min=0.0,
        reference_max=31.0,
        readings=[ParameterReading(date=datetime(2025, 10, 15), value=27.76, status="normal")],
        trend=None,
    )
    assert p.name == "SGOT"
    assert p.organ == "liver"


def test_patient_id_is_required():
    with pytest.raises(Exception):
        Patient(name="Alice", created_at=datetime.now())


def test_organ_summary_rank_literal():
    s = OrganSummary(organ="liver", score=85, flagged_count=0, parameter_count=10, rank="Good")
    assert s.rank == "Good"
    with pytest.raises(Exception):
        OrganSummary(organ="liver", score=85, flagged_count=0, parameter_count=10, rank="Unknown")
