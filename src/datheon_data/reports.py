"""PDF exports for the methodology note and research tearsheet."""

from __future__ import annotations

from io import BytesIO
from math import isfinite

import pandas as pd


NAVY = "#102039"
BLUE = "#0078B8"
GRAY = "#5C6D83"
PALE = "#EAF4FA"


def _styles():
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="DatheonTitle", parent=styles["Title"],
                              fontName="Helvetica-Bold", fontSize=20, leading=24,
                              textColor=colors.HexColor(NAVY), spaceAfter=11))
    styles.add(ParagraphStyle(name="DatheonSubtitle", parent=styles["Normal"],
                              fontName="Helvetica", fontSize=9, leading=13,
                              textColor=colors.HexColor(GRAY), spaceAfter=13))
    styles.add(ParagraphStyle(name="DatheonH1", parent=styles["Heading1"],
                              fontName="Helvetica-Bold", fontSize=12.5, leading=16,
                              textColor=colors.HexColor(NAVY), spaceBefore=15, spaceAfter=7,
                              keepWithNext=True))
    styles.add(ParagraphStyle(name="DatheonH2", parent=styles["Heading2"],
                              fontName="Helvetica-Bold", fontSize=10, leading=14,
                              textColor=colors.HexColor(BLUE), spaceBefore=10, spaceAfter=5,
                              keepWithNext=True))
    styles.add(ParagraphStyle(name="DatheonBody", parent=styles["BodyText"],
                              fontName="Helvetica", fontSize=9.3, leading=14,
                              textColor=colors.HexColor(NAVY), spaceAfter=7))
    styles.add(ParagraphStyle(name="DatheonBullet", parent=styles["BodyText"],
                              fontName="Helvetica", fontSize=9.3, leading=14,
                              leftIndent=14, firstLineIndent=-8,
                              textColor=colors.HexColor(NAVY), spaceAfter=5))
    return styles


def _footer(canvas, doc):
    from reportlab.lib import colors
    canvas.saveState()
    width, _ = doc.pagesize
    canvas.setStrokeColor(colors.HexColor("#D5E4EF"))
    canvas.line(doc.leftMargin, 36, width - doc.rightMargin, 36)
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(colors.HexColor(GRAY))
    canvas.drawString(doc.leftMargin, 24, "DATHEON  /  QUANTITATIVE RESEARCH")
    canvas.drawRightString(width - doc.rightMargin, 24, f"Page {doc.page}")
    canvas.restoreState()


def _document(buffer: BytesIO):
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import SimpleDocTemplate
    return SimpleDocTemplate(buffer, pagesize=A4, leftMargin=42, rightMargin=42,
                             topMargin=45, bottomMargin=52,
                             title="Datheon Strategy Research")


def render_whitepaper_pdf(markdown: str) -> bytes:
    """Render the repo's plain-Markdown methodology note to a paginated PDF."""
    from xml.sax.saxutils import escape
    from reportlab.platypus import Paragraph, Spacer

    styles = _styles()
    story = []
    for raw in markdown.splitlines():
        line = raw.strip()
        if not line:
            story.append(Spacer(1, 4))
        elif line.startswith("# "):
            story.append(Paragraph(escape(line[2:]), styles["DatheonTitle"]))
        elif line.startswith("## "):
            story.append(Paragraph(escape(line[3:]), styles["DatheonH1"]))
        elif line.startswith("### "):
            story.append(Paragraph(escape(line[4:]), styles["DatheonH2"]))
        elif line.startswith("- "):
            story.append(Paragraph("&#8226; " + escape(line[2:]), styles["DatheonBullet"]))
        else:
            story.append(Paragraph(escape(line), styles["DatheonBody"]))
    buffer = BytesIO()
    doc = _document(buffer)
    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return buffer.getvalue()


def render_tearsheet_pdf(report: dict[str, object], comparison: pd.DataFrame) -> bytes:
    """Render a compact, clearly sourced performance summary."""
    from reportlab.lib import colors
    from reportlab.platypus import Flowable, Paragraph, Spacer, Table, TableStyle

    styles = _styles()
    metrics = report["performance"]
    mc = report["monte_carlo"]
    assert isinstance(metrics, dict) and isinstance(mc, dict)

    class ReturnChart(Flowable):
        def __init__(self, frame: pd.DataFrame):
            Flowable.__init__(self)
            self.frame = frame
            self.width, self.height = 505, 180

        def draw(self):
            canvas = self.canv
            left, bottom, width, height = 35, 27, 455, 125
            values = self.frame[["strategy", "benchmark"]].div(float(report["execution_parameters"]["initial_capital"])).sub(1).mul(100)
            low = min(0.0, float(values.min().min()))
            high = max(0.0, float(values.max().max()))
            pad = max(2.0, (high - low) * 0.1)
            low, high = low - pad, high + pad
            canvas.setFont("Helvetica-Bold", 9)
            canvas.setFillColor(colors.HexColor(NAVY))
            canvas.drawString(left, 164, "Cumulative total return (%)")
            canvas.setStrokeColor(colors.HexColor("#D5E4EF"))
            for j in range(4):
                y = bottom + height * j / 3
                canvas.line(left, y, left + width, y)
                label = low + (high - low) * j / 3
                canvas.setFont("Helvetica", 7)
                canvas.setFillColor(colors.HexColor(GRAY))
                canvas.drawRightString(left - 4, y - 2, f"{label:.0f}")
            for column, color in (("strategy", BLUE), ("benchmark", GRAY)):
                series = values[column].to_numpy(dtype=float)
                path = canvas.beginPath()
                for i, value in enumerate(series):
                    x = left + width * i / max(1, len(series) - 1)
                    y = bottom + height * (value - low) / (high - low)
                    if i == 0:
                        path.moveTo(x, y)
                    else:
                        path.lineTo(x, y)
                canvas.setStrokeColor(colors.HexColor(color))
                canvas.setLineWidth(1.5)
                canvas.drawPath(path)
            canvas.setFont("Helvetica", 7.5)
            canvas.setFillColor(colors.HexColor(BLUE))
            canvas.drawString(left, 8, "Strategy")
            canvas.setFillColor(colors.HexColor(GRAY))
            canvas.drawString(left + 68, 8, str(report["benchmark"]) + " buy-and-hold")

    def pct(value):
        return "n/a" if value is None else f"{value:.1%}"

    def number(value):
        return "n/a" if value is None or not isfinite(value) else f"{value:.2f}"

    story = [Paragraph("Strategy Performance Tearsheet", styles["DatheonTitle"]),
             Paragraph(f"{report['ticker']}  |  {str(report['strategy']).replace('_', ' ').title()}  |  {report['start']} to {report['end']}",
                       styles["DatheonSubtitle"])]
    if report.get("synthetic_demo"):
        warning = Table([[Paragraph("SYNTHETIC DEMONSTRATION - NOT HISTORICAL MARKET PERFORMANCE",
                                    styles["DatheonBody"])]], colWidths=[505])
        warning.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(PALE)),
                                     ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor(BLUE)),
                                     ("LEFTPADDING", (0, 0), (-1, -1), 10),
                                     ("TOPPADDING", (0, 0), (-1, -1), 8)]))
        story += [warning, Spacer(1, 11)]
    kpis = [
        ["NET RETURN", "SHARPE", "MAX DRAWDOWN", "BOOTSTRAP RUIN"],
        [pct(metrics["total_return"]), number(metrics["sharpe_ratio"]),
         pct(metrics["maximum_drawdown"]), pct(mc["probability_of_ruin"])],
    ]
    table = Table(kpis, colWidths=[126] * 4, rowHeights=[22, 35])
    table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F3F7FA")),
                               ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor(GRAY)),
                               ("TEXTCOLOR", (0, 1), (-1, 1), colors.HexColor(NAVY)),
                               ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                               ("FONTNAME", (0, 1), (-1, 1), "Helvetica-Bold"),
                               ("FONTSIZE", (0, 0), (-1, 0), 7),
                               ("FONTSIZE", (0, 1), (-1, 1), 15),
                               ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                               ("LEFTPADDING", (0, 0), (-1, -1), 10)]))
    story += [table, Spacer(1, 14), ReturnChart(comparison), Spacer(1, 8),
              Paragraph("Risk and execution", styles["DatheonH1"])]
    rows = [
        ["Annualized return", pct(metrics["annualized_return"]),
         "Sortino ratio", number(metrics["sortino_ratio"])],
        ["Calmar ratio", number(metrics["calmar_ratio"]),
         "Max DD duration", f"{metrics['maximum_drawdown_duration_bars']} bars"],
        ["Traded notional", f"${metrics.get('total_traded_notional', 0):,.0f}",
         "Ending equity", f"${metrics['ending_equity']:,.0f}"],
        ["Spread + impact", f"${sum(metrics.get('total_' + key, 0) for key in ('spread_cost', 'linear_impact_cost', 'sqrt_impact_cost')):,.2f}",
         "Commission + borrow", f"${sum(metrics.get('total_' + key, 0) for key in ('commission', 'borrow_fee')):,.2f}"],
    ]
    details = Table(rows, colWidths=[120, 132, 120, 132], rowHeights=24)
    details.setStyle(TableStyle([("ROWBACKGROUNDS", (0, 0), (-1, -1),
                                  [colors.white, colors.HexColor("#F3F7FA")]),
                                 ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor(NAVY)),
                                 ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                                 ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
                                 ("FONTSIZE", (0, 0), (-1, -1), 8),
                                 ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                                 ("LEFTPADDING", (0, 0), (-1, -1), 7)]))
    story += [details, Spacer(1, 10),
              Paragraph("Methodology note", styles["DatheonH1"]),
              Paragraph("Signals use only prior-bar information. Orders are simulated at the next adjusted open with spread, volume-dependent impact, commissions, participation limits, and short borrow fees. The benchmark is buy-and-hold on adjusted close. Bootstrap ruin is the share of resampled net-return paths crossing half of initial capital; it is not a forecast.", styles["DatheonBody"]),
              Paragraph(f"Data: {report['source']}  |  Frequency: {report['frequency']}  |  Benchmark: {report['benchmark']}  |  Monte Carlo paths: {mc['paths']}", styles["DatheonSubtitle"])]
    buffer = BytesIO()
    doc = _document(buffer)
    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return buffer.getvalue()
