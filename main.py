"""
main.py
-------
CLI entry point for the Water Quality Report Automation System.

Usage examples
--------------
# Generate a report for a single CSV file:
python main.py generate --data examples/sample_data.csv --site SITE-01 --instrument FT-201

# Generate report for a specific instrument only:
python main.py generate --data examples/sample_data.csv --site SITE-01 --instrument FT-201 --format both

# Check calibration status for all instruments:
python main.py status

# Register a new instrument:
python main.py register --instrument FT-201 --site SITE-01 --type "Flow Meter" --interval 90

# Log a calibration event:
python main.py calibrate --instrument FT-201 --site SITE-01 --date 2024-11-15 --tech "Ethan Den Brok" --result PASS
"""

import argparse
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

# Load from .env or API.env (whichever exists)
load_dotenv(".env")
load_dotenv("API.env")

# ── Logging setup ─────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("wqra")


def cmd_generate(args):
    """Generate Word and/or PDF reports for sensor data."""
    from src.data_ingestion import SensorDataReader
    from src.claude_analysis import WaterQualityAnalyzer
    from src.report_generation import WordReportGenerator, PDFReportGenerator
    from src.compliance import CalibrationTracker

    tracker = CalibrationTracker(args.db)

    # ── Load data ──────────────────────────────────────────────────────────────
    logger.info("Loading sensor data from: %s", args.data)
    reader = SensorDataReader(args.data)
    df = reader.load()
    print(f"\n✓ Loaded {len(df)} rows")
    print(reader.validation_report.summary())

    # Filter to requested instrument if specified
    if args.instrument and "instrument_id" in df.columns:
        df = df[df["instrument_id"] == args.instrument].copy()
        if df.empty:
            print(f"✗ No data found for instrument '{args.instrument}'")
            sys.exit(1)

    # ── Claude analysis ────────────────────────────────────────────────────────
    logger.info("Running Claude analysis...")
    analyzer = WaterQualityAnalyzer()

    site_id = args.site or (df["site_id"].iloc[0] if "site_id" in df.columns else "UNKNOWN")
    instrument_id = args.instrument or (
        df["instrument_id"].iloc[0] if "instrument_id" in df.columns else "UNKNOWN"
    )

    # Look up last calibration date from the database
    cal_status = tracker.get_status(instrument_id)
    last_cal = cal_status.last_calibration_date if cal_status else None

    result = analyzer.analyze(
        df,
        site_id=site_id,
        instrument_id=instrument_id,
        last_calibration_date=last_cal,
    )
    print(f"\n✓ Claude analysis complete — calibration status: {result.calibration_status}")
    if result.anomalies:
        print(f"  ⚠ {len(result.anomalies)} anomalies detected")

    # ── Generate reports ───────────────────────────────────────────────────────
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = Path(args.output_dir)
    base_name = f"{site_id}_{instrument_id}_{timestamp}"

    word_path = pdf_path = None

    if args.format in ("word", "both"):
        word_path = output_dir / f"{base_name}.docx"
        gen = WordReportGenerator()
        gen.generate(
            analysis_result=result,
            df=df,
            site_id=site_id,
            instrument_id=instrument_id,
            output_path=word_path,
            technician_name=args.technician,
            include_raw_data=args.include_raw,
        )
        print(f"\n✓ Word report: {word_path}")

    if args.format in ("pdf", "both"):
        pdf_path = output_dir / f"{base_name}.pdf"
        gen = PDFReportGenerator()
        gen.generate(
            analysis_result=result,
            df=df,
            site_id=site_id,
            instrument_id=instrument_id,
            output_path=pdf_path,
            technician_name=args.technician,
            include_raw_data=args.include_raw,
        )
        print(f"✓ PDF report:  {pdf_path}")

    # Log report to database
    tracker.record_report(instrument_id, site_id, word_path, pdf_path)

    print("\n✓ Done.")


def cmd_status(args):
    """Print calibration status for all instruments."""
    from src.compliance import CalibrationTracker

    tracker = CalibrationTracker(args.db)
    statuses = tracker.get_status_all()

    if not statuses:
        print("No instruments registered. Use 'register' to add one.")
        return

    STATUS_ICONS = {"OK": "✓", "DUE": "⚠", "OVERDUE": "✗", "NEVER_CALIBRATED": "?"}
    print(f"\n{'Instrument':<15} {'Site':<12} {'Status':<18} {'Last Cal':<14} {'Next Due':<14} {'Days Since'}")
    print("-" * 90)
    for s in statuses:
        icon = STATUS_ICONS.get(s.status, "?")
        print(
            f"{icon} {s.instrument_id:<13} {s.site_id:<12} {s.status:<18} "
            f"{s.last_calibration_date or 'Never':<14} "
            f"{s.next_due_date or 'ASAP':<14} "
            f"{s.days_since_calibration if s.days_since_calibration is not None else '-'}"
        )

    overdue = [s for s in statuses if s.status in ("OVERDUE", "NEVER_CALIBRATED")]
    if overdue:
        print(f"\n⚠  {len(overdue)} instrument(s) require immediate attention.")


def cmd_register(args):
    """Register a new instrument in the database."""
    from src.compliance import CalibrationTracker

    tracker = CalibrationTracker(args.db)
    tracker.register_instrument(
        instrument_id=args.instrument,
        site_id=args.site,
        instrument_type=args.type,
        description=args.description,
        calibration_interval_days=args.interval,
    )
    print(f"✓ Registered instrument '{args.instrument}' at site '{args.site}' "
          f"(interval: {args.interval} days)")


def cmd_calibrate(args):
    """Record a calibration event."""
    from src.compliance import CalibrationTracker

    tracker = CalibrationTracker(args.db)
    event_id = tracker.record_calibration(
        instrument_id=args.instrument,
        site_id=args.site,
        calibration_date=args.date,
        technician=args.tech,
        result=args.result,
        notes=args.notes,
    )
    print(f"✓ Calibration recorded (event #{event_id}) — {args.instrument} {args.result} on {args.date}")


# ── Argument parser ────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="wqra",
        description="Water Quality Report Automation System — powered by Claude AI",
    )
    parser.add_argument(
        "--db",
        default="data/calibration.db",
        help="Path to SQLite database (default: data/calibration.db)",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    # ── generate ──────────────────────────────────────────────────────────────
    gen_p = sub.add_parser("generate", help="Generate a water quality report")
    gen_p.add_argument("--data", required=True, help="Path to sensor data file (.csv or .json)")
    gen_p.add_argument("--site", help="Site ID (auto-detected from data if not specified)")
    gen_p.add_argument("--instrument", help="Instrument ID to report on")
    gen_p.add_argument(
        "--format",
        choices=["word", "pdf", "both"],
        default="both",
        help="Report output format (default: both)",
    )
    gen_p.add_argument(
        "--output-dir",
        default="examples/generated_reports",
        help="Output directory for reports",
    )
    gen_p.add_argument("--technician", default="Field Technician", help="Technician name for sign-off")
    gen_p.add_argument("--include-raw", action="store_true", help="Append raw data table to report")
    gen_p.set_defaults(func=cmd_generate)

    # ── status ────────────────────────────────────────────────────────────────
    status_p = sub.add_parser("status", help="Show calibration status for all instruments")
    status_p.set_defaults(func=cmd_status)

    # ── register ──────────────────────────────────────────────────────────────
    reg_p = sub.add_parser("register", help="Register a new instrument")
    reg_p.add_argument("--instrument", required=True, help="Instrument ID")
    reg_p.add_argument("--site", required=True, help="Site ID")
    reg_p.add_argument("--type", default="Unknown", help="Instrument type (e.g. 'Flow Meter')")
    reg_p.add_argument("--description", default="", help="Free-text description")
    reg_p.add_argument("--interval", type=int, default=90, help="Calibration interval in days")
    reg_p.set_defaults(func=cmd_register)

    # ── calibrate ─────────────────────────────────────────────────────────────
    cal_p = sub.add_parser("calibrate", help="Record a calibration event")
    cal_p.add_argument("--instrument", required=True, help="Instrument ID")
    cal_p.add_argument("--site", required=True, help="Site ID")
    cal_p.add_argument("--date", required=True, help="Calibration date (YYYY-MM-DD)")
    cal_p.add_argument("--tech", required=True, help="Technician name")
    cal_p.add_argument(
        "--result", choices=["PASS", "FAIL", "ADJUSTED"], default="PASS"
    )
    cal_p.add_argument("--notes", default="", help="Additional notes")
    cal_p.set_defaults(func=cmd_calibrate)

    return parser


if __name__ == "__main__":
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)
