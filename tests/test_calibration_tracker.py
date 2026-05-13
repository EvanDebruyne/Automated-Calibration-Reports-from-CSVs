"""
Tests for src/compliance/tracker.py
"""

import pytest
from datetime import date, timedelta

from src.compliance.tracker import CalibrationTracker


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def tracker(tmp_path):
    """Fresh in-memory tracker backed by a temp database."""
    return CalibrationTracker(db_path=tmp_path / "test.db")


@pytest.fixture
def tracker_with_instrument(tracker):
    tracker.register_instrument(
        instrument_id="FT-201",
        site_id="SITE-01",
        instrument_type="Flow Meter",
        calibration_interval_days=90,
    )
    return tracker


# ── Registration tests ────────────────────────────────────────────────────────

class TestRegisterInstrument:
    def test_register_new_instrument(self, tracker):
        tracker.register_instrument("FT-201", "SITE-01")
        status = tracker.get_status("FT-201")
        assert status is not None
        assert status.instrument_id == "FT-201"

    def test_register_updates_existing(self, tracker_with_instrument):
        # Re-register with a different interval
        tracker_with_instrument.register_instrument(
            "FT-201", "SITE-01", calibration_interval_days=60
        )
        status = tracker_with_instrument.get_status("FT-201")
        assert status.calibration_interval_days == 60

    def test_unregistered_instrument_returns_none(self, tracker):
        assert tracker.get_status("NONEXISTENT") is None


# ── Calibration event tests ───────────────────────────────────────────────────

class TestCalibrationEvents:
    def test_record_calibration_returns_id(self, tracker_with_instrument):
        event_id = tracker_with_instrument.record_calibration(
            "FT-201", "SITE-01", date.today().isoformat(), "Ethan Den Brok", "PASS"
        )
        assert isinstance(event_id, int)
        assert event_id > 0

    def test_calibration_history(self, tracker_with_instrument):
        tracker_with_instrument.record_calibration(
            "FT-201", "SITE-01", "2024-09-01", "Alice", "PASS"
        )
        tracker_with_instrument.record_calibration(
            "FT-201", "SITE-01", "2024-12-01", "Bob", "ADJUSTED"
        )
        history = tracker_with_instrument.get_calibration_history("FT-201")
        assert len(history) == 2
        # Most recent first
        assert history[0]["calibration_date"] == "2024-12-01"

    def test_failed_calibration_not_counted_for_status(self, tracker_with_instrument):
        # A FAIL result should not update the "last good calibration" date
        fail_date = (date.today() - timedelta(days=5)).isoformat()
        tracker_with_instrument.record_calibration(
            "FT-201", "SITE-01", fail_date, "Eve", "FAIL"
        )
        status = tracker_with_instrument.get_status("FT-201")
        # Still no successful calibration on record
        assert status.status == "NEVER_CALIBRATED"


# ── Status computation tests ──────────────────────────────────────────────────

class TestCalibrationStatus:
    def test_never_calibrated(self, tracker_with_instrument):
        status = tracker_with_instrument.get_status("FT-201")
        assert status.status == "NEVER_CALIBRATED"
        assert status.last_calibration_date is None

    def test_ok_status(self, tracker_with_instrument):
        recent_date = (date.today() - timedelta(days=30)).isoformat()
        tracker_with_instrument.record_calibration(
            "FT-201", "SITE-01", recent_date, "Ethan", "PASS"
        )
        status = tracker_with_instrument.get_status("FT-201")
        assert status.status == "OK"
        assert status.days_since_calibration == 30

    def test_due_status(self, tracker_with_instrument):
        # 80 days ago — due within 14 days (interval=90)
        cal_date = (date.today() - timedelta(days=80)).isoformat()
        tracker_with_instrument.record_calibration(
            "FT-201", "SITE-01", cal_date, "Ethan", "PASS"
        )
        status = tracker_with_instrument.get_status("FT-201")
        assert status.status == "DUE"

    def test_overdue_status(self, tracker_with_instrument):
        old_date = (date.today() - timedelta(days=120)).isoformat()
        tracker_with_instrument.record_calibration(
            "FT-201", "SITE-01", old_date, "Ethan", "PASS"
        )
        status = tracker_with_instrument.get_status("FT-201")
        assert status.status == "OVERDUE"

    def test_next_due_date_calculation(self, tracker_with_instrument):
        cal_date = date(2024, 11, 15)
        tracker_with_instrument.record_calibration(
            "FT-201", "SITE-01", cal_date.isoformat(), "Ethan", "PASS"
        )
        status = tracker_with_instrument.get_status("FT-201")
        expected_due = date(2025, 2, 13).isoformat()  # 90 days after Nov 15
        assert status.next_due_date == expected_due


# ── Batch status tests ────────────────────────────────────────────────────────

class TestBatchStatus:
    def test_list_overdue(self, tracker):
        tracker.register_instrument("FT-201", "SITE-01", calibration_interval_days=90)
        tracker.register_instrument("PH-105", "SITE-02", calibration_interval_days=90)

        # FT-201: calibrated recently — OK
        recent = (date.today() - timedelta(days=10)).isoformat()
        tracker.record_calibration("FT-201", "SITE-01", recent, "Ethan", "PASS")

        # PH-105: never calibrated — NEVER_CALIBRATED (shows in overdue)
        overdue = tracker.list_overdue()
        overdue_ids = [s.instrument_id for s in overdue]
        assert "PH-105" in overdue_ids
        assert "FT-201" not in overdue_ids

    def test_list_due_soon(self, tracker):
        tracker.register_instrument("FT-201", "SITE-01", calibration_interval_days=90)
        almost_due = (date.today() - timedelta(days=80)).isoformat()
        tracker.record_calibration("FT-201", "SITE-01", almost_due, "Ethan", "PASS")

        due_soon = tracker.list_due_soon(within_days=14)
        assert any(s.instrument_id == "FT-201" for s in due_soon)

    def test_get_status_all(self, tracker):
        tracker.register_instrument("FT-201", "SITE-01")
        tracker.register_instrument("PH-105", "SITE-02")
        statuses = tracker.get_status_all()
        assert len(statuses) == 2


# ── Report logging tests ──────────────────────────────────────────────────────

class TestReportLogging:
    def test_record_report(self, tracker_with_instrument):
        # Should not raise
        tracker_with_instrument.record_report(
            "FT-201", "SITE-01",
            word_path="examples/generated_reports/report.docx",
            pdf_path="examples/generated_reports/report.pdf",
        )
