"""
tracker.py
----------
SQLite-backed calibration history tracker.

Tables
------
instruments
  - instrument_id   TEXT PRIMARY KEY
  - site_id         TEXT
  - instrument_type TEXT
  - description     TEXT
  - calibration_interval_days  INTEGER  (default 90)
  - created_at      TEXT

calibration_events
  - id              INTEGER PRIMARY KEY AUTOINCREMENT
  - instrument_id   TEXT  REFERENCES instruments
  - site_id         TEXT
  - calibration_date TEXT  (ISO date)
  - technician      TEXT
  - result          TEXT  (PASS / FAIL / ADJUSTED)
  - notes           TEXT
  - recorded_at     TEXT

reports
  - id              INTEGER PRIMARY KEY AUTOINCREMENT
  - instrument_id   TEXT
  - site_id         TEXT
  - report_date     TEXT
  - word_path       TEXT
  - pdf_path        TEXT
  - generated_at    TEXT
"""

import logging
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Generator, Optional

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = Path("data") / "calibration.db"


@dataclass
class CalibrationStatus:
    instrument_id: str
    site_id: str
    last_calibration_date: Optional[str]
    calibration_interval_days: int
    days_since_calibration: Optional[int]
    next_due_date: Optional[str]
    status: str   # OK | DUE | OVERDUE | NEVER_CALIBRATED

    def __str__(self):
        return (
            f"{self.instrument_id} ({self.site_id}): {self.status} "
            f"— last calibrated {self.last_calibration_date or 'never'}, "
            f"next due {self.next_due_date or 'ASAP'}"
        )


class CalibrationTracker:
    """
    Manages instrument calibration history in a local SQLite database.

    Usage
    -----
    >>> tracker = CalibrationTracker()
    >>> tracker.register_instrument("FT-201", "SITE-01", "Flow Meter", interval_days=90)
    >>> tracker.record_calibration("FT-201", "SITE-01", "2024-11-15", "Ethan Den Brok", "PASS")
    >>> status = tracker.get_status("FT-201")
    >>> print(status)
    >>> overdue = tracker.list_overdue()
    """

    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    # ── Public API ────────────────────────────────────────────────────────────

    def register_instrument(
        self,
        instrument_id: str,
        site_id: str,
        instrument_type: str = "Unknown",
        description: str = "",
        calibration_interval_days: int = 90,
    ) -> None:
        """Register a new instrument or update its metadata."""
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO instruments
                    (instrument_id, site_id, instrument_type, description,
                     calibration_interval_days, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(instrument_id) DO UPDATE SET
                    site_id = excluded.site_id,
                    instrument_type = excluded.instrument_type,
                    description = excluded.description,
                    calibration_interval_days = excluded.calibration_interval_days
                """,
                (
                    instrument_id,
                    site_id,
                    instrument_type,
                    description,
                    calibration_interval_days,
                    datetime.utcnow().isoformat(),
                ),
            )
        logger.info("Registered instrument: %s at %s", instrument_id, site_id)

    def record_calibration(
        self,
        instrument_id: str,
        site_id: str,
        calibration_date: str,
        technician: str,
        result: str = "PASS",
        notes: str = "",
    ) -> int:
        """
        Record a calibration event.

        Parameters
        ----------
        calibration_date : ISO date string e.g. "2024-11-15"
        result           : "PASS", "FAIL", or "ADJUSTED"

        Returns
        -------
        The new event row ID.
        """
        with self._conn() as conn:
            cursor = conn.execute(
                """
                INSERT INTO calibration_events
                    (instrument_id, site_id, calibration_date, technician,
                     result, notes, recorded_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    instrument_id,
                    site_id,
                    calibration_date,
                    technician,
                    result,
                    notes,
                    datetime.utcnow().isoformat(),
                ),
            )
            row_id = cursor.lastrowid
        logger.info(
            "Recorded calibration: %s — %s on %s by %s",
            instrument_id, result, calibration_date, technician,
        )
        return row_id

    def get_status(self, instrument_id: str) -> Optional[CalibrationStatus]:
        """Return current calibration status for an instrument."""
        with self._conn() as conn:
            inst = conn.execute(
                "SELECT site_id, calibration_interval_days FROM instruments WHERE instrument_id = ?",
                (instrument_id,),
            ).fetchone()
            if not inst:
                logger.warning("Instrument not found: %s", instrument_id)
                return None

            site_id, interval = inst["site_id"], inst["calibration_interval_days"]
            last = conn.execute(
                """
                SELECT calibration_date FROM calibration_events
                WHERE instrument_id = ? AND result != 'FAIL'
                ORDER BY calibration_date DESC LIMIT 1
                """,
                (instrument_id,),
            ).fetchone()

        return self._compute_status(instrument_id, site_id, last, interval)

    def get_status_all(self) -> list[CalibrationStatus]:
        """Return status for every registered instrument."""
        with self._conn() as conn:
            instruments = conn.execute(
                "SELECT instrument_id, site_id, calibration_interval_days FROM instruments"
            ).fetchall()

        statuses = []
        for row in instruments:
            status = self.get_status(row["instrument_id"])
            if status:
                statuses.append(status)
        return statuses

    def list_overdue(self) -> list[CalibrationStatus]:
        """Return all instruments that are overdue for calibration."""
        return [s for s in self.get_status_all() if s.status in ("OVERDUE", "NEVER_CALIBRATED")]

    def list_due_soon(self, within_days: int = 14) -> list[CalibrationStatus]:
        """Return instruments whose calibration is due within the next N days."""
        results = []
        for s in self.get_status_all():
            if s.status == "DUE":
                results.append(s)
            elif s.next_due_date:
                days_until = (date.fromisoformat(s.next_due_date) - date.today()).days
                if 0 <= days_until <= within_days:
                    results.append(s)
        return results

    def get_calibration_history(
        self, instrument_id: str, limit: int = 50
    ) -> list[dict]:
        """Return recent calibration events for an instrument."""
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT calibration_date, technician, result, notes, recorded_at
                FROM calibration_events
                WHERE instrument_id = ?
                ORDER BY calibration_date DESC
                LIMIT ?
                """,
                (instrument_id, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def record_report(
        self,
        instrument_id: str,
        site_id: str,
        word_path: Optional[str] = None,
        pdf_path: Optional[str] = None,
    ) -> None:
        """Log a generated report to the database."""
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO reports
                    (instrument_id, site_id, report_date, word_path, pdf_path, generated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    instrument_id,
                    site_id,
                    date.today().isoformat(),
                    str(word_path) if word_path else None,
                    str(pdf_path) if pdf_path else None,
                    datetime.utcnow().isoformat(),
                ),
            )

    # ── Private helpers ───────────────────────────────────────────────────────

    def _init_db(self):
        with self._conn() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS instruments (
                    instrument_id              TEXT PRIMARY KEY,
                    site_id                    TEXT NOT NULL,
                    instrument_type            TEXT DEFAULT 'Unknown',
                    description                TEXT DEFAULT '',
                    calibration_interval_days  INTEGER DEFAULT 90,
                    created_at                 TEXT
                );

                CREATE TABLE IF NOT EXISTS calibration_events (
                    id               INTEGER PRIMARY KEY AUTOINCREMENT,
                    instrument_id    TEXT NOT NULL,
                    site_id          TEXT NOT NULL,
                    calibration_date TEXT NOT NULL,
                    technician       TEXT,
                    result           TEXT DEFAULT 'PASS',
                    notes            TEXT DEFAULT '',
                    recorded_at      TEXT,
                    FOREIGN KEY (instrument_id) REFERENCES instruments(instrument_id)
                );

                CREATE TABLE IF NOT EXISTS reports (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    instrument_id TEXT,
                    site_id       TEXT,
                    report_date   TEXT,
                    word_path     TEXT,
                    pdf_path      TEXT,
                    generated_at  TEXT
                );
                """
            )
        logger.debug("Database initialised at: %s", self.db_path)

    @contextmanager
    def _conn(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def _compute_status(
        instrument_id: str,
        site_id: str,
        last_row: Optional[sqlite3.Row],
        interval: int,
    ) -> CalibrationStatus:
        today = date.today()

        if last_row is None:
            return CalibrationStatus(
                instrument_id=instrument_id,
                site_id=site_id,
                last_calibration_date=None,
                calibration_interval_days=interval,
                days_since_calibration=None,
                next_due_date=None,
                status="NEVER_CALIBRATED",
            )

        last_date = date.fromisoformat(last_row["calibration_date"])
        days_since = (today - last_date).days
        next_due = last_date + timedelta(days=interval)
        days_until_due = (next_due - today).days

        if days_until_due < 0:
            status = "OVERDUE"
        elif days_until_due <= 14:
            status = "DUE"
        else:
            status = "OK"

        return CalibrationStatus(
            instrument_id=instrument_id,
            site_id=site_id,
            last_calibration_date=last_date.isoformat(),
            calibration_interval_days=interval,
            days_since_calibration=days_since,
            next_due_date=next_due.isoformat(),
            status=status,
        )
