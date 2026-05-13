"""
sensor_reader.py
----------------
Reads and validates raw sensor data from CSV or JSON files.

Supported sensor parameters:
  - timestamp       : ISO 8601 datetime string
  - ph              : pH level (0–14)
  - turbidity_ntu   : Turbidity in NTU
  - flow_rate_lps   : Flow rate in litres per second
  - temperature_c   : Temperature in Celsius
  - conductivity_us : Conductivity in µS/cm
  - site_id         : Monitoring site identifier
  - instrument_id   : Sensor/instrument identifier
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

# ─── Acceptable ranges for each parameter ────────────────────────────────────
PARAMETER_RANGES = {
    "ph": (0.0, 14.0),
    "turbidity_ntu": (0.0, 1000.0),
    "flow_rate_lps": (0.0, 10_000.0),
    "temperature_c": (-5.0, 60.0),
    "conductivity_us": (0.0, 50_000.0),
}

REQUIRED_COLUMNS = {"timestamp", "site_id", "instrument_id"}
SENSOR_COLUMNS = set(PARAMETER_RANGES.keys())


@dataclass
class ValidationReport:
    """Summary of validation results for a loaded dataset."""
    total_rows: int = 0
    valid_rows: int = 0
    invalid_rows: int = 0
    missing_columns: list = field(default_factory=list)
    out_of_range: dict = field(default_factory=dict)   # {column: count}
    warnings: list = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return not self.missing_columns and self.invalid_rows == 0

    def summary(self) -> str:
        lines = [
            f"Rows: {self.total_rows} total, {self.valid_rows} valid, {self.invalid_rows} invalid",
        ]
        if self.missing_columns:
            lines.append(f"Missing columns: {', '.join(self.missing_columns)}")
        for col, count in self.out_of_range.items():
            lines.append(f"Out-of-range values in '{col}': {count}")
        for w in self.warnings:
            lines.append(f"Warning: {w}")
        return "\n".join(lines)


class SensorDataReader:
    """
    Loads sensor data from CSV or JSON files and validates readings.

    Usage
    -----
    >>> reader = SensorDataReader("examples/sample_data.csv")
    >>> df = reader.load()
    >>> print(reader.validation_report.summary())
    """

    def __init__(self, file_path: str | Path):
        self.file_path = Path(file_path)
        self.validation_report = ValidationReport()
        self._df: Optional[pd.DataFrame] = None

    # ── Public API ────────────────────────────────────────────────────────────

    def load(self) -> pd.DataFrame:
        """Load and validate sensor data. Returns a clean DataFrame."""
        if not self.file_path.exists():
            raise FileNotFoundError(f"Data file not found: {self.file_path}")

        ext = self.file_path.suffix.lower()
        if ext == ".csv":
            df = self._load_csv()
        elif ext == ".json":
            df = self._load_json()
        else:
            raise ValueError(f"Unsupported file type '{ext}'. Use .csv or .json.")

        df = self._validate(df)
        self._df = df
        logger.info(
            "Loaded %d rows from %s — %s",
            len(df),
            self.file_path.name,
            self.validation_report.summary(),
        )
        return df

    def get_site_summary(self) -> pd.DataFrame:
        """Return per-site statistics for loaded data."""
        if self._df is None:
            raise RuntimeError("Call load() before get_site_summary().")
        numeric_cols = [c for c in SENSOR_COLUMNS if c in self._df.columns]
        return (
            self._df.groupby("site_id")[numeric_cols]
            .agg(["mean", "min", "max", "std"])
            .round(3)
        )

    def get_instrument_readings(self, instrument_id: str) -> pd.DataFrame:
        """Filter data for a specific instrument."""
        if self._df is None:
            raise RuntimeError("Call load() first.")
        mask = self._df["instrument_id"] == instrument_id
        return self._df[mask].copy()

    def to_dict_records(self) -> list[dict]:
        """Return sensor readings as a list of dicts (useful for Claude API)."""
        if self._df is None:
            raise RuntimeError("Call load() first.")
        return self._df.to_dict(orient="records")

    # ── Private helpers ───────────────────────────────────────────────────────

    def _load_csv(self) -> pd.DataFrame:
        logger.debug("Reading CSV: %s", self.file_path)
        return pd.read_csv(self.file_path, parse_dates=["timestamp"])

    def _load_json(self) -> pd.DataFrame:
        logger.debug("Reading JSON: %s", self.file_path)
        with open(self.file_path) as f:
            data = json.load(f)
        # Accept top-level list or {"readings": [...]}
        if isinstance(data, list):
            records = data
        elif isinstance(data, dict) and "readings" in data:
            records = data["readings"]
        else:
            raise ValueError("JSON must be a list of readings or {'readings': [...]}")
        df = pd.DataFrame(records)
        if "timestamp" in df.columns:
            df["timestamp"] = pd.to_datetime(df["timestamp"])
        return df

    def _validate(self, df: pd.DataFrame) -> pd.DataFrame:
        report = self.validation_report
        report.total_rows = len(df)

        # Check required columns
        missing = REQUIRED_COLUMNS - set(df.columns)
        if missing:
            report.missing_columns = sorted(missing)
            logger.warning("Missing required columns: %s", missing)

        # Warn about missing sensor columns
        present_sensors = SENSOR_COLUMNS & set(df.columns)
        absent_sensors = SENSOR_COLUMNS - present_sensors
        if absent_sensors:
            report.warnings.append(
                f"Sensor columns not found (will be ignored): {', '.join(sorted(absent_sensors))}"
            )

        # Out-of-range checks
        invalid_mask = pd.Series([False] * len(df), index=df.index)
        for col, (low, high) in PARAMETER_RANGES.items():
            if col not in df.columns:
                continue
            mask = df[col].notna() & ((df[col] < low) | (df[col] > high))
            count = mask.sum()
            if count:
                report.out_of_range[col] = int(count)
                logger.warning("%d out-of-range values in column '%s'", count, col)
                invalid_mask |= mask

        report.valid_rows = int((~invalid_mask).sum())
        report.invalid_rows = int(invalid_mask.sum())

        # Sort by timestamp if present
        if "timestamp" in df.columns:
            df = df.sort_values("timestamp").reset_index(drop=True)

        return df
