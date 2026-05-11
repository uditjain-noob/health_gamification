import pytest
from unittest.mock import MagicMock, patch
from apps.ingest import ingest_report


def test_ingest_creates_patient_when_no_id():
    store = MagicMock()
    store.create_patient.return_value = "pid-123"
    store.save_report.return_value = "rid-456"
    parser = MagicMock()
    parser.parse_json.return_value = [
        {"name": "SGOT", "unit": "U/L", "ref_min": 0.0, "ref_max": 31.0,
         "readings": [{"date": "2025-10-15", "value": 27.76, "status": "normal"}]}
    ]

    summary = ingest_report(
        store=store, parser=parser, mapper=MagicMock(),
        patient_id=None, patient_name="Alice",
        file_path=None, data=[{"parameter": "SGOT", "range": "0-31", "parameterValues": []}]
    )

    store.create_patient.assert_called_once_with(name="Alice")
    store.log_xp.assert_called_once()
    assert "pid-123" in summary
    assert "SGOT" in summary or "1 parameter" in summary


def test_ingest_uses_existing_patient_id():
    store = MagicMock()
    store.save_report.return_value = "rid-789"
    parser = MagicMock()
    parser.parse_json.return_value = []
    mapper = MagicMock()
    mapper.get_organ.return_value = "liver"

    summary = ingest_report(
        store=store, parser=parser, mapper=mapper,
        patient_id="existing-pid", patient_name=None,
        file_path=None, data=[]
    )

    store.create_patient.assert_not_called()
    assert "existing-pid" in summary
