from unittest.mock import MagicMock
from apps.dashboard import get_dashboard_json


def _make_store(organ="liver", flagged=False):
    store = MagicMock()
    store.get_organ_summaries.return_value = [{"organ": organ}]
    status = "high" if flagged else "normal"
    store.get_parameters_for_organ.return_value = [
        {
            "name": "ALT",
            "ref_min": 7,
            "ref_max": 56,
            "readings": [{"status": status, "value": 30}],
        }
    ]
    store.get_xp_total.return_value = 75
    return store


def _make_mapper():
    mapper = MagicMock()
    mapper.is_critical.return_value = False
    mapper.get_organ_emoji.return_value = "🫁"
    mapper.get_organ_weight.return_value = 1.0
    return mapper


def test_get_dashboard_json_shape():
    data = get_dashboard_json(_make_store(), _make_mapper(), "p1")
    assert isinstance(data["overall"], (int, float))
    assert isinstance(data["rank"], str)
    assert isinstance(data["rank_emoji"], str)
    assert isinstance(data["level"], int)
    assert isinstance(data["xp_total"], int)
    assert isinstance(data["xp_to_next"], int)
    assert isinstance(data["organs"], list)
    assert isinstance(data["total_params"], int)
    assert isinstance(data["total_flagged"], int)


def test_get_dashboard_json_organ_fields():
    data = get_dashboard_json(_make_store(), _make_mapper(), "p1")
    organ = data["organs"][0]
    assert organ["organ"] == "liver"
    assert organ["emoji"] == "🫁"
    assert isinstance(organ["score"], (int, float))
    assert isinstance(organ["rank"], str)
    assert organ["parameter_count"] == 1
    assert organ["flagged_count"] == 0


def test_get_dashboard_json_counts_flagged():
    data = get_dashboard_json(_make_store(flagged=True), _make_mapper(), "p1")
    assert data["organs"][0]["flagged_count"] == 1
    assert data["total_flagged"] == 1


def test_get_dashboard_json_empty_patient():
    store = MagicMock()
    store.get_organ_summaries.return_value = []
    store.get_xp_total.return_value = 0
    data = get_dashboard_json(store, MagicMock(), "nobody")
    assert data["organs"] == []
    assert data["overall"] == 0
    assert data["total_params"] == 0
