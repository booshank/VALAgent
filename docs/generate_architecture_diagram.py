#!/usr/bin/env python3
"""
Generate VAL CoPilot production architecture + process-flow PDF.

Excludes offline/mock testing paths (USE_OFFLINE_MOCKS, offline_router, fixtures).
"""

from __future__ import annotations

from pathlib import Path

from reportlab.lib.colors import Color, HexColor, white
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    Frame,
    PageTemplate,
    BaseDocTemplate,
    Paragraph,
    Spacer,
    PageBreak,
    KeepTogether,
    Flowable,
    HRFlowable,
)

DOCS = Path(__file__).resolve().parent
PDF_PATH = DOCS / "VAL_CoPilot_Architecture_and_Process_Flow.pdf"
ARTIFACT = Path("/opt/cursor/artifacts/VAL_CoPilot_Architecture_and_Process_Flow.pdf")

NAVY = HexColor("#0B1F33")
TEAL = HexColor("#0E6B6B")
TEAL_LIGHT = HexColor("#D9F3F3")
SLATE = HexColor("#334155")
LIGHT = HexColor("#F1F5F9")
BORDER = HexColor("#94A3B8")
ORANGE = HexColor("#C2410C")
ORANGE_LIGHT = HexColor("#FFEDD5")
BLUE = HexColor("#1D4ED8")
BLUE_LIGHT = HexColor("#DBEAFE")
PURPLE = HexColor("#6D28D9")
PURPLE_LIGHT = HexColor("#EDE9FE")
GREEN = HexColor("#047857")
GREEN_LIGHT = HexColor("#D1FAE5")
GOLD = HexColor("#B45309")
GOLD_LIGHT = HexColor("#FEF3C7")


class BoxDiagram(Flowable):
    """Canvas-drawn architecture / flow diagram with fixed height."""

    def __init__(self, width: float, height: float, painter) -> None:
        super().__init__()
        self.width = width
        self.height = height
        self.painter = painter

    def wrap(self, availWidth, availHeight):  # noqa: N802
        self.width = min(self.width, availWidth)
        return self.width, self.height

    def draw(self) -> None:
        self.painter(self.canv, self.width, self.height)


def _round_rect(c, x, y, w, h, fill, stroke, radius=6, stroke_width=1.2):
    c.setFillColor(fill)
    c.setStrokeColor(stroke)
    c.setLineWidth(stroke_width)
    c.roundRect(x, y, w, h, radius, fill=1, stroke=1)


def _label(c, text, x, y, size=8, color=SLATE, align="center", bold=False):
    c.setFillColor(color)
    c.setFont("Helvetica-Bold" if bold else "Helvetica", size)
    if align == "center":
        c.drawCentredString(x, y, text)
    elif align == "right":
        c.drawRightString(x, y, text)
    else:
        c.drawString(x, y, text)


def _arrow(c, x1, y1, x2, y2, color=SLATE, label: str | None = None):
    c.setStrokeColor(color)
    c.setFillColor(color)
    c.setLineWidth(1.3)
    c.line(x1, y1, x2, y2)
    # arrow head
    import math

    angle = math.atan2(y2 - y1, x2 - x1)
    size = 6
    ax = x2 - size * math.cos(angle - 0.4)
    ay = y2 - size * math.sin(angle - 0.4)
    bx = x2 - size * math.cos(angle + 0.4)
    by = y2 - size * math.sin(angle + 0.4)
    path = c.beginPath()
    path.moveTo(x2, y2)
    path.lineTo(ax, ay)
    path.lineTo(bx, by)
    path.close()
    c.drawPath(path, fill=1, stroke=0)
    if label:
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2
        c.setFillColor(NAVY)
        c.setFont("Helvetica", 7)
        c.drawCentredString(mx, my + 4, label)


def paint_system_architecture(c, width, height):
    # Background
    c.setFillColor(HexColor("#F8FAFC"))
    c.rect(0, 0, width, height, fill=1, stroke=0)

    # Title band
    _label(c, "Production System Architecture (no mock / offline paths)", width / 2, height - 14, 9, NAVY, bold=True)

    # Layer 1: Validation UI
    _round_rect(c, 18, height - 95, width - 36, 70, BLUE_LIGHT, BLUE, 8)
    _label(c, "Layer 1 — Validation UI", 30, height - 40, 9, BLUE, "left", bold=True)
    _round_rect(c, 40, height - 85, 160, 36, white, BLUE)
    _label(c, "Streamlit test_ui", 120, height - 62, 8, NAVY, bold=True)
    _label(c, "Bot Framework activity", 120, height - 74, 7, SLATE)
    _round_rect(c, 220, height - 85, 170, 36, white, BLUE)
    _label(c, "User Prompt", 305, height - 62, 8, NAVY, bold=True)
    _label(c, "Markdown reply render", 305, height - 74, 7, SLATE)
    _arrow(c, 390, height - 67, 430, height - 67, BLUE)

    # Layer 2: Cognitive Routing
    _round_rect(c, 18, height - 250, width - 36, 140, TEAL_LIGHT, TEAL, 8)
    _label(c, "Layer 2 — Cognitive Routing (copilot_agent)", 30, height - 118, 9, TEAL, "left", bold=True)

    _round_rect(c, 40, height - 175, 130, 44, white, TEAL)
    _label(c, "Flask /api/messages", 105, height - 150, 8, NAVY, bold=True)
    _label(c, "app.py", 105, height - 163, 7, SLATE)

    _round_rect(c, 195, height - 175, 150, 44, white, TEAL)
    _label(c, "LangChain AgentExecutor", 270, height - 148, 7.5, NAVY, bold=True)
    _label(c, "OpenAI tools agent", 270, height - 160, 7, SLATE)
    _label(c, "SYSTEM_PROMPT", 270, height - 171, 7, TEAL)

    _round_rect(c, 370, height - 175, 150, 44, white, ORANGE)
    _label(c, "Azure OpenAI", 445, height - 150, 8, ORANGE, bold=True)
    _label(c, "AzureChatOpenAI", 445, height - 163, 7, SLATE)

    _round_rect(c, 40, height - 235, 200, 44, white, TEAL)
    _label(c, "DualMCPBridge", 140, height - 210, 8, NAVY, bold=True)
    _label(c, "mcp_clients.py — stdio MCP", 140, height - 223, 7, SLATE)

    _round_rect(c, 260, height - 235, 260, 44, PURPLE_LIGHT, PURPLE)
    _label(c, "Cognitive Procedures (prompt-enforced)", 390, height - 208, 7.5, PURPLE, bold=True)
    _label(c, "Compare · Audit · Counter-Clause · Exposure · Renewal", 390, height - 222, 6.5, SLATE)

    _arrow(c, 105, height - 175, 105, height - 191, TEAL)
    _arrow(c, 170, height - 153, 195, height - 153, TEAL)
    _arrow(c, 345, height - 153, 370, height - 153, ORANGE, "LLM")
    _arrow(c, 270, height - 175, 270, height - 191, TEAL)
    _arrow(c, 240, height - 213, 260, height - 213, PURPLE)

    # Layer 3: Data Retrieval
    _round_rect(c, 18, 18, width - 36, 145, GREEN_LIGHT, GREEN, 8)
    _label(c, "Layer 3 — Data Retrieval (mcp_server FastMCP)", 30, 148, 9, GREEN, "left", bold=True)

    tools = [
        ("get_expiring", "contracts", 40),
        ("get_vendor", "spend_summary", 40 + 95),
        ("compare", "contracts", 40 + 190),
        ("check_missing", "contract_fields", 40 + 285),
        ("search_cloud", "blob_contracts", 40 + 380),
    ]
    for line1, line2, x in tools:
        _round_rect(c, x, 95, 88, 38, white, GREEN)
        _label(c, line1, x + 44, 118, 6.5, NAVY, bold=True)
        _label(c, line2, x + 44, 105, 6.5, SLATE)

    _round_rect(c, 40, 35, 150, 45, GOLD_LIGHT, GOLD)
    _label(c, "Microsoft Fabric SQL", 115, 60, 8, GOLD, bold=True)
    _label(c, "Gold contracts / spend", 115, 47, 7, SLATE)

    _round_rect(c, 210, 35, 150, 45, BLUE_LIGHT, BLUE)
    _label(c, "Azure AI Search", 285, 60, 8, BLUE, bold=True)
    _label(c, "semantic hybrid docs", 285, 47, 7, SLATE)

    _round_rect(c, 380, 35, 140, 45, PURPLE_LIGHT, PURPLE)
    _label(c, "Postgres PGVector", 450, 60, 8, PURPLE, bold=True)
    _label(c, "operational memory", 450, 47, 7, SLATE)

    _arrow(c, 140, height - 250, 140, 143, GREEN, "MCP tools")
    _arrow(c, 115, 95, 115, 80, GOLD)
    _arrow(c, 285, 95, 285, 80, BLUE)
    # bridge to pgvector
    _arrow(c, 450, height - 250, 450, 80, PURPLE)


def paint_foundry_deploy(c, width, height):
    c.setFillColor(HexColor("#F8FAFC"))
    c.rect(0, 0, width, height, fill=1, stroke=0)
    _label(c, "Azure AI Foundry Provisioning Path", width / 2, height - 14, 9, NAVY, bold=True)

    steps = [
        (30, "Root .env", "AZURE_FOUNDRY_\nCONNECTION_STRING", TEAL_LIGHT, TEAL),
        (145, "DefaultAzure\nCredential", "Entra ID auth", ORANGE_LIGHT, ORANGE),
        (260, "Import MCP\ntools", "3 Fabric/Search\ncallables", GREEN_LIGHT, GREEN),
        (375, "FunctionTool\n+ ToolSet", "azure-ai-agents", BLUE_LIGHT, BLUE),
        (490, "create_agent", "SYSTEM_PROMPT\ninstructions", PURPLE_LIGHT, PURPLE),
    ]
    y = height / 2 - 10
    for i, (x, title, sub, fill, stroke) in enumerate(steps):
        _round_rect(c, x, y - 25, 100, 70, fill, stroke)
        for j, line in enumerate(title.split("\n")):
            _label(c, line, x + 50, y + 25 - j * 11, 7.5, NAVY, bold=True)
        for j, line in enumerate(sub.split("\n")):
            _label(c, line, x + 50, y - 5 - j * 10, 6.5, SLATE)
        if i < len(steps) - 1:
            _arrow(c, x + 100, y + 10, steps[i + 1][0], y + 10, SLATE)

    _label(
        c,
        "Foundry ToolSet (deploy): get_expiring_contracts · get_vendor_spend_summary · search_cloud_blob_contracts",
        width / 2,
        28,
        7,
        TEAL,
        bold=True,
    )
    _label(
        c,
        "Full local MCP also exposes: compare_contracts · check_missing_contract_fields · fabric_health_check",
        width / 2,
        14,
        6.5,
        SLATE,
    )


def paint_request_flow(c, width, height):
    c.setFillColor(HexColor("#F8FAFC"))
    c.rect(0, 0, width, height, fill=1, stroke=0)
    _label(c, "End-to-End Request Process Flow", width / 2, height - 14, 9, NAVY, bold=True)

    nodes = [
        (width * 0.12, height - 55, "1. User asks\nin Streamlit", BLUE_LIGHT, BLUE),
        (width * 0.38, height - 55, "2. POST\n/api/messages", TEAL_LIGHT, TEAL),
        (width * 0.64, height - 55, "3. Azure OpenAI\nplans tool calls", ORANGE_LIGHT, ORANGE),
        (width * 0.88, height - 55, "4. MCP tools\nexecute", GREEN_LIGHT, GREEN),
        (width * 0.88, height - 150, "5. Evidence\nreturned", GREEN_LIGHT, GREEN),
        (width * 0.64, height - 150, "6. LLM synthesizes\nMarkdown sections", ORANGE_LIGHT, ORANGE),
        (width * 0.38, height - 150, "7. Flask reply\nactivity", TEAL_LIGHT, TEAL),
        (width * 0.12, height - 150, "8. UI renders\nanswer", BLUE_LIGHT, BLUE),
    ]
    box_w, box_h = 95, 48
    centers = []
    for x, y, text, fill, stroke in nodes:
        _round_rect(c, x - box_w / 2, y - box_h / 2, box_w, box_h, fill, stroke)
        lines = text.split("\n")
        for i, line in enumerate(lines):
            _label(c, line, x, y + 8 - i * 11, 7, NAVY, bold=(i == 0))
        centers.append((x, y))

    # arrows along the snake
    order = list(range(8))
    for i in range(len(order) - 1):
        a, b = centers[order[i]], centers[order[i + 1]]
        # shorten endpoints toward target
        _arrow(c, a[0] + (12 if b[0] > a[0] else -12 if b[0] < a[0] else 0),
               a[1] - (18 if b[1] < a[1] else 0),
               b[0] - (12 if b[0] > a[0] else -12 if b[0] < a[0] else 0),
               b[1] + (18 if b[1] < a[1] else 0),
               SLATE)

    # Intent routing strip
    _round_rect(c, 20, 20, width - 40, 70, LIGHT, BORDER, 6)
    _label(c, "Intent → Tool Domain Routing (SYSTEM_PROMPT)", width / 2, 72, 8, NAVY, bold=True)
    domains = [
        ("Financial / dates", "Fabric SQL", GOLD),
        ("Compare / completeness", "Analytics tools", TEAL),
        ("Legal clauses / PDFs", "Azure AI Search", BLUE),
        ("Session memory", "PGVector", PURPLE),
    ]
    for i, (intent, tool, color) in enumerate(domains):
        x = 40 + i * 130
        _round_rect(c, x, 30, 120, 28, white, color)
        _label(c, intent, x + 60, 46, 6.5, NAVY, bold=True)
        _label(c, tool, x + 60, 35, 6.5, color)


def paint_lifecycle_flow(c, width, height):
    c.setFillColor(HexColor("#F8FAFC"))
    c.rect(0, 0, width, height, fill=1, stroke=0)
    _label(c, "Contract Lifecycle Cognitive Procedures — Process Flow", width / 2, height - 14, 9, NAVY, bold=True)

    # Trigger column
    _label(c, "User Intent", 70, height - 40, 8, NAVY, bold=True)
    intents = [
        ("Single-agreement\naudit / red flag", ORANGE),
        ("High-risk clause\nfound", ORANGE),
        ("Penalty / breach\nexposure", GOLD),
        ("Expiring / renew /\nterminate", TEAL),
        ("Compare 2+N\ncontracts", BLUE),
    ]
    for i, (text, color) in enumerate(intents):
        y = height - 90 - i * 52
        _round_rect(c, 20, y, 100, 42, white, color)
        for j, line in enumerate(text.split("\n")):
            _label(c, line, 70, y + 26 - j * 10, 6.5, NAVY)

    # Tools column
    _label(c, "Tools Invoked", 220, height - 40, 8, NAVY, bold=True)
    tool_sets = [
        "check_missing_contract_fields\n+ search_cloud_blob_contracts",
        "search_cloud_blob_contracts\n(clause evidence)",
        "get_vendor_spend_summary\n+ expiring / compare + search",
        "get_expiring_contracts\n+ get_vendor_spend_summary",
        "compare_contracts\n+ spend + search",
    ]
    for i, text in enumerate(tool_sets):
        y = height - 90 - i * 52
        _round_rect(c, 140, y, 160, 42, GREEN_LIGHT, GREEN)
        for j, line in enumerate(text.split("\n")):
            _label(c, line, 220, y + 26 - j * 10, 6.2, SLATE)
        _arrow(c, 120, y + 21, 140, y + 21, BORDER)

    # Procedure column
    _label(c, "Required Markdown Output", 420, height - 40, 8, NAVY, bold=True)
    procs = [
        ("## Red-Flag Compliance Audit", ORANGE),
        ("## Dynamic Counter-Clause Drafting", ORANGE),
        ("## Financial Exposure Projection", GOLD),
        ("## Proactive Renewal Strategy Sheet", TEAL),
        ("## Recommendation", BLUE),
    ]
    for i, (text, color) in enumerate(procs):
        y = height - 90 - i * 52
        _round_rect(c, 320, y, 220, 42, white, color)
        _label(c, text, 430, y + 18, 7, color, bold=True)
        _arrow(c, 300, y + 21, 320, y + 21, BORDER)

    _round_rect(c, 20, 12, width - 40, 28, PURPLE_LIGHT, PURPLE, 5)
    _label(
        c,
        "When multiple procedures apply: Audit → Counter-Clause → Exposure → Renewal → Recommendation",
        width / 2,
        22,
        7,
        PURPLE,
        bold=True,
    )


def paint_compare_flow(c, width, height):
    c.setFillColor(HexColor("#F8FAFC"))
    c.rect(0, 0, width, height, fill=1, stroke=0)
    _label(c, "Comparative Analysis Decision Framework", width / 2, height - 14, 9, NAVY, bold=True)

    stages = [
        (40, "1. Quantitative\nComparison", "ACV, tenure,\nauto-renew, spend", GOLD_LIGHT, GOLD),
        (200, "2. Risk &\nLiability", "caps, indemnity,\nSLA, exit terms", ORANGE_LIGHT, ORANGE),
        (360, "3. Explicit\nSuggestion", "## Recommendation\nwinner + rationale", BLUE_LIGHT, BLUE),
    ]
    for i, (x, title, sub, fill, stroke) in enumerate(stages):
        _round_rect(c, x, height / 2 - 20, 130, 80, fill, stroke)
        for j, line in enumerate(title.split("\n")):
            _label(c, line, x + 65, height / 2 + 35 - j * 11, 8, NAVY, bold=True)
        for j, line in enumerate(sub.split("\n")):
            _label(c, line, x + 65, height / 2 - 5 - j * 10, 6.5, SLATE)
        if i < len(stages) - 1:
            _arrow(c, x + 130, height / 2 + 20, stages[i + 1][0], height / 2 + 20, SLATE)

    _label(c, "Supports N-way compare via comma-separated contract_refs / supplier_names / …", width / 2, 30, 7, TEAL, bold=True)


def build_pdf(path: Path) -> None:
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        name="CoverTitle", fontName="Helvetica-Bold", fontSize=20,
        textColor=NAVY, alignment=TA_CENTER, spaceAfter=8, leading=24,
    ))
    styles.add(ParagraphStyle(
        name="CoverSub", fontName="Helvetica", fontSize=11,
        textColor=SLATE, alignment=TA_CENTER, spaceAfter=5, leading=14,
    ))
    styles.add(ParagraphStyle(
        name="H1", fontName="Helvetica-Bold", fontSize=13,
        textColor=NAVY, spaceBefore=10, spaceAfter=6, leading=16,
    ))
    styles.add(ParagraphStyle(
        name="Body", fontName="Helvetica", fontSize=9.5,
        textColor=SLATE, spaceAfter=5, leading=13,
    ))
    styles.add(ParagraphStyle(
        name="ArchBullet", fontName="Helvetica", fontSize=9,
        textColor=SLATE, leading=12, leftIndent=10,
    ))
    styles.add(ParagraphStyle(
        name="Caption", fontName="Helvetica-Oblique", fontSize=8,
        textColor=HexColor("#64748B"), alignment=TA_CENTER, spaceBefore=2, spaceAfter=8,
    ))
    styles.add(ParagraphStyle(
        name="Footer", fontName="Helvetica", fontSize=8,
        textColor=HexColor("#64748B"), alignment=TA_CENTER,
    ))

    page_w = letter[0] - 1.2 * inch
    story: list = []

    # Cover
    story.append(Spacer(1, 1.5 * inch))
    story.append(Paragraph("VAL CoPilot", styles["CoverTitle"]))
    story.append(Paragraph("Architecture &amp; Process Flow", styles["CoverTitle"]))
    story.append(Spacer(1, 0.2 * inch))
    story.append(HRFlowable(width="80%", thickness=1, color=TEAL, spaceBefore=4, spaceAfter=10))
    story.append(Paragraph(
        "Production architecture for the three-layer monorepo and the cognitive "
        "contract-lifecycle procedures introduced in the orchestrator.",
        styles["CoverSub"],
    ))
    story.append(Spacer(1, 0.15 * inch))
    story.append(Paragraph("Scope: production runtime only", styles["CoverSub"]))
    story.append(Paragraph(
        "Excluded: USE_OFFLINE_MOCKS, offline cognitive router, test fixtures",
        styles["CoverSub"],
    ))
    story.append(Spacer(1, 0.35 * inch))
    story.append(Paragraph("<b>Contents</b>", styles["CoverSub"]))
    for item in [
        "1. System architecture (UI → Agent → MCP → Azure data)",
        "2. End-to-end request process flow",
        "3. Contract lifecycle cognitive procedures",
        "4. Comparative analysis decision framework",
        "5. Azure AI Foundry provisioning path",
        "6. Component &amp; change summary",
    ]:
        story.append(Paragraph(item, styles["CoverSub"]))
    story.append(PageBreak())

    # Page 2 - architecture
    story.append(Paragraph("1. Production System Architecture", styles["H1"]))
    story.append(Paragraph(
        "VAL CoPilot is a three-layer monorepo. The Validation UI submits Bot Framework "
        "activities to the Cognitive Routing agent. The agent uses Azure OpenAI tool-calling "
        "guided by <b>SYSTEM_PROMPT</b>, then invokes MCP tools in the Data Retrieval layer "
        "to ground answers in Fabric SQL and Azure AI Search (plus optional PGVector memory).",
        styles["Body"],
    ))
    story.append(BoxDiagram(page_w, 380, paint_system_architecture))
    story.append(Paragraph("Figure 1 — Layered production architecture", styles["Caption"]))
    story.append(PageBreak())

    # Page 3 - request flow
    story.append(Paragraph("2. End-to-End Request Process Flow", styles["H1"]))
    story.append(Paragraph(
        "Every production turn follows the same control loop: UI ingress → Flask → LangChain "
        "AgentExecutor → Azure OpenAI tool plan → MCP tool execution → evidence synthesis → "
        "Markdown reply. No mock interceptors participate in this path.",
        styles["Body"],
    ))
    story.append(BoxDiagram(page_w, 280, paint_request_flow))
    story.append(Paragraph("Figure 2 — Request lifecycle", styles["Caption"]))
    story.append(Paragraph("Key production files", styles["H1"]))
    for line in [
        "• <font face='Courier'>test_ui/app.py</font> — Streamlit Bot Framework harness",
        "• <font face='Courier'>copilot_agent/app.py</font> — Flask <font face='Courier'>/api/messages</font>",
        "• <font face='Courier'>copilot_agent/agent.py</font> — SYSTEM_PROMPT + AgentExecutor",
        "• <font face='Courier'>copilot_agent/mcp_clients.py</font> — dual MCP stdio bridge",
        "• <font face='Courier'>mcp_server/server.py</font> — FastMCP Fabric / Search tools",
        "• <font face='Courier'>mcp_server/fabric_sql.py</font> / <font face='Courier'>azure_search.py</font> — data access",
    ]:
        story.append(Paragraph(line, styles["ArchBullet"]))
    story.append(PageBreak())

    # Page 4 - lifecycle
    story.append(Paragraph("3. Contract Lifecycle Cognitive Procedures", styles["H1"]))
    story.append(Paragraph(
        "Advanced analysis is enforced in the orchestrator prompt (not in MCP tool bodies). "
        "Each procedure ends in a dedicated Markdown section with actionable recommendations.",
        styles["Body"],
    ))
    story.append(BoxDiagram(page_w, 360, paint_lifecycle_flow))
    story.append(Paragraph("Figure 3 — Intent → tools → Markdown procedure sections", styles["Caption"]))
    story.append(PageBreak())

    # Page 5 - compare + foundry
    story.append(Paragraph("4. Comparative Analysis Decision Framework", styles["H1"]))
    story.append(Paragraph(
        "For compare intents (including N-way), the agent must not merely juxtapose excerpts. "
        "It ranks candidates using quantitative and risk criteria, then emits "
        "<b>## Recommendation</b>.",
        styles["Body"],
    ))
    story.append(BoxDiagram(page_w, 160, paint_compare_flow))
    story.append(Paragraph("Figure 4 — Compare decision framework", styles["Caption"]))

    story.append(Paragraph("5. Azure AI Foundry Provisioning Path", styles["H1"]))
    story.append(Paragraph(
        "<font face='Courier'>copilot_agent/deploy_to_foundry.py</font> provisions a managed "
        "Foundry agent with the same SYSTEM_PROMPT and a FunctionTool ToolSet wrapping core "
        "Fabric / Search MCP implementations.",
        styles["Body"],
    ))
    story.append(BoxDiagram(page_w, 160, paint_foundry_deploy))
    story.append(Paragraph("Figure 5 — Foundry deployment process", styles["Caption"]))
    story.append(PageBreak())

    # Page 6 - change summary
    story.append(Paragraph("6. Component &amp; Change Summary", styles["H1"]))
    story.append(Paragraph(
        "Capabilities delivered in the production architecture (excluding staging mocks):",
        styles["Body"],
    ))
    changes = [
        "<b>Data Retrieval MCP</b> — Fabric Gold tools for expiring contracts, vendor spend, "
        "N-way compare, missing-field completeness; Azure AI Search hybrid semantic search; "
        "shared lookup dimensions (ContractID, SupplierName, ContractName, ContractType, ACV).",
        "<b>Cognitive Routing</b> — LangChain OpenAI-tools agent with strict domain routing; "
        "Comparative Analysis framework; four lifecycle procedures with mandatory Markdown sections.",
        "<b>Validation UI</b> — Streamlit emulator posting Bot Framework activities to "
        "<font face='Courier'>POST /api/messages</font> and rendering Markdown replies.",
        "<b>Foundry deploy</b> — DefaultAzureCredential + ToolSet/FunctionTool provisioning script "
        "driven by <font face='Courier'>AZURE_FOUNDRY_CONNECTION_STRING</font>.",
        "<b>Config boundary</b> — single root <font face='Courier'>.env</font>; MCP remains "
        "free of orchestration / LLM logic.",
    ]
    for item in changes:
        story.append(Paragraph(f"• {item}", styles["ArchBullet"]))
        story.append(Spacer(1, 4))

    story.append(Spacer(1, 10))
    story.append(Paragraph("MCP tools (production fabric_data server)", styles["H1"]))
    for t in [
        "get_expiring_contracts",
        "get_vendor_spend_summary",
        "compare_contracts",
        "check_missing_contract_fields",
        "search_cloud_blob_contracts",
        "fabric_health_check",
    ]:
        story.append(Paragraph(f"• <font face='Courier'>{t}</font>", styles["ArchBullet"]))

    story.append(Spacer(1, 12))
    story.append(HRFlowable(width="100%", thickness=0.8, color=BORDER))
    story.append(Paragraph(
        "VAL CoPilot · Architecture &amp; Process Flow · Production paths only",
        styles["Footer"],
    ))

    def on_page(canvas_obj, doc):
        canvas_obj.saveState()
        canvas_obj.setFont("Helvetica", 8)
        canvas_obj.setFillColor(HexColor("#64748B"))
        canvas_obj.drawCentredString(
            letter[0] / 2,
            0.45 * inch,
            f"VAL CoPilot Architecture · Page {doc.page}",
        )
        canvas_obj.restoreState()

    path.parent.mkdir(parents=True, exist_ok=True)
    doc = BaseDocTemplate(
        str(path),
        pagesize=letter,
        title="VAL CoPilot Architecture and Process Flow",
        author="VAL CoPilot",
    )
    frame = Frame(
        0.6 * inch,
        0.65 * inch,
        letter[0] - 1.2 * inch,
        letter[1] - 1.2 * inch,
        id="normal",
    )
    doc.addPageTemplates([PageTemplate(id="main", frames=frame, onPage=on_page)])
    doc.build(story)


def main() -> None:
    build_pdf(PDF_PATH)
    ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
    ARTIFACT.write_bytes(PDF_PATH.read_bytes())
    print(f"Wrote {PDF_PATH} ({PDF_PATH.stat().st_size} bytes)")
    print(f"Wrote {ARTIFACT} ({ARTIFACT.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
