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


def test_get_organ_summaries_returns_organs_present(store):
    pid = store.create_patient("Hank")
    store.save_report(pid, "test.json", [
        {"name": "SGOT", "unit": "U/L", "organ": "liver",
         "ref_min": 0.0, "ref_max": 31.0,
         "readings": [{"date": "2025-10-15", "value": 20.0, "status": "normal"}]},
        {"name": "CREATININE", "unit": "mg/dL", "organ": "kidney",
         "ref_min": 0.7, "ref_max": 1.2,
         "readings": [{"date": "2025-10-15", "value": 0.9, "status": "normal"}]},
    ])
    organs = {s["organ"] for s in store.get_organ_summaries(pid)}
    assert organs == {"liver", "kidney"}


def test_save_report_upserts_parameter_by_name(store):
    pid = store.create_patient("Iris")
    store.save_report(pid, "report1.json", [
        {"name": "SGOT", "unit": "U/L", "organ": "liver",
         "ref_min": 0.0, "ref_max": 31.0,
         "readings": [{"date": "2025-10-15", "value": 20.0, "status": "normal"}]},
    ])
    store.save_report(pid, "report2.json", [
        {"name": "SGOT", "unit": "U/L", "organ": "liver",
         "ref_min": 0.0, "ref_max": 31.0,
         "readings": [{"date": "2026-03-01", "value": 14.0, "status": "normal"}]},
    ])
    params = store.get_parameters_for_organ(pid, "liver")
    # Only one parameter row, but two readings
    assert len(params) == 1
    assert len(params[0]["readings"]) == 2


def test_upsert_readings_ordered_newest_first(store):
    pid = store.create_patient("Jack")
    store.save_report(pid, "r1.json", [
        {"name": "SGOT", "unit": "U/L", "organ": "liver",
         "ref_min": 0.0, "ref_max": 31.0,
         "readings": [{"date": "2025-10-15", "value": 27.0, "status": "normal"}]},
    ])
    store.save_report(pid, "r2.json", [
        {"name": "SGOT", "unit": "U/L", "organ": "liver",
         "ref_min": 0.0, "ref_max": 31.0,
         "readings": [{"date": "2026-03-01", "value": 14.0, "status": "normal"}]},
    ])
    params = store.get_parameters_for_organ(pid, "liver")
    readings = params[0]["readings"]
    assert readings[0]["result_date"] == "2026-03-01"
    assert readings[1]["result_date"] == "2025-10-15"


def test_get_parameter_trends_single_reading_excluded(store):
    pid = store.create_patient("Karen")
    store.save_report(pid, "r.json", [
        {"name": "SGOT", "unit": "U/L", "organ": "liver",
         "ref_min": 0.0, "ref_max": 31.0,
         "readings": [{"date": "2025-10-15", "value": 20.0, "status": "normal"}]},
    ])
    trends = store.get_parameter_trends(pid, organs=["liver"])
    # Only 1 reading → direction is None
    assert trends[0]["direction"] is None


def test_get_parameter_trends_two_readings_has_direction(store):
    pid = store.create_patient("Leo")
    store.save_report(pid, "r1.json", [
        {"name": "SGOT", "unit": "U/L", "organ": "liver",
         "ref_min": 0.0, "ref_max": 31.0,
         "readings": [{"date": "2025-10-15", "value": 27.0, "status": "normal"}]},
    ])
    store.save_report(pid, "r2.json", [
        {"name": "SGOT", "unit": "U/L", "organ": "liver",
         "ref_min": 0.0, "ref_max": 31.0,
         "readings": [{"date": "2026-03-01", "value": 5.0, "status": "normal"}]},
    ])
    trends = store.get_parameter_trends(pid, organs=["liver"])
    assert trends[0]["direction"] == "improving"


def test_get_parameter_trends_series_is_chronological(store):
    pid = store.create_patient("Mia")
    store.save_report(pid, "r1.json", [
        {"name": "SGOT", "unit": "U/L", "organ": "liver",
         "ref_min": 0.0, "ref_max": 31.0,
         "readings": [{"date": "2025-10-15", "value": 27.0, "status": "normal"}]},
    ])
    store.save_report(pid, "r2.json", [
        {"name": "SGOT", "unit": "U/L", "organ": "liver",
         "ref_min": 0.0, "ref_max": 31.0,
         "readings": [{"date": "2026-03-01", "value": 5.0, "status": "normal"}]},
    ])
    trends = store.get_parameter_trends(pid, organs=["liver"])
    series = trends[0]["series"]
    assert series[0]["date"] < series[1]["date"]


def test_get_parameter_trends_organs_filter(store):
    pid = store.create_patient("Ned")
    store.save_report(pid, "r.json", [
        {"name": "SGOT", "unit": "U/L", "organ": "liver",
         "ref_min": 0.0, "ref_max": 31.0,
         "readings": [{"date": "2025-10-15", "value": 20.0, "status": "normal"}]},
        {"name": "CREATININE", "unit": "mg/dL", "organ": "kidney",
         "ref_min": 0.7, "ref_max": 1.2,
         "readings": [{"date": "2025-10-15", "value": 0.9, "status": "normal"}]},
    ])
    trends = store.get_parameter_trends(pid, organs=["liver"])
    assert all(t["organ"] == "liver" for t in trends)


def test_get_parameter_trends_lookback_limits_series(store):
    pid = store.create_patient("Olivia")
    for i, date in enumerate(["2025-01-01", "2025-04-01", "2025-07-01",
                               "2025-10-01", "2026-01-01", "2026-04-01"]):
        store.save_report(pid, f"r{i}.json", [
            {"name": "SGOT", "unit": "U/L", "organ": "liver",
             "ref_min": 0.0, "ref_max": 31.0,
             "readings": [{"date": date, "value": 15.0 + i, "status": "normal"}]},
        ])
    trends = store.get_parameter_trends(pid, organs=["liver"], lookback=3)
    assert len(trends[0]["series"]) == 3
