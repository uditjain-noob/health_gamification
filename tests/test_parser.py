import json
import pytest
from unittest.mock import MagicMock
from core.parser import Parser, _parse_range_string, compute_status


@pytest.fixture
def mock_client():
    return MagicMock()


@pytest.fixture
def parser(mock_client):
    return Parser(llm_client=mock_client)


SAMPLE_FORMAT = [
    {
        "parameter": "ASPARTATE AMINOTRANSFERASE (SGOT )",
        "range": "Range 0.0 - 31.0 U/L",
        "parameterValues": [
            {"resultDate": "2025-10-15T00:09:48Z", "value": "27.76"}
        ]
    }
]


def test_parse_sample_format(parser):
    result = parser.parse_json(SAMPLE_FORMAT)
    assert len(result) == 1
    assert result[0]["name"] == "ASPARTATE AMINOTRANSFERASE (SGOT )"
    assert result[0]["ref_min"] == 0.0
    assert result[0]["ref_max"] == 31.0
    assert result[0]["unit"] == "U/L"
    assert len(result[0]["readings"]) == 1
    assert result[0]["readings"][0]["value"] == 27.76


def test_parse_simple_format(parser):
    data = [{"name": "SGOT", "unit": "U/L", "reference_min": 0.0, "reference_max": 31.0,
              "readings": [{"date": "2025-10-15", "value": 27.76}]}]
    result = parser.parse_json(data)
    assert result[0]["ref_min"] == 0.0
    assert result[0]["readings"][0]["value"] == 27.76


def test_parse_range_string():
    min_v, max_v, unit = _parse_range_string("Range 0.0 - 31.0 U/L")
    assert min_v == 0.0
    assert max_v == 31.0
    assert unit == "U/L"


def test_parse_range_string_no_prefix():
    min_v, max_v, unit = _parse_range_string("0.0 - 31.0 U/L")
    assert min_v == 0.0
    assert max_v == 31.0


def test_unknown_format_falls_back_to_llm(mock_client, parser):
    unknown = [{"testName": "SGOT", "normalRange": "0-31", "result": "27.76"}]
    mock_client.complete.return_value = json.dumps([{
        "name": "SGOT", "unit": "U/L", "ref_min": 0.0, "ref_max": 31.0,
        "readings": [{"date": "2025-10-15", "value": 27.76}]
    }])
    result = parser.parse_json(unknown)
    assert mock_client.complete.called
    assert result[0]["name"] == "SGOT"


def test_compute_status_normal():
    assert compute_status(27.76, 0.0, 31.0) == "normal"


def test_compute_status_high():
    assert compute_status(45.0, 0.0, 31.0) == "high"


def test_compute_status_low():
    assert compute_status(-1.0, 0.0, 31.0) == "low"
