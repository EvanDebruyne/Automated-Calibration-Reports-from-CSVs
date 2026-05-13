# Automated Calibration Reports from CSVs

Generates professional Word and PDF calibration reports from raw sensor data using the Claude AI API. Point it at a CSV and it produces a formatted report with an AI-written summary, time-series graphs, anomaly detection, and calibration service notes.

Works well for:

- **Turbidimeters** — NTU readings, primary/secondary standard calibrations, optical component inspection
- **Flow meters** — GPM readings, totalizer values (handles comma-formatted numbers like `1,024,200`), drift detection
- **Temperature sensors** — readings displayed in °F, trend visualization over the logging period
- **Multi-parameter instruments** — any numeric columns in the CSV are automatically picked up and graphed

---

## Requirements

- Python 3.10+
- An [Anthropic API key](https://console.anthropic.com)

```bash
pip install -r requirements.txt
```

Add your API key to a `.env` file in the project root:

```
ANTHROPIC_API_KEY=your_key_here
```

---

## CSV Format

The tool requires three columns in every CSV — everything else is picked up automatically as sensor data:

| Column | Required | Description |
|--------|----------|-------------|
| `timestamp` | Yes | ISO 8601 format — `2024-11-01T06:00:00` |
| `site_id` | Yes | Site identifier — e.g. `SITE-01` |
| `instrument_id` | Yes | Instrument identifier — e.g. `FT-201` |
| *(any numeric column)* | No | Any sensor reading — pH, turbidity, pressure, flow, etc. |

**Example:**

```csv
timestamp,site_id,instrument_id,ph,turbidity_ntu,flow_rate_lps,temperature_c
2024-11-01T06:00:00,SITE-01,FT-201,7.2,0.4,125.3,18.2
2024-11-01T06:15:00,SITE-01,FT-201,7.3,0.5,124.8,18.3
```

Any numeric columns beyond the three required fields are automatically included in the report. There is no fixed list of accepted parameters — the system adapts to whatever data is in the file.

Two columns are converted to imperial units for display: `temperature_c` → °F and `flow_rate_lps` → GPM. All other columns are shown as-is.

---

## Generating a Report

```bash
python main.py generate --data examples/sample_data.csv --site SITE-01 --instrument FT-201
```

Options:

```
--data          Path to your CSV or JSON file
--site          Site ID
--instrument    Instrument ID to report on
--format        word | pdf | both  (default: both)
--output-dir    Where to save reports (default: examples/generated_reports)
--technician    Name shown on the sign-off line
--include-raw   Append the raw data table as an appendix
```

Reports are saved to `examples/generated_reports/` by default, named with the site, instrument, and timestamp.

---

## Calibration Tracking

Register instruments and log calibration events to a local SQLite database. The report header will automatically show whether calibration is current.

**Register an instrument:**
```bash
python main.py register --instrument FT-201 --site SITE-01 --type "Flow Meter" --interval 90
```

**Log a calibration:**
```bash
python main.py calibrate --instrument FT-201 --site SITE-01 --date 2024-11-15 --tech "Technician Name" --result PASS
```

**Check status of all instruments:**
```bash
python main.py status
```

---

## Report Contents

Each report contains:

- **Header** — site, instrument, report period, calibration status (colour coded)
- **Executive Summary** — AI-generated plain-English overview
- **Statistical Summary** — mean, min, max, std dev for all sensor columns
- **Detected Anomalies** — out-of-range readings with severity ratings
- **Calibration & Service Notes** — AI-generated fieldwork notes based on the data
- **Sign-off** — technician and reviewer fields

---

## Tech Stack

- [Anthropic Claude API](https://docs.anthropic.com) — analysis and report text
- pandas — data ingestion and statistics
- python-docx — Word report generation
- ReportLab — PDF report generation
- SQLite — calibration history tracking

---

## License

MIT
