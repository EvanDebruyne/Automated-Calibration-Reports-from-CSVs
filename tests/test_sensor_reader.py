"""
Tests for src/data_ingestion/sensor_reader.py
"""

import json
import tempfile
from pathlib import Path

import pandas as pd
import pytest

from src.data_ingestion.sensor_reader import SensorDataReader, ValidationReport


# ── Fixtures ──────────────────────────────────────────────────────────────────

VALID_ROWS = [
    {
        "timestamp": "2024-11-01T06:00:00",
        "site_id": "SITE-01",
        "instrument_id": "FT-201",
        "ph": 7.2,
        "turbidity_ntu": 0.4,
        "flow_rate_lps": 125.3,
        "temperature_c": 18.2,
        "conductivity_us": 450.1,
    },
    {
        "timestamp": "2024-11-01T07:00:00",
        "site_id": "SITE-01",
        "instrument_id": "FT-201",
        "ph": 7.5,
        "turbidity_ntu": 0.6,
        "flow_rate_lps": 127.0,
        "temperature_c": 18.6,
        "conductivity_us": 453.0,
    },
]

ANOMALOUS_ROW = {
    "timestamp": "2024-11-01T08:00:00",
    "site_id": "SITE-01",
    "instrument_id": "FT-201",
    "ph": 15.0,          # out of range (>14)
    "turbidity_ntu": 0.5,
    "flow_rate_lps": 120.0,
    "temperature_c": 18.0,
    "conductivity_us": 450.0,
}


@pytest.fixture
def valid_csv(tmp_path):
    df = pd.DataFrame(VALID_ROWS)
    csv_path = tmp_path / "valid.csv"
    df.to_csv(csv_path, index=False)
    return csv_path


@pytest.fixture
def anomalous_csv(tmp_path):
    rows = VALID_ROWS + [ANOMALOUS_ROW]
    df = pd.DataFrame(rows)
    csv_path = tmp_path / "anomalous.csv"
    df.to_csv(csv_path, index=False)
    return csv_path


@pytest.fixture
def valid_json(tmp_path):
    json_path = tmp_path / "valid.json"
    json_path.write_text(json.dumps(VALID_ROWS))
    return json_path


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestSensorDataReaderCSV:
    def test_load_valid_csv(self, valid_csv):
        reader = SensorDataReader(valid_csv)
        df = reader.load()
        assert len(df) == 2
        assert "ph" in df.columns
        assert reader.validation_report.invalid_rows == 0

    def test_timestamps_parsed(self, valid_csv):
        reader = SensorDataReader(valid_csv)
        df = reader.load()
        assert pd.api.types.is_datetime64_any_dtype(df["timestamp"])

    def test_sorted_by_timestamp(self, valid_csv):
        reader = SensorDataReader(valid_csv)
        df = reader.load()
        assert df["timestamp"].is_monotonic_increasing

    def test_out_of_range_flagged(self, anomalous_csv):
        reader = SensorDataReader(anomalous_csv)
        df = reader.load()
        report = reader.validation_report
        assert report.invalid_rows == 1
        assert "ph" in report.out_of_range
        assert report.out_of_range["ph"] == 1

    def test_file_not_found(self, tmp_path):
        reader = SensorDataReader(tmp_path / "nonexistent.csv")
        with pytest.raises(FileNotFoundError):
            reader.load()

    def test_unsupported_extension(self, tmp_path):
        f = tmp_path / "data.xlsx"
        f.write_text("")
        reader = SensorDataReader(f)
        with pytest.raises(ValueError, match="Unsupported file type"):
            reader.load()


class TestSensorDataReaderJSON:
    def test_load_valid_json(self, valid_json):
        reader = SensorDataReader(valid_json)
        df = reader.load()
        assert len(df) == 2
        assert reader.validation_report.invalid_rows == 0

    def test_load_wrapped_json(self, tmp_path):
        wrapped = {"readings": VALID_ROWS}
        json_path = tmp_path / "wrapped.json"
        json_path.write_text(json.dumps(wrapped))
        reader = SensorDataReader(json_path)
        df = reader.load()
        assert len(df) == 2

    def test_invalid_json_structure(self, tmp_path):
        json_path = tmp_path / "bad.json"
        json_path.write_text(json.dumps({"data": "wrong"}))
        reader = SensorDataReader(json_path)
        with pytest.raises(ValueError):
            reader.load()


class TestSiteAndInstrumentHelpers:
    def test_get_site_summary(self, valid_csv):
        reader = SensorDataReader(valid_csv)
        reader.load()
        summary = reader.get_site_summary()
        assert "SITE-01" in summary.index

    def test_get_instrument_readings(self, valid_csv):
        reader = SensorDataReader(valid_csv)
        reader.load()
        inst_df = reader.get_instrument_readings("FT-201")
        assert len(inst_df) == 2
        assert (inst_df["instrument_id"] == "FT-201").all()

    def test_get_instrument_readings_before_load(self, valid_csv):
        reader = SensorDataReader(valid_csv)
        with pytest.raises(RuntimeError):
            reader.get_instrument_readings("FT-201")

    def test_to_dict_records(self, valid_csv):
        reader = SensorDataReader(valid_csv)
        reader.load()
        records = reader.to_dict_records()
        assert isinstance(records, list)
        assert len(records) == 2
        assert "ph" in records[0]


class TestValidationReport:
    def test_is_valid_true(self):
        report = ValidationReport(total_rows=10, valid_rows=10)
        assert report.is_valid

    def test_is_valid_false_missing_columns(self):
        report = ValidationReport(missing_columns=["site_id"])
        assert not report.is_valid

    def test_is_valid_false_invalid_rows(self):
        report = ValidationReport(total_rows=10, valid_rows=9, invalid_rows=1)
        assert not report.is_valid

    def test_summary_contains_counts(self, valid_csv):
        reader = SensorDataReader(valid_csv)
        reader.load()
        summary = reader.validation_report.summary()
        assert "2 total" in summary
        assert "2 valid" in summary
