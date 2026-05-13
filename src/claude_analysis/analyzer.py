"""
analyzer.py
-----------
Uses the Claude API to analyse water quality sensor data and produce:
  - Anomaly detection with explanations
  - Natural language executive summary
  - Calibration status assessment
  - Corrective action recommendations

Requires ANTHROPIC_API_KEY in the environment (or .env file).
"""

import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Optional

import anthropic
import pandas as pd

logger = logging.getLogger(__name__)

# Default model — swap for claude-opus-4-6 for higher reasoning depth
DEFAULT_MODEL = "claude-sonnet-4-6"

# Regulatory limits used in the prompt context (Australian Drinking Water Guidelines / EPA)
REGULATORY_CONTEXT = """
Australian Drinking Water Guidelines (ADWG) / typical EPA limits for reference:
- pH: 6.5–8.5 (aesthetic), 6.0–9.5 (health guidance)
- Turbidity: <1 NTU (treated), <5 NTU (source water target)
- Temperature: <25°C (aesthetic preference)
- Conductivity: <2500 µS/cm (aesthetic)
These are guidance values. Actual limits depend on the jurisdiction and licence conditions.
"""


@dataclass
class AnalysisResult:
    """Structured output from Claude's analysis of sensor data."""
    executive_summary: str = ""
    anomalies: list[dict] = field(default_factory=list)       # [{parameter, value, timestamp, severity, explanation}]
    calibration_status: str = ""                               # "OK" | "DUE" | "OVERDUE" | "SUSPECTED_DRIFT"
    corrective_actions: list[str] = field(default_factory=list)
    compliance_notes: str = ""
    raw_response: str = ""                                     # Full Claude response for audit trail


class WaterQualityAnalyzer:
    """
    Sends sensor data to the Claude API and returns a structured AnalysisResult.

    Usage
    -----
    >>> analyzer = WaterQualityAnalyzer()
    >>> result = analyzer.analyze(df, site_id="SITE-01", instrument_id="FT-201")
    >>> print(result.executive_summary)
    """

    def __init__(self, model: str = DEFAULT_MODEL, api_key: Optional[str] = None):
        key = api_key or os.getenv("ANTHROPIC_API_KEY")
        if not key:
            raise EnvironmentError(
                "ANTHROPIC_API_KEY not set. Add it to your .env file or environment."
            )
        self.client = anthropic.Anthropic(api_key=key)
        self.model = model

    # ── Public API ────────────────────────────────────────────────────────────

    def analyze(
        self,
        df: pd.DataFrame,
        site_id: str,
        instrument_id: str,
        last_calibration_date: Optional[str] = None,
        calibration_interval_days: int = 90,
    ) -> AnalysisResult:
        """
        Analyse sensor readings and return an AnalysisResult.

        Parameters
        ----------
        df                       : DataFrame of sensor readings for this instrument
        site_id                  : Monitoring site identifier
        instrument_id            : Instrument/sensor identifier
        last_calibration_date    : ISO date of last calibration, or None
        calibration_interval_days: Maximum days between calibrations
        """
        prompt = self._build_prompt(
            df, site_id, instrument_id, last_calibration_date, calibration_interval_days
        )
        logger.info("Sending %d readings to Claude for %s / %s", len(df), site_id, instrument_id)

        # Retry up to 3 times on transient server errors
        last_error = None
        for attempt in range(1, 4):
            try:
                message = self.client.messages.create(
                    model=self.model,
                    max_tokens=2048,
                    messages=[{"role": "user", "content": prompt}],
                )
                raw = message.content[0].text
                logger.debug("Claude raw response:\n%s", raw)
                return self._parse_response(raw)
            except Exception as e:
                last_error = e
                if attempt < 3 and "500" in str(e):
                    wait = attempt * 5
                    logger.warning("API error (attempt %d/3), retrying in %ds: %s", attempt, wait, e)
                    time.sleep(wait)
                else:
                    raise
        raise last_error

    def analyze_batch(
        self,
        df: pd.DataFrame,
        calibration_records: Optional[list[dict]] = None,
    ) -> dict[str, AnalysisResult]:
        """
        Run analysis for every unique (site_id, instrument_id) pair in the DataFrame.

        Returns a dict keyed by "SITE_ID/INSTRUMENT_ID".
        """
        results = {}
        cal_lookup = {}
        if calibration_records:
            for rec in calibration_records:
                key = f"{rec.get('site_id','')}/{rec.get('instrument_id','')}"
                cal_lookup[key] = rec.get("last_calibration_date")

        groups = df.groupby(["site_id", "instrument_id"])
        for (site_id, instrument_id), group_df in groups:
            key = f"{site_id}/{instrument_id}"
            last_cal = cal_lookup.get(key)
            results[key] = self.analyze(group_df, site_id, instrument_id, last_cal)

        return results

    # ── Private helpers ───────────────────────────────────────────────────────

    def _build_prompt(
        self,
        df: pd.DataFrame,
        site_id: str,
        instrument_id: str,
        last_calibration_date: Optional[str],
        calibration_interval_days: int,
    ) -> str:
        # Compute basic stats to include in the prompt
        numeric_cols = df.select_dtypes(include="number").columns.tolist()
        stats = df[numeric_cols].describe().round(3).to_string() if numeric_cols else "No numeric columns."

        # Sample up to 20 rows so the prompt stays concise
        sample = df.head(20).to_csv(index=False)

        cal_info = (
            f"Last calibration: {last_calibration_date} "
            f"(interval target: every {calibration_interval_days} days)"
            if last_calibration_date
            else "Last calibration date: UNKNOWN"
        )

        return f"""You are an expert water quality engineer reviewing sensor data from a monitoring site.

Site ID: {site_id}
Instrument ID: {instrument_id}
{cal_info}
Date range: {df['timestamp'].min() if 'timestamp' in df.columns else 'N/A'} to {df['timestamp'].max() if 'timestamp' in df.columns else 'N/A'}
Total readings: {len(df)}

{REGULATORY_CONTEXT}

--- STATISTICAL SUMMARY ---
{stats}

--- SAMPLE READINGS (up to 50 rows) ---
{sample}

Please analyse the data and respond in the following JSON format only (no markdown, no preamble).
Keep all text fields concise — the report must fit on one page.

{{
  "executive_summary": "2-3 sentences max. Overall water quality and instrument performance.",
  "anomalies": [
    {{
      "parameter": "ph",
      "value": 9.8,
      "timestamp": "2024-03-15T14:30:00",
      "severity": "HIGH",
      "explanation": "One sentence max."
    }}
  ],
  "calibration_status": "OK",
  "corrective_actions": [
    "List the calibration and service work performed on the instrument. Examples of the kind of notes to include: turbidimeter calibrated using primary and secondary standards (note pass/fail), optical components inspected (bulb/laser sensor condition noted), flow meter zero/span checked and adjusted, sensor cleaned and flushed, worn parts replaced, troubleshooting steps taken for erratic readings. Keep each item to one concise sentence. Max 5 items."
  ]
}}

Severity levels: LOW, MEDIUM, HIGH, CRITICAL.
calibration_status options: OK, DUE, OVERDUE, SUSPECTED_DRIFT.
Return ONLY valid JSON."""

    @staticmethod
    def _parse_response(raw: str) -> AnalysisResult:
        result = AnalysisResult(raw_response=raw)
        try:
            # Strip any accidental markdown fences
            clean = raw.strip()
            if clean.startswith("```"):
                clean = clean.split("```")[1]
                if clean.startswith("json"):
                    clean = clean[4:]
            data = json.loads(clean)
            result.executive_summary = data.get("executive_summary", "")
            result.anomalies = data.get("anomalies", [])
            result.calibration_status = data.get("calibration_status", "OK")
            result.corrective_actions = data.get("corrective_actions", [])
            result.compliance_notes = data.get("compliance_notes", "")
        except json.JSONDecodeError as e:
            logger.error("Failed to parse Claude response as JSON: %s", e)
            result.executive_summary = raw  # Fall back to raw text
        return result
