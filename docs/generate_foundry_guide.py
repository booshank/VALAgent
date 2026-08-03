#!/usr/bin/env python3
"""Generate VAL CoPilot Azure Foundry deployment guide (PDF + HTML) from Markdown."""

from __future__ import annotations

import html as html_mod
import re
from pathlib import Path

from reportlab.lib.colors import HexColor, white
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    HRFlowable,
    ListFlowable,
    ListItem,
    Paragraph,
    Preformatted,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

DOCS = Path(__file__).resolve().parent
PDF_PATH = DOCS / "VAL_CoPilot_Azure_Foundry_Deployment_Guide.pdf"
MD_PATH = DOCS / "VAL_CoPilot_Azure_Foundry_Deployment_Guide.md"
HTML_PATH = DOCS / "VAL_CoPilot_Azure_Foundry_Deployment_Guide.html"
ARTIFACT = Path("/opt/cursor/artifacts/VAL_CoPilot_Azure_Foundry_Deployment_Guide.pdf")

NAVY = HexColor("#0B1F33")
TEAL = HexColor("#0E6B6B")
SLATE = HexColor("#334155")
LIGHT = HexColor("#F1F5F9")
BORDER = HexColor("#CBD5E1")


def _inline_md_to_rl(text: str) -> str:
    """Convert limited markdown inline syntax to ReportLab XML."""
    text = html_mod.escape(text)
    text = re.sub(r"`([^`]+)`", r"<font face='Courier' size='9'>\1</font>", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<link href="\2">\1</link>', text)
    return text


def _build_pdf_from_markdown(md_text: str, path: Path) -> None:
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        name="CoverTitle", fontName="Helvetica-Bold", fontSize=20,
        textColor=NAVY, alignment=TA_CENTER, spaceAfter=8, leading=24,
    ))
    styles.add(ParagraphStyle(
        name="H1Custom", fontName="Helvetica-Bold", fontSize=13,
        textColor=NAVY, spaceBefore=14, spaceAfter=6, leading=16,
    ))
    styles.add(ParagraphStyle(
        name="H1Part", fontName="Helvetica-Bold", fontSize=14,
        textColor=TEAL, spaceBefore=16, spaceAfter=8, leading=18,
        backColor=LIGHT, borderPadding=4,
    ))
    styles.add(ParagraphStyle(
        name="H2Custom", fontName="Helvetica-Bold", fontSize=11,
        textColor=TEAL, spaceBefore=10, spaceAfter=4, leading=14,
    ))
    styles.add(ParagraphStyle(
        name="H3Custom", fontName="Helvetica-Bold", fontSize=10,
        textColor=SLATE, spaceBefore=8, spaceAfter=3, leading=13,
    ))
    styles.add(ParagraphStyle(
        name="BodyCustom", fontName="Helvetica", fontSize=9.5,
        textColor=SLATE, spaceAfter=5, leading=13, alignment=TA_LEFT,
    ))
    styles.add(ParagraphStyle(
        name="BulletBody", fontName="Helvetica", fontSize=9.5,
        textColor=SLATE, leading=12,
    ))
    styles.add(ParagraphStyle(
        name="CodeBlock", fontName="Courier", fontSize=8,
        textColor=NAVY, backColor=LIGHT, leading=10,
        leftIndent=4, rightIndent=4, spaceBefore=3, spaceAfter=6,
    ))
    styles.add(ParagraphStyle(
        name="Note", fontName="Helvetica-Oblique", fontSize=9,
        textColor=SLATE, leftIndent=6, spaceBefore=3, spaceAfter=6, leading=11,
    ))
    styles.add(ParagraphStyle(
        name="TableCell", fontName="Helvetica", fontSize=8,
        textColor=SLATE, leading=10,
    ))
    styles.add(ParagraphStyle(
        name="TableHeader", fontName="Helvetica-Bold", fontSize=8,
        textColor=white, leading=10,
    ))
    styles.add(ParagraphStyle(
        name="Footer", fontName="Helvetica", fontSize=8,
        textColor=HexColor("#64748B"), alignment=TA_CENTER,
    ))

    story: list = []
    story.append(Spacer(1, 0.3 * inch))
    story.append(Paragraph("VAL CoPilot", styles["CoverTitle"]))
    story.append(Paragraph("Azure AI Foundry Deployment Guide", styles["CoverTitle"]))
    story.append(HRFlowable(width="100%", thickness=1, color=TEAL, spaceBefore=4, spaceAfter=8))
    story.append(Paragraph(
        "Optional future path — current POC runs Streamlit → Flask → FastMCP → synthetic Gold",
        styles["Note"],
    ))
    story.append(Paragraph(
        "Part A = Azure Foundry portal steps &nbsp;&nbsp;|&nbsp;&nbsp; Part B = GitHub repo / deploy script",
        styles["BodyCustom"],
    ))
    story.append(Paragraph(
        "Complete <b>Part A</b> fully before running <font face='Courier'>deploy_to_foundry.py</font>.",
        styles["Note"],
    ))

    lines = md_text.splitlines()
    i = 0
    # Skip the top H1 (already used as cover)
    while i < len(lines) and not lines[i].startswith("# "):
        i += 1
    if i < len(lines) and lines[i].startswith("# "):
        i += 1

    in_code = False
    code_buf: list[str] = []
    table_rows: list[list[str]] = []

    def flush_code() -> None:
        nonlocal code_buf
        if not code_buf:
            return
        block = "\n".join(code_buf)
        story.append(Preformatted(block, styles["CodeBlock"]))
        code_buf = []

    def flush_table() -> None:
        nonlocal table_rows
        if not table_rows:
            return
        # Drop separator row (| --- |)
        data_rows = []
        for row in table_rows:
            if all(set(c.strip()) <= {"-", ":", " "} for c in row):
                continue
            data_rows.append(row)
        if not data_rows:
            table_rows = []
            return
        header, *body = data_rows
        rl_rows = [[Paragraph(_inline_md_to_rl(c), styles["TableHeader"]) for c in header]]
        for row in body:
            # pad/truncate to header width
            cells = (row + [""] * len(header))[: len(header)]
            rl_rows.append([Paragraph(_inline_md_to_rl(c), styles["TableCell"]) for c in cells])
        col_w = (letter[0] - 1.5 * inch) / max(len(header), 1)
        table = Table(rl_rows, colWidths=[col_w] * len(header))
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), NAVY),
            ("BACKGROUND", (0, 1), (-1, -1), LIGHT),
            ("GRID", (0, 0), (-1, -1), 0.4, BORDER),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(table)
        story.append(Spacer(1, 6))
        table_rows = []

    while i < len(lines):
        line = lines[i]
        if line.startswith("```"):
            flush_table()
            if not in_code:
                in_code = True
                code_buf = []
            else:
                in_code = False
                flush_code()
            i += 1
            continue
        if in_code:
            code_buf.append(line)
            i += 1
            continue

        if line.startswith("|"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            table_rows.append(cells)
            i += 1
            continue
        flush_table()

        if not line.strip():
            i += 1
            continue
        if line.strip() == "---":
            story.append(HRFlowable(width="100%", thickness=0.6, color=BORDER, spaceBefore=6, spaceAfter=6))
            i += 1
            continue

        if line.startswith("# PART ") or line.startswith("# Part "):
            story.append(Paragraph(_inline_md_to_rl(line.lstrip("# ").strip()), styles["H1Part"]))
            i += 1
            continue
        if line.startswith("### "):
            story.append(Paragraph(_inline_md_to_rl(line[4:].strip()), styles["H3Custom"]))
            i += 1
            continue
        if line.startswith("## "):
            story.append(Paragraph(_inline_md_to_rl(line[3:].strip()), styles["H2Custom"]))
            i += 1
            continue
        if line.startswith("# "):
            story.append(Paragraph(_inline_md_to_rl(line[2:].strip()), styles["H1Custom"]))
            i += 1
            continue

        if line.startswith("> "):
            story.append(Paragraph(_inline_md_to_rl(line[2:].strip()), styles["Note"]))
            i += 1
            continue

        m_check = re.match(r"^[-*] \[([ xX])\]\s+(.*)$", line)
        if m_check:
            mark = "☑" if m_check.group(1).lower() == "x" else "☐"
            story.append(Paragraph(f"{mark} {_inline_md_to_rl(m_check.group(2))}", styles["BulletBody"]))
            story.append(Spacer(1, 2))
            i += 1
            continue

        m_ul = re.match(r"^[-*] +(.*)$", line)
        if m_ul:
            story.append(Paragraph(f"• {_inline_md_to_rl(m_ul.group(1))}", styles["BulletBody"]))
            story.append(Spacer(1, 2))
            i += 1
            continue

        m_ol = re.match(r"^(\d+)\.\s+(.*)$", line)
        if m_ol:
            story.append(Paragraph(f"{m_ol.group(1)}. {_inline_md_to_rl(m_ol.group(2))}", styles["BulletBody"]))
            story.append(Spacer(1, 2))
            i += 1
            continue

        story.append(Paragraph(_inline_md_to_rl(line.strip()), styles["BodyCustom"]))
        i += 1

    flush_table()
    flush_code()
    story.append(Spacer(1, 10))
    story.append(HRFlowable(width="100%", thickness=0.6, color=BORDER))
    story.append(Paragraph(
        "VALAgent · Keep secrets out of Git · Script: copilot_agent/deploy_to_foundry.py",
        styles["Footer"],
    ))

    def add_page_number(canvas, doc) -> None:
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(HexColor("#64748B"))
        canvas.drawCentredString(
            letter[0] / 2,
            0.45 * inch,
            f"VAL CoPilot · Azure AI Foundry Deployment · Page {doc.page}",
        )
        canvas.restoreState()

    path.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(path),
        pagesize=letter,
        leftMargin=0.7 * inch,
        rightMargin=0.7 * inch,
        topMargin=0.65 * inch,
        bottomMargin=0.65 * inch,
        title="VAL CoPilot Azure AI Foundry Deployment Guide",
        author="VAL CoPilot",
    )
    doc.build(story, onFirstPage=add_page_number, onLaterPages=add_page_number)


def _build_html(md_text: str, path: Path) -> None:
    lines_out: list[str] = []
    in_code = False
    in_ul = False
    in_ol = False
    in_table = False

    def close_lists() -> None:
        nonlocal in_ul, in_ol
        if in_ul:
            lines_out.append("</ul>")
            in_ul = False
        if in_ol:
            lines_out.append("</ol>")
            in_ol = False

    def close_table() -> None:
        nonlocal in_table
        if in_table:
            lines_out.append("</table>")
            in_table = False

    for raw in md_text.splitlines():
        line = raw.rstrip()
        if line.startswith("```"):
            close_lists()
            close_table()
            if not in_code:
                lines_out.append("<pre><code>")
                in_code = True
            else:
                lines_out.append("</code></pre>")
                in_code = False
            continue
        if in_code:
            lines_out.append(html_mod.escape(line))
            continue
        if line.startswith("|"):
            close_lists()
            cells = [c.strip() for c in line.strip("|").split("|")]
            if all(set(c) <= {"-", ":", " "} for c in cells):
                continue
            if not in_table:
                lines_out.append("<table>")
                in_table = True
                lines_out.append(
                    "<tr>" + "".join(f"<th>{html_mod.escape(c)}</th>" for c in cells) + "</tr>"
                )
            else:
                lines_out.append(
                    "<tr>" + "".join(f"<td>{html_mod.escape(c)}</td>" for c in cells) + "</tr>"
                )
            continue
        close_table()
        if not line.strip():
            close_lists()
            continue
        if line.startswith("# "):
            close_lists()
            cls = " part" if line.startswith("# PART") or line.startswith("# Part") else ""
            lines_out.append(f"<h1 class='{cls.strip()}'>{html_mod.escape(line[2:])}</h1>")
            continue
        if line.startswith("## "):
            close_lists()
            lines_out.append(f"<h2>{html_mod.escape(line[3:])}</h2>")
            continue
        if line.startswith("### "):
            close_lists()
            lines_out.append(f"<h3>{html_mod.escape(line[4:])}</h3>")
            continue
        if line.startswith("> "):
            close_lists()
            lines_out.append(f"<blockquote>{html_mod.escape(line[2:])}</blockquote>")
            continue
        if re.match(r"^[-*] \[[ xX]\]\s+", line):
            if not in_ul:
                close_lists()
                lines_out.append("<ul class='checks'>")
                in_ul = True
            item = re.sub(r"^[-*] \[[ xX]\]\s*", "", line)
            lines_out.append(f"<li>{html_mod.escape(item)}</li>")
            continue
        if re.match(r"^[-*] ", line):
            if not in_ul:
                close_lists()
                lines_out.append("<ul>")
                in_ul = True
            lines_out.append(f"<li>{html_mod.escape(line[2:])}</li>")
            continue
        if re.match(r"^\d+\. ", line):
            if not in_ol:
                close_lists()
                lines_out.append("<ol>")
                in_ol = True
            item = re.sub(r"^\d+\.\s*", "", line)
            lines_out.append(f"<li>{html_mod.escape(item)}</li>")
            continue
        if line.strip() == "---":
            close_lists()
            lines_out.append("<hr/>")
            continue
        close_lists()
        text = html_mod.escape(line)
        text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
        text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
        text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', text)
        lines_out.append(f"<p>{text}</p>")

    close_lists()
    close_table()
    if in_code:
        lines_out.append("</code></pre>")

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>VAL CoPilot — Azure AI Foundry Deployment Guide</title>
  <style>
    body {{ font-family: Georgia, "Times New Roman", serif; max-width: 880px;
           margin: 2rem auto; padding: 0 1.25rem 3rem; color: #1e293b;
           background: linear-gradient(180deg, #f8fafc 0%, #eef6f6 100%); }}
    h1,h2,h3 {{ font-family: "Segoe UI", Helvetica, Arial, sans-serif; color: #0b1f33; }}
    h1 {{ border-bottom: 2px solid #0e6b6b; padding-bottom: .35rem; }}
    h1.part {{ background: #d9f3f3; padding: .6rem .8rem; border: none; border-radius: 6px; color: #0e6b6b; }}
    h2 {{ color: #0e6b6b; margin-top: 1.6rem; }}
    code, pre {{ font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; background: #f1f5f9; }}
    pre {{ padding: .9rem 1rem; overflow-x: auto; border-radius: 6px; border: 1px solid #cbd5e1; }}
    code {{ padding: .1rem .3rem; border-radius: 3px; }}
    table {{ border-collapse: collapse; width: 100%; margin: 1rem 0; background: #fff; }}
    th, td {{ border: 1px solid #cbd5e1; padding: .55rem .7rem; text-align: left; vertical-align: top; font-size: .95rem; }}
    th {{ background: #0b1f33; color: #fff; }}
    tr:nth-child(even) td {{ background: #f8fafc; }}
    blockquote {{ border-left: 4px solid #0e6b6b; margin: 1rem 0; padding: .2rem 1rem; background: #f0fdfa; }}
    hr {{ border: none; border-top: 1px solid #cbd5e1; margin: 1.5rem 0; }}
    ul.checks li {{ list-style: none; }}
    ul.checks li::before {{ content: "☐ "; }}
    .download {{ font-family: "Segoe UI", Helvetica, Arial, sans-serif; background: #0e6b6b;
                 color: #fff !important; text-decoration: none; padding: .55rem .9rem;
                 border-radius: 6px; display: inline-block; margin: .4rem .4rem .4rem 0; }}
    .download.secondary {{ background: #0b1f33; }}
    .callout {{ background: #ffedd5; border: 1px solid #c2410c; padding: .75rem 1rem;
                border-radius: 6px; margin: 1rem 0; font-family: "Segoe UI", Helvetica, Arial, sans-serif; }}
  </style>
</head>
<body>
  <p>
    <a class="download" href="VAL_CoPilot_Azure_Foundry_Deployment_Guide.pdf">Download PDF</a>
    <a class="download secondary" href="VAL_CoPilot_Azure_Foundry_Deployment_Guide.md">View Markdown</a>
  </p>
  <div class="callout"><strong>Optional future path.</strong> Current POC runtime is Streamlit → Flask → FastMCP → synthetic Gold.
  Complete Part A (Azure Foundry portal) before Part B (deploy script). The script cannot create the Foundry resource, project, or model deployment.</div>
  {"".join(lines_out)}
</body>
</html>
"""
    path.write_text(html, encoding="utf-8")


def main() -> None:
    markdown = MD_PATH.read_text(encoding="utf-8")
    if len(markdown.strip()) < 100:
        raise SystemExit(f"Markdown guide missing or empty: {MD_PATH}")
    _build_html(markdown, HTML_PATH)
    _build_pdf_from_markdown(markdown, PDF_PATH)
    ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
    ARTIFACT.write_bytes(PDF_PATH.read_bytes())
    print(f"Wrote {MD_PATH} ({MD_PATH.stat().st_size} bytes)")
    print(f"Wrote {HTML_PATH} ({HTML_PATH.stat().st_size} bytes)")
    print(f"Wrote {PDF_PATH} ({PDF_PATH.stat().st_size} bytes)")
    print(f"Wrote {ARTIFACT} ({ARTIFACT.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
