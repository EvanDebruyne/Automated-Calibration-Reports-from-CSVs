"""
pdf_report.py
-------------
Generates a professional calibration & water quality PDF report
using ReportLab's Platypus high-level layout engine.

Mirrors the sections in word_report.py so both outputs stay in sync.
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    PageBreak,
    HRFlowable,
    Image,
)

LOGO_PATH = Path(__file__).parent.parent.parent / "templates" / "aquasummit_logo.png"

from src.claude_analysis.analyzer import AnalysisResult

logger = logging.getLogger(__name__)

# ── Unit conversion helpers ───────────────────────────────────────────────────
_COL_LABELS = {
    "ph":               "pH",
    "turbidity_ntu":    "Turbidity (NTU)",
    "flow_rate_lps":    "Flow Rate (GPM)",
    "temperature_c":    "Temperature (°F)",
    "conductivity_us":  "Conductivity (µS/cm)",
}

def _display_col(col: str) -> str:
    return _COL_LABELS.get(col, col.replace("_", " ").title())

def _convert_units(df):
    d = df.copy()
    if "temperature_c" in d.columns:
        d["temperature_c"] = (d["temperature_c"] * 9 / 5 + 32).round(2)
    if "flow_rate_lps" in d.columns:
        d["flow_rate_lps"] = (d["flow_rate_lps"] * 15.8503).round(2)
    return d.rename(columns=_COL_LABELS)

def _get_numeric_cols(df):
    skip = {"site_id", "instrument_id", "timestamp"}
    return [c for c in df.select_dtypes(include="number").columns if c not in skip]

# ── Palette ───────────────────────────────────────────────────────────────────
BLUE_DARK = colors.HexColor("#1A578A")
BLUE_MID = colors.HexColor("#2E75B6")
BLUE_LIGHT = colors.HexColor("#D9E8F5")
RED = colors.HexColor("#C00000")
ORANGE = colors.HexColor("#FFA500")
YELLOW_LIGHT = colors.HexColor("#FFF2CC")
GREEN = colors.HexColor("#00B050")
GREY = colors.HexColor("#7F7F7F")

SEVERITY_COLOURS = {
    "CRITICAL": colors.HexColor("#C00000"),
    "HIGH": colors.red,
    "MEDIUM": ORANGE,
    "LOW": colors.HexColor("#0070C0"),
}
STATUS_COLOURS = {
    "OK": GREEN,
    "DUE": ORANGE,
    "OVERDUE": colors.red,
    "SUSPECTED_DRIFT": RED,
    "UNKNOWN": GREY,
}


class PDFReportGenerator:
    """
    Builds a .pdf water quality report.

    Usage
    -----
    >>> gen = PDFReportGenerator()
    >>> path = gen.generate(
    ...     analysis_result=result,
    ...     df=df,
    ...     site_id="SITE-01",
    ...     instrument_id="FT-201",
    ...     output_path="examples/generated_reports/report.pdf",
    ... )
    """

    def __init__(self):
        self.styles = self._build_styles()

    def generate(
        self,
        analysis_result: AnalysisResult,
        df: pd.DataFrame,
        site_id: str,
        instrument_id: str,
        output_path: str | Path,
        technician_name: str = "Field Technician",
        include_raw_data: bool = False,
    ) -> Path:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        doc = SimpleDocTemplate(
            str(output_path),
            pagesize=letter,
            leftMargin=inch,
            rightMargin=inch,
            topMargin=inch,
            bottomMargin=inch,
        )

        story = []
        story += self._header_section(site_id, instrument_id, df, analysis_result)
        story += self._executive_summary_section(analysis_result)
        story += self._statistical_summary_section(df)
        story += self._anomalies_section(analysis_result)
        story += self._calibration_service_notes_section(analysis_result)
        story += self._sign_off_section(technician_name)

        if include_raw_data:
            story.append(PageBreak())
            story += self._raw_data_section(df)

        doc.build(story)
        logger.info("PDF report saved: %s", output_path)
        return output_path

    # ── Sections ──────────────────────────────────────────────────────────────

    def _header_section(self, site_id, instrument_id, df, result):
        s = self.styles
        elems = []

        elems.append(Spacer(1, 0.1 * inch))

        # Logo left, title right — side by side
        title_para = Paragraph("Water Quality Calibration Report", s["ReportTitle"])
        if LOGO_PATH.exists():
            logo = Image(str(LOGO_PATH), width=2.2 * inch, height=0.75 * inch)
            logo_title_data = [[logo, title_para]]
            logo_title_tbl = Table(logo_title_data, colWidths=[2.4 * inch, 4.1 * inch])
            logo_title_tbl.setStyle(TableStyle([
                ("ALIGN", (0, 0), (0, 0), "LEFT"),
                ("ALIGN", (1, 0), (1, 0), "RIGHT"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]))
            elems.append(logo_title_tbl)
        else:
            elems.append(title_para)

        elems.append(Spacer(1, 0.15 * inch))

        if "timestamp" in df.columns:
            date_from = pd.to_datetime(df["timestamp"]).min().strftime("%d %B %Y")
            date_to = pd.to_datetime(df["timestamp"]).max().strftime("%d %B %Y")
            period = f"{date_from} — {date_to}"
        else:
            period = "N/A"

        status = result.calibration_status or "UNKNOWN"
        STATUS_HEX = {
            "OK": "#00B050", "DUE": "#FFA500", "OVERDUE": "#FF0000",
            "SUSPECTED_DRIFT": "#C00000", "UNKNOWN": "#7F7F7F",
        }
        status_hex = STATUS_HEX.get(status, "#7F7F7F")

        # Info table: 4 columns — Site | Instrument | Period | Cal Status
        info_data = [
            ["Site", "Instrument", "Report Period", "Calibration Status"],
            [site_id, instrument_id, period,
             Paragraph(f'<font color="{status_hex}"><b>{status}</b></font>', s["BodyText"])],
        ]
        info_tbl = Table(info_data, colWidths=[1.1 * inch, 1.2 * inch, 2.6 * inch, 1.6 * inch])
        info_tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), BLUE_MID),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("BACKGROUND", (0, 1), (-1, 1), BLUE_LIGHT),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        elems.append(info_tbl)
        elems.append(Paragraph(
            f"Generated: {datetime.now().strftime('%d %B %Y %H:%M')}",
            s["SubtitleSmall"]
        ))
        elems.append(HRFlowable(width="100%", thickness=2, color=BLUE_DARK, spaceAfter=10))
        return elems

    def _executive_summary_section(self, result):
        elems = [Paragraph("Executive Summary", self.styles["SectionHeading"]),
                 HRFlowable(width="100%", thickness=1, color=BLUE_MID, spaceAfter=6)]
        elems.append(Paragraph(result.executive_summary or "No summary available.", self.styles["BodyText"]))
        elems.append(Spacer(1, 0.2 * inch))
        return elems

    def _statistical_summary_section(self, df):
        elems = [Paragraph("Statistical Summary", self.styles["SectionHeading"]),
                 HRFlowable(width="100%", thickness=1, color=BLUE_MID, spaceAfter=6)]

        numeric_cols = _get_numeric_cols(df)
        if not numeric_cols:
            elems.append(Paragraph("No numeric sensor data available.", self.styles["BodyText"]))
            elems.append(Spacer(1, 0.2 * inch))
            return elems

        display_df = _convert_units(df)
        display_cols = [_display_col(c) for c in numeric_cols]
        stats = display_df[display_cols].describe().loc[["mean", "min", "max", "std"]].round(2)

        data = [["Statistic"] + display_cols]
        stat_label_map = {"mean": "Mean", "min": "Minimum", "max": "Maximum", "std": "Std Dev"}
        for stat_name, row in stats.iterrows():
            data.append([stat_label_map.get(stat_name, stat_name)] + [str(v) for v in row.values])

        col_width = (6.5 * inch) / len(data[0])
        tbl = Table(data, colWidths=[col_width] * len(data[0]))
        tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), BLUE_MID),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [BLUE_LIGHT, colors.white]),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("ALIGN", (1, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        elems.append(tbl)
        elems.append(Spacer(1, 0.2 * inch))
        return elems

    def _anomalies_section(self, result):
        elems = [Paragraph("Detected Anomalies", self.styles["SectionHeading"]),
                 HRFlowable(width="100%", thickness=1, color=BLUE_MID, spaceAfter=6)]

        if not result.anomalies:
            elems.append(Paragraph("No anomalies detected in the review period.", self.styles["BodyText"]))
            elems.append(Spacer(1, 0.2 * inch))
            return elems

        data = [["Timestamp", "Parameter", "Value", "Severity"]]
        for a in result.anomalies:
            data.append([
                str(a.get("timestamp", "")),
                a.get("parameter", "").replace("_", " ").title(),
                str(a.get("value", "")),
                a.get("severity", ""),
            ])

        col_widths = [1.9 * inch, 1.7 * inch, 1.2 * inch, 1.7 * inch]
        tbl = Table(data, colWidths=col_widths, repeatRows=1)

        style_cmds = [
            ("BACKGROUND", (0, 0), (-1, 0), BLUE_MID),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]
        for r_idx, a in enumerate(result.anomalies, start=1):
            sev = a.get("severity", "LOW")
            if sev in ("HIGH", "CRITICAL"):
                style_cmds.append(("BACKGROUND", (0, r_idx), (-1, r_idx), YELLOW_LIGHT))
            text_colour = SEVERITY_COLOURS.get(sev, colors.black)
            style_cmds.append(("TEXTCOLOR", (3, r_idx), (3, r_idx), text_colour))
            style_cmds.append(("FONTNAME", (3, r_idx), (3, r_idx), "Helvetica-Bold"))

        tbl.setStyle(TableStyle(style_cmds))
        elems.append(tbl)
        elems.append(Spacer(1, 0.2 * inch))
        return elems

    def _calibration_service_notes_section(self, result):
        elems = [Paragraph("Calibration &amp; Service Notes", self.styles["SectionHeading"]),
                 HRFlowable(width="100%", thickness=1, color=BLUE_MID, spaceAfter=6)]
        if not result.corrective_actions:
            elems.append(Paragraph("No service actions recorded.", self.styles["BodyText"]))
        else:
            for action in result.corrective_actions:
                elems.append(Paragraph(f"• {action}", self.styles["BulletText"]))
        elems.append(Spacer(1, 0.2 * inch))
        return elems

    def _sign_off_section(self, technician_name):
        elems = [Paragraph("Report Sign-Off", self.styles["SectionHeading"]),
                 HRFlowable(width="100%", thickness=1, color=BLUE_MID, spaceAfter=6)]
        sign_off_data = [
            ["Prepared by:", technician_name],
            ["Reviewed by:", ""],
            ["Date:", ""],
        ]
        tbl = Table(sign_off_data, colWidths=[1.5 * inch, 5.0 * inch])
        tbl.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 10),
            ("LINEBELOW", (1, 0), (1, -1), 0.5, colors.grey),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        elems.append(tbl)
        return elems

    def _raw_data_section(self, df):
        elems = [Paragraph("Appendix — Raw Sensor Data", self.styles["SectionHeading"])]
        sample = df.head(200)
        data = [sample.columns.tolist()] + sample.values.tolist()
        data = [[str(v) for v in row] for row in data]
        col_width = 6.5 * inch / len(df.columns)
        tbl = Table(data, colWidths=[col_width] * len(df.columns), repeatRows=1)
        tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), BLUE_MID),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 7),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [BLUE_LIGHT, colors.white]),
            ("GRID", (0, 0), (-1, -1), 0.3, colors.grey),
        ]))
        elems.append(tbl)
        return elems

    # ── Style definitions ─────────────────────────────────────────────────────

    @staticmethod
    def _build_styles():
        base = getSampleStyleSheet()
        styles = {}

        styles["ReportTitle"] = ParagraphStyle(
            "ReportTitle",
            parent=base["Title"],
            fontName="Helvetica-Bold",
            fontSize=20,
            textColor=BLUE_DARK,
            alignment=1,  # centre
            spaceAfter=6,
        )
        styles["Subtitle"] = ParagraphStyle(
            "Subtitle",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=12,
            textColor=BLUE_MID,
            alignment=1,
            spaceAfter=4,
        )
        styles["SubtitleSmall"] = ParagraphStyle(
            "SubtitleSmall",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=10,
            textColor=colors.grey,
            alignment=1,
            spaceAfter=2,
        )
        styles["SectionHeading"] = ParagraphStyle(
            "SectionHeading",
            parent=base["Heading1"],
            fontName="Helvetica-Bold",
            fontSize=13,
            textColor=BLUE_DARK,
            spaceBefore=14,
            spaceAfter=4,
        )
        styles["BodyText"] = ParagraphStyle(
            "BodyText",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=10,
            leading=14,
            spaceAfter=4,
        )
        styles["BulletText"] = ParagraphStyle(
            "BulletText",
            parent=styles["BodyText"],
            leftIndent=12,
            spaceAfter=3,
        )
        return styles
