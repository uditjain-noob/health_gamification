import pytest
from datetime import datetime
from db.store import Store


@pytest.fixture
def store():
    # libsql-experimental supports :memory: for tests (no Turso URL = local only)
    s = Store(db_path=":memory:")
    s.initialize()
    return s


def test_create_patient_returns_id(store):
    pid = store.create_patient(name="Alice")
    assert isinstance(pid, str)
    assert len(pid) > 0


def test_create_patient_no_name(store):
    pid = store.create_patient(name=None)
    assert pid is not None


def test_save_report_returns_id(store):
    pid = store.create_patient("Bob")
    rid = store.save_report(
        patient_id=pid,
        source_file="test.json",
        parameters=[{
            "name": "SGOT", "raw_name": "SGOT", "unit": "U/L",
            "organ": "liver", "ref_min": 0.0, "ref_max": 31.0,
            "readings": [{"date": "2025-10-15", "value": 27.76, "status": "normal"}]
        }]
    )
    assert isinstance(rid, str)


def test_get_parameters_for_organ(store):
    pid = store.create_patient("Carol")
    store.save_report(
        patient_id=pid,
        source_file="test.json",
        parameters=[
            {"name": "SGOT", "raw_name": "SGOT", "unit": "U/L",
             "organ": "liver", "ref_min": 0.0, "ref_max": 31.0,
             "readings": [{"date": "2025-10-15", "value": 27.76, "status": "normal"}]},
            {"name": "CREATININE", "raw_name": "CREATININE", "unit": "mg/dL",
             "organ": "kidney", "ref_min": 0.7, "ref_max": 1.2,
             "readings": [{"date": "2025-10-15", "value": 0.9, "status": "normal"}]},
        ]
    )
    liver_params = store.get_parameters_for_organ(patient_id=pid, organ="liver")
    assert len(liver_params) == 1
    assert liver_params[0]["name"] == "SGOT"


def test_log_xp_and_get_total(store):
    pid = store.create_patient("Dave")
    store.log_xp(patient_id=pid, event="upload_report", xp=50)
    store.log_xp(patient_id=pid, event="quest_complete", xp=20)
    assert store.get_xp_total(patient_id=pid) == 70


def test_get_latest_report_returns_most_recent(store):
    pid = store.create_patient("Eve")
    store.save_report(pid, "first.json", [])
    store.save_report(pid, "second.json", [])
    report = store.get_latest_report(patient_id=pid)
    assert report["source_file"] == "second.json"


def test_get_latest_report_none_when_empty(store):
    pid = store.create_patient("Frank")
    assert store.get_latest_report(patient_id=pid) is None


def test_get_organ_summaries_empty(store):
    pid = store.create_patient("Grace")
    summaries = store.get_organ_summaries(patient_id=pid)
    assert summaries == []
