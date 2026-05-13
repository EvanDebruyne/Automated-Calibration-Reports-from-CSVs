# Water Quality Report Automation System

An intelligent tool that automatically generates professional calibration and water quality reports from raw sensor data — using Claude AI to analyse readings and produce compliance-ready Word and PDF documentation.

Built for water industry professionals who spend too much time manually writing reports that follow the same structure every time.

---

## Features

- **Automated report generation** — produces both `.docx` and `.pdf` reports from a single command
- **Claude AI analysis** — detects anomalies, summarises trends, assesses calibration drift, and recommends corrective actions in plain English
- **Multi-site, multi-instrument** support — handles data from flow meters, pH sensors, turbidity analysers, and more
- **Calibration history tracking** — SQLite database records every calibration event, flags overdue instruments, and tracks compliance
- **Flexible data input** — accepts CSV or JSON sensor logs
- **CLI interface** — clean terminal workflow for field technicians and engineers

---

## Project Structure

```
water-quality-report-automation/
├── src/
│   ├── data_ingestion/
│   │   └── sensor_reader.py     # Loads & validates CSV/JSON sensor data
│   ├── claude_analysis/
│   │   └── analyzer.py          # Claude API integration for intelligent analysis
│   ├── report_generation/
│   │   ├── word_report.py       # Generates .docx reports (python-docx)
│   │   └── pdf_report.py        # Generates .pdf reports (ReportLab)
│   └── compliance/
│       └── tracker.py           # SQLite calibration history & overdue alerts
├── examples/
│   ├── sample_data.csv          # Example sensor readings (2 sites, 2 instruments)
│   └── generated_reports/       # Output directory for generated reports
├── tests/
│   ├── test_sensor_reader.py
│   └── test_calibration_tracker.py
├── main.py                      # CLI entry point
├── requirements.txt
├── .env.example
└── README.md
```

---

## Quick Start

### 1. Clone and install dependencies

```bash
git clone https://github.com/yourusername/water-quality-report-automation.git
cd water-quality-report-automation
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Set up your API key

```bash
cp .env.example .env
# Edit .env and add your Anthropic API key
```

Get your API key at [console.anthropic.com](https://console.anthropic.com).

### 3. Generate your first report

```bash
python main.py generate --data examples/sample_data.csv --site SITE-01 --instrument FT-201
```

This will create both a Word and PDF report in `examples/generated_reports/`.

---

## CLI Reference

### Generate a report

```bash
python main.py generate \
  --data path/to/sensor_log.csv \
  --site SITE-01 \
  --instrument FT-201 \
  --format both \              # word | pdf | both
  --technician "Ethan Den Brok" \
  --output-dir examples/generated_reports
```

### Check calibration status

```bash
python main.py status
```

Output:
```
Instrument      Site         Status             Last Cal       Next Due       Days Since
------------------------------------------------------------------------------------------
✓ FT-201        SITE-01      OK                 2024-11-15     2025-02-13     90
⚠ PH-105        SITE-02      DUE                2024-08-10     2024-11-08     95
✗ TB-302        SITE-03      OVERDUE            2024-05-01     2024-07-30     197
```

### Register an instrument

```bash
python main.py register \
  --instrument FT-201 \
  --site SITE-01 \
  --type "Flow Meter" \
  --interval 90
```

### Record a calibration

```bash
python main.py calibrate \
  --instrument FT-201 \
  --site SITE-01 \
  --date 2024-11-15 \
  --tech "Ethan Den Brok" \
  --result PASS \
  --notes "Zero-point adjusted. Within 0.5% tolerance."
```

---

## Supported Sensor Parameters

| Column | Description | Unit | Typical Range |
|--------|-------------|------|---------------|
| `ph` | pH level | — | 6.5–8.5 (ADWG) |
| `turbidity_ntu` | Turbidity | NTU | < 1 NTU (treated) |
| `flow_rate_lps` | Flow rate | L/s | Site-specific |
| `temperature_c` | Temperature | °C | < 25°C |
| `conductivity_us` | Conductivity | µS/cm | < 2500 µS/cm |

---

## Input Format

### CSV

```csv
timestamp,site_id,instrument_id,ph,turbidity_ntu,flow_rate_lps,temperature_c,conductivity_us
2024-11-01T06:00:00,SITE-01,FT-201,7.2,0.4,125.3,18.2,450.1
```

### JSON

```json
[
  {
    "timestamp": "2024-11-01T06:00:00",
    "site_id": "SITE-01",
    "instrument_id": "FT-201",
    "ph": 7.2,
    "turbidity_ntu": 0.4,
    "flow_rate_lps": 125.3,
    "temperature_c": 18.2,
    "conductivity_us": 450.1
  }
]
```

---

## Report Contents

Each generated report includes:

1. **Cover information** — site, instrument, date range, generation timestamp
2. **Executive Summary** — Claude's plain-English assessment of overall water quality
3. **Statistical Summary** — mean, min, max, std dev for each parameter
4. **Detected Anomalies** — table of out-of-range readings with severity ratings (LOW / MEDIUM / HIGH / CRITICAL)
5. **Calibration Status** — OK / DUE / OVERDUE / SUSPECTED_DRIFT with colour coding
6. **Corrective Actions** — specific, actionable recommendations from Claude
7. **Compliance Notes** — regulatory context and licence condition assessment
8. **Sign-off section** — space for technician and reviewer signatures

---

## Tech Stack

| Component | Technology |
|-----------|------------|
| AI Analysis | Anthropic Claude API (`claude-sonnet-4-6`) |
| Data processing | pandas, numpy |
| Word reports | python-docx |
| PDF reports | ReportLab |
| Database | SQLite (via Python stdlib) |
| CLI | argparse |
| Environment | python-dotenv |

---

## Running Tests

```bash
pytest tests/ -v
pytest tests/ --cov=src --cov-report=term-missing
```

---

## Roadmap

- [ ] Email delivery of generated reports
- [ ] SCADA system integration (Modbus/OPC-UA data pull)
- [ ] Trend charting embedded in reports (matplotlib)
- [ ] Web dashboard for compliance overview
- [ ] Automated daily/weekly report scheduling

---

## Background

This project combines real water industry experience with Python automation and the Claude API. The sensor parameters, regulatory limits, and calibration workflows are based on practical field work with flow meters, pH analysers, and turbidity sensors in operational water treatment and distribution systems.

---

## License

MIT
