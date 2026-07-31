#!/usr/bin/env python3
"""
Generate VAL CoPilot production architecture + process-flow PowerPoint.

Excludes offline/mock testing paths (USE_OFFLINE_MOCKS, offline_router, fixtures).
"""

from __future__ import annotations

from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import nsmap, qn
from pptx.util import Emu, Inches, Pt

DOCS = Path(__file__).resolve().parent
PPTX_PATH = DOCS / "VAL_CoPilot_Architecture_and_Process_Flow.pptx"
ARTIFACT = Path("/opt/cursor/artifacts/VAL_CoPilot_Architecture_and_Process_Flow.pptx")

# Widescreen 16:9
SLIDE_W = Inches(13.333)
SLIDE_H = Inches(7.5)

NAVY = RGBColor(0x0B, 0x1F, 0x33)
TEAL = RGBColor(0x0E, 0x6B, 0x6B)
TEAL_LIGHT = RGBColor(0xD9, 0xF3, 0xF3)
SLATE = RGBColor(0x33, 0x41, 0x55)
LIGHT = RGBColor(0xF1, 0xF5, 0xF9)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
ORANGE = RGBColor(0xC2, 0x41, 0x0C)
ORANGE_LIGHT = RGBColor(0xFF, 0xED, 0xD5)
BLUE = RGBColor(0x1D, 0x4E, 0xD8)
BLUE_LIGHT = RGBColor(0xDB, 0xEA, 0xFE)
PURPLE = RGBColor(0x6D, 0x28, 0xD9)
PURPLE_LIGHT = RGBColor(0xED, 0xE9, 0xFE)
GREEN = RGBColor(0x04, 0x78, 0x57)
GREEN_LIGHT = RGBColor(0xD1, 0xFA, 0xE5)
GOLD = RGBColor(0xB4, 0x53, 0x09)
GOLD_LIGHT = RGBColor(0xFE, 0xF3, 0xC7)
GRAY = RGBColor(0x94, 0xA3, 0xB8)


def _set_run(run, text: str, size: int, bold: bool = False, color: RGBColor = SLATE) -> None:
    run.text = text
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = color
    run.font.name = "Calibri"


def _fill_shape(shape, fill: RGBColor, line: RGBColor, line_pt: float = 1.25) -> None:
    shape.fill.solid()
    shape.fill.fore_color.rgb = fill
    shape.line.color.rgb = line
    shape.line.width = Pt(line_pt)


def add_box(
    slide,
    left,
    top,
    width,
    height,
    fill: RGBColor,
    line: RGBColor,
    title: str,
    subtitle: str = "",
    title_size: int = 12,
    sub_size: int = 10,
    title_color: RGBColor | None = None,
):
    shape = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, left, top, width, height)
    _fill_shape(shape, fill, line)
    # Soft corners
    try:
        shape.adjustments[0] = 0.12
    except Exception:  # noqa: BLE001
        pass
    tf = shape.text_frame
    tf.word_wrap = True
    tf.auto_size = None
    shape.text_frame.clear()
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.CENTER
    run = p.add_run()
    _set_run(run, title, title_size, bold=True, color=title_color or NAVY)
    if subtitle:
        p2 = tf.add_paragraph()
        p2.alignment = PP_ALIGN.CENTER
        run2 = p2.add_run()
        _set_run(run2, subtitle, sub_size, bold=False, color=SLATE)
    tf.paragraphs[0].space_before = Pt(2)
    return shape


def add_layer_band(slide, left, top, width, height, fill: RGBColor, line: RGBColor, label: str):
    shape = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, left, top, width, height)
    _fill_shape(shape, fill, line, 1.5)
    try:
        shape.adjustments[0] = 0.04
    except Exception:  # noqa: BLE001
        pass
    # Label at top-left via separate text box for clarity
    tb = slide.shapes.add_textbox(left + Inches(0.15), top + Inches(0.08), width - Inches(0.3), Inches(0.3))
    p = tb.text_frame.paragraphs[0]
    run = p.add_run()
    _set_run(run, label, 13, bold=True, color=line)
    return shape


def add_title_bar(slide, text: str, subtitle: str = "") -> None:
    bar = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0), Inches(0), SLIDE_W, Inches(0.85))
    _fill_shape(bar, NAVY, NAVY, 0)
    tb = slide.shapes.add_textbox(Inches(0.4), Inches(0.18), Inches(12.5), Inches(0.55))
    p = tb.text_frame.paragraphs[0]
    run = p.add_run()
    _set_run(run, text, 22, bold=True, color=WHITE)
    if subtitle:
        sub = slide.shapes.add_textbox(Inches(0.4), Inches(0.9), Inches(12.5), Inches(0.35))
        p2 = sub.text_frame.paragraphs[0]
        run2 = p2.add_run()
        _set_run(run2, subtitle, 12, bold=False, color=SLATE)


def add_arrow_right(slide, left, top, width=Inches(0.35), height=Inches(0.18), color: RGBColor = GRAY):
    shape = slide.shapes.add_shape(MSO_SHAPE.RIGHT_ARROW, left, top, width, height)
    _fill_shape(shape, color, color, 0)
    return shape


def add_arrow_down(slide, left, top, width=Inches(0.18), height=Inches(0.3), color: RGBColor = GRAY):
    shape = slide.shapes.add_shape(MSO_SHAPE.DOWN_ARROW, left, top, width, height)
    _fill_shape(shape, color, color, 0)
    return shape


def add_footer(slide, page: str) -> None:
    tb = slide.shapes.add_textbox(Inches(0.4), Inches(7.1), Inches(12.5), Inches(0.3))
    p = tb.text_frame.paragraphs[0]
    p.alignment = PP_ALIGN.CENTER
    run = p.add_run()
    _set_run(run, f"VAL CoPilot · Production architecture only (no mock/offline paths) · {page}", 9, color=GRAY)


def slide_cover(prs: Presentation) -> None:
    slide = prs.slides.add_slide(prs.slide_layouts[6])  # blank
    bg = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, SLIDE_W, SLIDE_H)
    _fill_shape(bg, LIGHT, LIGHT, 0)
    accent = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, Inches(2.2), SLIDE_W, Inches(2.6))
    _fill_shape(accent, NAVY, NAVY, 0)

    title = slide.shapes.add_textbox(Inches(0.8), Inches(2.5), Inches(11.7), Inches(1.0))
    p = title.text_frame.paragraphs[0]
    p.alignment = PP_ALIGN.CENTER
    run = p.add_run()
    _set_run(run, "VAL CoPilot", 36, bold=True, color=WHITE)

    sub = slide.shapes.add_textbox(Inches(0.8), Inches(3.4), Inches(11.7), Inches(0.8))
    p2 = sub.text_frame.paragraphs[0]
    p2.alignment = PP_ALIGN.CENTER
    run2 = p2.add_run()
    _set_run(run2, "Architecture & Process Flow", 28, bold=True, color=TEAL_LIGHT)

    note = slide.shapes.add_textbox(Inches(1.5), Inches(5.2), Inches(10.3), Inches(1.2))
    for i, line in enumerate(
        [
            "Three-layer monorepo: Validation UI → Cognitive Routing → Data Retrieval MCP",
            "Includes contract lifecycle procedures, compare framework, and Foundry deploy path",
            "Excluded: USE_OFFLINE_MOCKS, offline cognitive router, test fixtures",
        ]
    ):
        para = note.text_frame.paragraphs[0] if i == 0 else note.text_frame.add_paragraph()
        para.alignment = PP_ALIGN.CENTER
        run = para.add_run()
        _set_run(run, line, 14, color=SLATE)


def slide_architecture(prs: Presentation) -> None:
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    add_title_bar(
        slide,
        "1. Production System Architecture",
        "Streamlit → Flask / LangChain / Azure OpenAI → MCP tools → Fabric SQL + Azure AI Search (+ PGVector)",
    )

    # Layer 1
    add_layer_band(slide, Inches(0.35), Inches(1.35), Inches(12.6), Inches(1.35), BLUE_LIGHT, BLUE, "Layer 1 — Validation UI (test_ui)")
    add_box(slide, Inches(0.7), Inches(1.8), Inches(3.6), Inches(0.7), WHITE, BLUE, "Streamlit test_ui", "Bot Framework activity builder")
    add_box(slide, Inches(4.7), Inches(1.8), Inches(3.6), Inches(0.7), WHITE, BLUE, "User Prompt", "Markdown reply rendering")
    add_box(slide, Inches(8.7), Inches(1.8), Inches(3.6), Inches(0.7), WHITE, BLUE, "HTTP Client", "COPILOT_MESSAGES_URL → :3978")
    add_arrow_right(slide, Inches(4.35), Inches(2.05), color=BLUE)
    add_arrow_right(slide, Inches(8.35), Inches(2.05), color=BLUE)

    # Layer 2
    add_layer_band(slide, Inches(0.35), Inches(2.9), Inches(12.6), Inches(2.15), TEAL_LIGHT, TEAL, "Layer 2 — Cognitive Routing (copilot_agent)")
    add_box(slide, Inches(0.7), Inches(3.4), Inches(2.8), Inches(0.85), WHITE, TEAL, "Flask /api/messages", "app.py")
    add_box(slide, Inches(3.9), Inches(3.4), Inches(3.0), Inches(0.85), WHITE, TEAL, "LangChain AgentExecutor", "OpenAI tools agent + SYSTEM_PROMPT")
    add_box(slide, Inches(7.3), Inches(3.4), Inches(2.6), Inches(0.85), ORANGE_LIGHT, ORANGE, "Azure OpenAI", "AzureChatOpenAI")
    add_box(slide, Inches(10.2), Inches(3.4), Inches(2.4), Inches(0.85), PURPLE_LIGHT, PURPLE, "Cognitive Procedures", "Compare · Audit · Exposure…")
    add_arrow_right(slide, Inches(3.55), Inches(3.7), color=TEAL)
    add_arrow_right(slide, Inches(6.95), Inches(3.7), color=ORANGE)
    add_box(slide, Inches(0.7), Inches(4.45), Inches(5.5), Inches(0.45), WHITE, TEAL, "DualMCPBridge (mcp_clients.py) — stdio MCP to fabric_data + pgvector", title_size=11)
    add_arrow_down(slide, Inches(6.3), Inches(4.95), color=GREEN)

    # Layer 3
    add_layer_band(slide, Inches(0.35), Inches(5.25), Inches(12.6), Inches(1.65), GREEN_LIGHT, GREEN, "Layer 3 — Data Retrieval (mcp_server FastMCP)")
    tools = [
        ("get_expiring_contracts", 0.55),
        ("get_vendor_spend_summary", 3.0),
        ("compare_contracts", 5.45),
        ("check_missing_fields", 7.9),
        ("search_cloud_blob", 10.35),
    ]
    for name, x in tools:
        add_box(slide, Inches(x), Inches(5.7), Inches(2.25), Inches(0.5), WHITE, GREEN, name, title_size=10)

    add_box(slide, Inches(0.7), Inches(6.35), Inches(3.7), Inches(0.4), GOLD_LIGHT, GOLD, "Microsoft Fabric SQL (Gold)", title_size=11, title_color=GOLD)
    add_box(slide, Inches(4.7), Inches(6.35), Inches(3.7), Inches(0.4), BLUE_LIGHT, BLUE, "Azure AI Search (semantic hybrid)", title_size=11, title_color=BLUE)
    add_box(slide, Inches(8.7), Inches(6.35), Inches(3.7), Inches(0.4), PURPLE_LIGHT, PURPLE, "Postgres / PGVector memory", title_size=11, title_color=PURPLE)
    add_footer(slide, "Slide 2")


def slide_request_flow(prs: Presentation) -> None:
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    add_title_bar(
        slide,
        "2. End-to-End Request Process Flow",
        "Production control loop — UI ingress → tool execution → Markdown synthesis",
    )

    steps_top = [
        ("1. User asks\nin Streamlit", BLUE_LIGHT, BLUE, 0.5),
        ("2. POST\n/api/messages", TEAL_LIGHT, TEAL, 3.5),
        ("3. Azure OpenAI\nplans tool calls", ORANGE_LIGHT, ORANGE, 6.5),
        ("4. MCP tools\nexecute", GREEN_LIGHT, GREEN, 9.5),
    ]
    for title, fill, line, x in steps_top:
        add_box(slide, Inches(x), Inches(1.6), Inches(2.6), Inches(1.1), fill, line, title.replace("\n", " "), title_size=14)
    for x in (3.15, 6.15, 9.15):
        add_arrow_right(slide, Inches(x), Inches(2.0), Inches(0.3), Inches(0.22), GRAY)

    add_arrow_down(slide, Inches(10.6), Inches(2.8), Inches(0.22), Inches(0.45), GRAY)

    steps_bot = [
        ("8. UI renders answer", BLUE_LIGHT, BLUE, 0.5),
        ("7. Flask reply activity", TEAL_LIGHT, TEAL, 3.5),
        ("6. LLM synthesizes Markdown", ORANGE_LIGHT, ORANGE, 6.5),
        ("5. Evidence returned", GREEN_LIGHT, GREEN, 9.5),
    ]
    for title, fill, line, x in steps_bot:
        add_box(slide, Inches(x), Inches(3.4), Inches(2.6), Inches(1.1), fill, line, title, title_size=14)
    # Bottom row flows right-to-left (5 → 6 → 7 → 8)
    for x in (3.15, 6.15, 9.15):
        arr = slide.shapes.add_shape(
            MSO_SHAPE.LEFT_ARROW, Inches(x), Inches(3.8), Inches(0.3), Inches(0.22)
        )
        _fill_shape(arr, GRAY, GRAY, 0)

    # Routing strip
    add_layer_band(
        slide,
        Inches(0.4),
        Inches(4.9),
        Inches(12.5),
        Inches(1.7),
        LIGHT,
        GRAY,
        "Intent → Tool Domain Routing (SYSTEM_PROMPT)",
    )
    domains = [
        ("Financial / dates", "Fabric SQL tools", GOLD_LIGHT, GOLD, 0.7),
        ("Compare / completeness", "Analytics tools", TEAL_LIGHT, TEAL, 3.8),
        ("Legal clauses / PDFs", "Azure AI Search", BLUE_LIGHT, BLUE, 6.9),
        ("Session memory", "PGVector MCP", PURPLE_LIGHT, PURPLE, 10.0),
    ]
    for title, sub, fill, line, x in domains:
        add_box(slide, Inches(x), Inches(5.5), Inches(2.8), Inches(0.85), fill, line, title, sub, 12, 11)

    add_footer(slide, "Slide 3")


def slide_lifecycle(prs: Presentation) -> None:
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    add_title_bar(
        slide,
        "3. Contract Lifecycle Cognitive Procedures",
        "Analysis enforced in orchestrator SYSTEM_PROMPT — not in MCP tool bodies",
    )

    headers = [("User Intent", 0.4), ("Tools Invoked", 4.5), ("Required Markdown Output", 8.6)]
    for text, x in headers:
        tb = slide.shapes.add_textbox(Inches(x), Inches(1.2), Inches(3.8), Inches(0.35))
        run = tb.text_frame.paragraphs[0].add_run()
        _set_run(run, text, 14, bold=True, color=NAVY)

    rows = [
        (
            "Single-agreement audit / red flag",
            "check_missing_contract_fields + search_cloud_blob_contracts",
            "## Red-Flag Compliance Audit",
            ORANGE,
            ORANGE_LIGHT,
        ),
        (
            "High-risk clause found",
            "search_cloud_blob_contracts (clause evidence)",
            "## Dynamic Counter-Clause Drafting",
            ORANGE,
            ORANGE_LIGHT,
        ),
        (
            "Penalty / breach exposure",
            "get_vendor_spend_summary + expiring/compare + search",
            "## Financial Exposure Projection",
            GOLD,
            GOLD_LIGHT,
        ),
        (
            "Expiring / renew / terminate",
            "get_expiring_contracts + get_vendor_spend_summary",
            "## Proactive Renewal Strategy Sheet",
            TEAL,
            TEAL_LIGHT,
        ),
        (
            "Compare 2+N contracts",
            "compare_contracts + spend + search",
            "## Recommendation",
            BLUE,
            BLUE_LIGHT,
        ),
    ]
    for i, (intent, tools, output, color, light) in enumerate(rows):
        y = 1.6 + i * 0.9
        add_box(slide, Inches(0.4), Inches(y), Inches(3.7), Inches(0.75), WHITE, color, intent, title_size=12)
        add_arrow_right(slide, Inches(4.2), Inches(y + 0.28), Inches(0.25), Inches(0.18), GRAY)
        add_box(slide, Inches(4.5), Inches(y), Inches(3.8), Inches(0.75), GREEN_LIGHT, GREEN, tools, title_size=11)
        add_arrow_right(slide, Inches(8.4), Inches(y + 0.28), Inches(0.25), Inches(0.18), GRAY)
        add_box(slide, Inches(8.7), Inches(y), Inches(4.1), Inches(0.75), light, color, output, title_size=12, title_color=color)

    note = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.4), Inches(6.3), Inches(12.5), Inches(0.5))
    _fill_shape(note, PURPLE_LIGHT, PURPLE)
    p = note.text_frame.paragraphs[0]
    p.alignment = PP_ALIGN.CENTER
    run = p.add_run()
    _set_run(
        run,
        "When multiple procedures apply: Audit → Counter-Clause → Exposure → Renewal → Recommendation",
        13,
        bold=True,
        color=PURPLE,
    )
    add_footer(slide, "Slide 4")


def slide_compare(prs: Presentation) -> None:
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    add_title_bar(
        slide,
        "4. Comparative Analysis Decision Framework",
        "N-way compare supported via comma-separated contract_refs / supplier_names / …",
    )

    stages = [
        ("1. Quantitative Comparison", "ACV, tenure, auto-renew,\nhistorical vendor spend", GOLD_LIGHT, GOLD, 0.8),
        ("2. Risk & Liability Assessment", "Liability caps, indemnity,\nSLA, termination / exit", ORANGE_LIGHT, ORANGE, 5.0),
        ("3. Explicit Suggestion", "## Recommendation\nwinner + ranked runners-up", BLUE_LIGHT, BLUE, 9.2),
    ]
    for title, sub, fill, line, x in stages:
        add_box(slide, Inches(x), Inches(2.4), Inches(3.3), Inches(2.0), fill, line, title, sub.replace("\n", " · "), 16, 12)
    add_arrow_right(slide, Inches(4.25), Inches(3.3), Inches(0.55), Inches(0.28), GRAY)
    add_arrow_right(slide, Inches(8.45), Inches(3.3), Inches(0.55), Inches(0.28), GRAY)

    add_box(
        slide,
        Inches(0.8),
        Inches(5.0),
        Inches(11.7),
        Inches(1.2),
        LIGHT,
        TEAL,
        "Do not merely juxtapose excerpts — decide which option is structurally superior / lower risk",
        "Tools: compare_contracts · get_vendor_spend_summary · get_expiring_contracts · search_cloud_blob_contracts",
        14,
        12,
    )
    add_footer(slide, "Slide 5")


def slide_foundry(prs: Presentation) -> None:
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    add_title_bar(
        slide,
        "5. Azure AI Foundry Provisioning Path",
        "copilot_agent/deploy_to_foundry.py — DefaultAzureCredential + FunctionTool / ToolSet",
    )

    steps = [
        ("Root .env", "AZURE_FOUNDRY_\nCONNECTION_STRING", TEAL_LIGHT, TEAL, 0.4),
        ("DefaultAzure\nCredential", "Entra ID auth", ORANGE_LIGHT, ORANGE, 3.0),
        ("Import MCP\ntools", "3 Fabric/Search\ncallables", GREEN_LIGHT, GREEN, 5.6),
        ("FunctionTool\n+ ToolSet", "azure-ai-agents", BLUE_LIGHT, BLUE, 8.2),
        ("create_agent", "SYSTEM_PROMPT\ninstructions", PURPLE_LIGHT, PURPLE, 10.8),
    ]
    for title, sub, fill, line, x in steps:
        add_box(
            slide,
            Inches(x),
            Inches(2.2),
            Inches(2.3),
            Inches(2.0),
            fill,
            line,
            title.replace("\n", " "),
            sub.replace("\n", " "),
            14,
            11,
        )
    for x in (2.75, 5.35, 7.95, 10.55):
        add_arrow_right(slide, Inches(x), Inches(3.1), Inches(0.22), Inches(0.2), GRAY)

    add_box(
        slide,
        Inches(0.5),
        Inches(4.7),
        Inches(12.3),
        Inches(0.7),
        GREEN_LIGHT,
        GREEN,
        "Foundry ToolSet: get_expiring_contracts · get_vendor_spend_summary · search_cloud_blob_contracts",
        title_size=13,
    )
    add_box(
        slide,
        Inches(0.5),
        Inches(5.6),
        Inches(12.3),
        Inches(0.7),
        LIGHT,
        SLATE,
        "Full local MCP also exposes: compare_contracts · check_missing_contract_fields · fabric_health_check",
        title_size=13,
    )
    add_footer(slide, "Slide 6")


def slide_summary(prs: Presentation) -> None:
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    add_title_bar(
        slide,
        "6. Component & Change Summary",
        "Production capabilities delivered (mock/offline staging excluded)",
    )

    items = [
        (
            "Data Retrieval MCP",
            "Fabric Gold tools for expiring contracts, vendor spend, N-way compare, missing-field completeness; "
            "Azure AI Search hybrid semantic search; shared lookup dimensions.",
            GREEN,
            GREEN_LIGHT,
        ),
        (
            "Cognitive Routing",
            "LangChain OpenAI-tools agent with strict domain routing; Comparative Analysis framework; "
            "four lifecycle procedures with mandatory Markdown sections.",
            TEAL,
            TEAL_LIGHT,
        ),
        (
            "Validation UI",
            "Streamlit emulator posting Bot Framework activities to POST /api/messages and rendering Markdown replies.",
            BLUE,
            BLUE_LIGHT,
        ),
        (
            "Foundry Deploy",
            "DefaultAzureCredential + ToolSet/FunctionTool provisioning via AZURE_FOUNDRY_CONNECTION_STRING.",
            PURPLE,
            PURPLE_LIGHT,
        ),
        (
            "Config Boundary",
            "Single root .env; MCP remains free of orchestration / LLM logic.",
            GOLD,
            GOLD_LIGHT,
        ),
    ]
    for i, (title, body, color, light) in enumerate(items):
        y = 1.25 + i * 0.95
        add_box(slide, Inches(0.5), Inches(y), Inches(2.8), Inches(0.8), light, color, title, title_size=13, title_color=color)
        body_box = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(3.5), Inches(y), Inches(9.3), Inches(0.8))
        _fill_shape(body_box, WHITE, color)
        try:
            body_box.adjustments[0] = 0.08
        except Exception:  # noqa: BLE001
            pass
        p = body_box.text_frame.paragraphs[0]
        run = p.add_run()
        _set_run(run, body, 12, color=SLATE)
        body_box.text_frame.word_wrap = True

    add_footer(slide, "Slide 7")


def build_pptx(path: Path) -> None:
    prs = Presentation()
    prs.slide_width = SLIDE_W
    prs.slide_height = SLIDE_H

    slide_cover(prs)
    slide_architecture(prs)
    slide_request_flow(prs)
    slide_lifecycle(prs)
    slide_compare(prs)
    slide_foundry(prs)
    slide_summary(prs)

    path.parent.mkdir(parents=True, exist_ok=True)
    prs.save(str(path))


def main() -> None:
    build_pptx(PPTX_PATH)
    ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
    ARTIFACT.write_bytes(PPTX_PATH.read_bytes())
    print(f"Wrote {PPTX_PATH} ({PPTX_PATH.stat().st_size} bytes)")
    print(f"Wrote {ARTIFACT} ({ARTIFACT.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
