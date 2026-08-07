#!/usr/bin/env python3
"""Generate a downloadable PDF of the consolidated VAL CoPilot change prompt."""

from __future__ import annotations

import shutil
from pathlib import Path

from reportlab.lib.colors import HexColor, white
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    HRFlowable,
    KeepTogether,
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
PDF_PATH = DOCS / "VAL_CoPilot_Consolidated_Changes_Prompt.pdf"
ARTIFACT = Path("/opt/cursor/artifacts/VAL_CoPilot_Consolidated_Changes_Prompt.pdf")

NAVY = HexColor("#0B1F33")
TEAL = HexColor("#0E6B6B")
SLATE = HexColor("#334155")
LIGHT = HexColor("#F1F5F9")
BORDER = HexColor("#CBD5E1")
AMBER = HexColor("#B45309")


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "TitleCustom",
            parent=base["Title"],
            fontName="Helvetica-Bold",
            fontSize=18,
            leading=22,
            textColor=white,
            alignment=TA_CENTER,
            spaceAfter=4,
        ),
        "subtitle": ParagraphStyle(
            "SubtitleCustom",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=10,
            leading=13,
            textColor=HexColor("#DBEAFE"),
            alignment=TA_CENTER,
            spaceAfter=0,
        ),
        "h1": ParagraphStyle(
            "H1Custom",
            parent=base["Heading1"],
            fontName="Helvetica-Bold",
            fontSize=13,
            leading=16,
            textColor=NAVY,
            spaceBefore=14,
            spaceAfter=6,
        ),
        "h2": ParagraphStyle(
            "H2Custom",
            parent=base["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=11,
            leading=14,
            textColor=TEAL,
            spaceBefore=10,
            spaceAfter=4,
        ),
        "body": ParagraphStyle(
            "BodyCustom",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=9.5,
            leading=13,
            textColor=SLATE,
            alignment=TA_JUSTIFY,
            spaceAfter=6,
        ),
        "bullet": ParagraphStyle(
            "BulletCustom",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=9.5,
            leading=12.5,
            textColor=SLATE,
            leftIndent=4,
            spaceAfter=2,
        ),
        "mono": ParagraphStyle(
            "MonoCustom",
            parent=base["Code"],
            fontName="Courier",
            fontSize=8.5,
            leading=11,
            textColor=NAVY,
            backColor=LIGHT,
            borderPadding=6,
            spaceBefore=4,
            spaceAfter=8,
        ),
        "callout": ParagraphStyle(
            "CalloutCustom",
            parent=base["Normal"],
            fontName="Helvetica-Oblique",
            fontSize=9.5,
            leading=13,
            textColor=AMBER,
            alignment=TA_LEFT,
            spaceBefore=4,
            spaceAfter=4,
        ),
        "table_cell": ParagraphStyle(
            "TableCell",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=8.5,
            leading=11,
            textColor=SLATE,
        ),
        "table_header": ParagraphStyle(
            "TableHeader",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=8.5,
            leading=11,
            textColor=white,
        ),
        "footer": ParagraphStyle(
            "FooterCustom",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=8,
            textColor=HexColor("#64748B"),
            alignment=TA_CENTER,
        ),
    }


def _bullets(items: list[str], style: ParagraphStyle) -> ListFlowable:
    return ListFlowable(
        [ListItem(Paragraph(item, style), leftIndent=12, bulletColor=TEAL) for item in items],
        bulletType="bullet",
        start="•",
        leftIndent=18,
        spaceBefore=2,
        spaceAfter=6,
    )


def _header_band(styles: dict[str, ParagraphStyle]) -> list:
    data = [[
        Paragraph("VAL CoPilot — Consolidated Changes Prompt", styles["title"]),
    ], [
        Paragraph(
            "Synthetic Contract Intelligence Tool-Layer POC · Agent handoff context",
            styles["subtitle"],
        ),
    ]]
    table = Table(data, colWidths=[7.0 * inch])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), NAVY),
                ("TOPPADDING", (0, 0), (-1, 0), 14),
                ("BOTTOMPADDING", (0, -1), (-1, -1), 12),
                ("LEFTPADDING", (0, 0), (-1, -1), 14),
                ("RIGHTPADDING", (0, 0), (-1, -1), 14),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ]
        )
    )
    return [table, Spacer(1, 0.2 * inch)]


def _pr_table(styles: dict[str, ParagraphStyle]) -> Table:
    rows = [
        [
            Paragraph("PR", styles["table_header"]),
            Paragraph("Change", styles["table_header"]),
        ],
        [
            Paragraph("#12", styles["table_cell"]),
            Paragraph("Process-flow docs + Foundry deploy refresh", styles["table_cell"]),
        ],
        [
            Paragraph("#13", styles["table_cell"]),
            Paragraph(
                "LinkSquares fixtures; remove old Test_contracts / test_fixtures",
                styles["table_cell"],
            ),
        ],
        [
            Paragraph("#14", styles["table_cell"]),
            Paragraph("Any-ID + N-way <font face='Courier'>compare_contracts</font>", styles["table_cell"]),
        ],
        [
            Paragraph("#15", styles["table_cell"]),
            Paragraph("No default compare when contracts are missing", styles["table_cell"]),
        ],
        [
            Paragraph("#16", styles["table_cell"]),
            Paragraph("Persistent persona conversation / search memory", styles["table_cell"]),
        ],
        [
            Paragraph("#17", styles["table_cell"]),
            Paragraph(
                "Missing compare/search/profile messaging + hard-stop refinements",
                styles["table_cell"],
            ),
        ],
        [
            Paragraph("#18", styles["table_cell"]),
            Paragraph(
                "Explicit save / retrieve / pin / filter / delete for previous searches",
                styles["table_cell"],
            ),
        ],
    ]
    table = Table(rows, colWidths=[0.7 * inch, 6.3 * inch])
    style_cmds = [
        ("BACKGROUND", (0, 0), (-1, 0), TEAL),
        ("GRID", (0, 0), (-1, -1), 0.4, BORDER),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]
    for i in range(1, len(rows)):
        if i % 2 == 0:
            style_cmds.append(("BACKGROUND", (0, i), (-1, i), LIGHT))
    table.setStyle(TableStyle(style_cmds))
    return table


def build_pdf(path: Path) -> None:
    styles = _styles()
    story: list = []
    story.extend(_header_band(styles))

    story.append(Paragraph("Purpose", styles["h1"]))
    story.append(
        Paragraph(
            "This document is a consolidated handoff prompt covering all VAL CoPilot "
            "changes delivered in the recent agent workstream. Paste or attach it as "
            "system/context for follow-on agents so behavior stays consistent.",
            styles["body"],
        )
    )

    story.append(Paragraph("Architecture (do not change boundaries)", styles["h1"]))
    story.append(
        _bullets(
            [
                "<b>Streamlit</b> (<font face='Courier'>test_ui/</font>) → "
                "<b>Flask</b> <font face='Courier'>/api/messages</font> "
                "(<font face='Courier'>copilot_agent/</font>) → "
                "<b>LangChain / offline router</b> → "
                "<b>FastMCP tools</b> (<font face='Courier'>mcp_server/</font>) → "
                "LinkSquares synthetic fixtures / Fabric SQL / Azure AI Search",
                "Shared persona memory: <font face='Courier'>memory/store.py</font> → "
                "<font face='Courier'>data/persona_memory.sqlite</font>",
                "Offline mocks via <font face='Courier'>USE_OFFLINE_MOCKS=true</font> / "
                "<font face='Courier'>AZURE_OPENAI_FORCE_OFFLINE=true</font>",
                "Active fixtures: "
                "<font face='Courier'>LinSquare_Contracts_100_Updated_30bb.json</font> + "
                "<font face='Courier'>agreement_9a06.json</font> "
                "(old <font face='Courier'>Test_contracts_0397</font> / "
                "<font face='Courier'>test_fixtures</font> removed)",
            ],
            styles["bullet"],
        )
    )

    story.append(Paragraph("Product rules already implemented (must preserve)", styles["h1"]))

    story.append(Paragraph("1. Compare contracts (any IDs + N-way)", styles["h2"]))
    story.append(
        _bullets(
            [
                "<font face='Courier'>compare_contracts</font> accepts any contract IDs "
                "and N-way lists (not only first/second).",
                "Multi-vendor / supplier expansion supported "
                "(<font face='Courier'>supplier_names</font>, "
                "<font face='Courier'>expand_supplier_matches</font>, "
                "<font face='Courier'>max_contracts</font>).",
                "Offline router extracts all mentioned IDs/vendors into compare kwargs.",
            ],
            styles["bullet"],
        )
    )

    story.append(Paragraph("2. Missing compare = hard stop (no default compare)", styles["h2"]))
    story.append(
        Paragraph(
            "If any requested supplier or contract ID cannot be resolved:",
            styles["body"],
        )
    )
    story.append(
        _bullets(
            [
                "<b>Do not</b> default to <font face='Courier'>CON-0001 vs CON-0002</font>",
                "<b>Do not</b> emit a comparative table",
                "<b>Do not</b> emit a recommendation",
                "Return <b>exactly and only</b> the message below",
            ],
            styles["bullet"],
        )
    )
    story.append(
        Preformatted(
            "The contract information requested for the comparison is not available at the moment",
            styles["mono"],
        )
    )
    story.append(
        _bullets(
            [
                "Same hard stop for mixed known/unknown vendors "
                "(never collapse into single-supplier catalog expansion).",
                "Sanitize legacy hallucination: "
                "<font face='Courier'>No two resolvable compare sides detected; "
                "defaulting comparison to CON-0001 vs CON-0002.</font>",
                "Compare intents are forced through the deterministic offline router.",
            ],
            styles["bullet"],
        )
    )

    story.append(Paragraph("3. Missing search / profile", styles["h2"]))
    story.append(
        _bullets(
            [
                "Unknown vendor search / unknown contract profile → "
                "<font face='Courier'>error: contract_not_present</font> with "
                "“No such contract is available…”",
                "Search/profile use that wording; <b>compare</b> uses the hard-stop "
                "sentence in section 2.",
            ],
            styles["bullet"],
        )
    )

    story.append(Paragraph("4. Persona memory — save &amp; retrieve previous searches", styles["h2"]))
    story.append(
        _bullets(
            [
                "Auto-save search-like user queries per persona.",
                "Streamlit sidebar <b>Saved searches</b>: filter, pin "
                "(<b>Save last search</b>), Re-run, Open chat, Delete, Retrieve in chat.",
                "Chat recall: “Show my previous searches”, “Retrieve my saved searches”, "
                "“previous searches about {topic}”.",
                "APIs: <font face='Courier'>GET/POST/DELETE /api/memory/searches</font>, "
                "<font face='Courier'>GET /api/memory/recall</font>, "
                "<font face='Courier'>GET /api/memory/conversations</font>",
                "Streamlit sets <font face='Courier'>channelData.clientPersistsMemory=true</font>; "
                "Flask persists for other clients.",
                "Memory-recall intents are forced through the offline persona store.",
            ],
            styles["bullet"],
        )
    )

    story.append(Paragraph("5. Docs / Foundry", styles["h2"]))
    story.append(
        _bullets(
            [
                "Process-flow architecture PDF/PPTX refreshed for tool-layer POC.",
                "Foundry framed as optional; "
                "<font face='Courier'>deploy_to_foundry.py</font> ToolSet covers the MCP tool surface.",
            ],
            styles["bullet"],
        )
    )

    story.append(Paragraph("Key merged PRs", styles["h1"]))
    story.append(_pr_table(styles))
    story.append(Spacer(1, 0.12 * inch))

    story.append(Paragraph("Runtime", styles["h1"]))
    story.append(
        _bullets(
            [
                "Flask: <font face='Courier'>http://localhost:3978</font>",
                "Streamlit: <font face='Courier'>http://localhost:8501</font>",
                "Branch work uses <font face='Courier'>cursor/&lt;name&gt;-a9d1</font>; "
                "preferred PR base: <font face='Courier'>main</font>",
            ],
            styles["bullet"],
        )
    )

    story.append(Paragraph("When changing behavior next", styles["h1"]))
    story.append(
        _bullets(
            [
                "Prefer deterministic offline-router / MCP hard stops over relying on the LLM.",
                "Do not reintroduce default <font face='Courier'>CON-0001/CON-0002</font> compares.",
                "Keep Streamlit ↔ Flask memory ownership clear "
                "(<font face='Courier'>clientPersistsMemory</font>).",
                "Preserve existing LinkSquares fixture-backed offline mocks.",
            ],
            styles["bullet"],
        )
    )

    story.append(Paragraph("One-liner sticky note", styles["h1"]))
    story.append(
        KeepTogether(
            [
                HRFlowable(width="100%", thickness=1, color=TEAL, spaceBefore=2, spaceAfter=8),
                Paragraph(
                    "VAL CoPilot: N-way any-ID compare; missing supplier/ID compare hard-stops "
                    "with exactly “The contract information requested for the comparison is not "
                    "available at the moment” (no table/recommendation/default pair); unknown "
                    "search/profile → “No such contract is available”; persona SQLite memory "
                    "auto-saves searches with Streamlit pin/filter/re-run/delete and chat/API "
                    "recall; LinkSquares fixtures only; Foundry optional.",
                    styles["callout"],
                ),
                HRFlowable(width="100%", thickness=1, color=TEAL, spaceBefore=8, spaceAfter=10),
            ]
        )
    )

    story.append(
        Paragraph(
            "Generated for VAL CoPilot agent handoff · booshank/VALAgent",
            styles["footer"],
        )
    )

    path.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(path),
        pagesize=letter,
        leftMargin=0.65 * inch,
        rightMargin=0.65 * inch,
        topMargin=0.55 * inch,
        bottomMargin=0.55 * inch,
        title="VAL CoPilot — Consolidated Changes Prompt",
        author="VAL CoPilot Cloud Agent",
    )
    doc.build(story)


def main() -> None:
    build_pdf(PDF_PATH)
    ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(PDF_PATH, ARTIFACT)
    print(f"Wrote {PDF_PATH}")
    print(f"Copied {ARTIFACT}")


if __name__ == "__main__":
    main()
