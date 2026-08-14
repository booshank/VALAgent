#!/usr/bin/env python3
"""Generate VAL CoPilot Architecture & Process Flow PDF (tool-layer POC)."""

from __future__ import annotations

from pathlib import Path

from reportlab.lib.colors import HexColor, white, black
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    HRFlowable,
    KeepTogether,
    ListFlowable,
    ListItem,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

OUT = Path(__file__).resolve().parent / "VAL_CoPilot_Architecture_and_Process_Flow.pdf"
ARTIFACT = Path("/opt/cursor/artifacts/VAL_CoPilot_Architecture_and_Process_Flow.pdf")

NAVY = HexColor("#0B1F3A")
STEEL = HexColor("#1F4E79")
TEAL = HexColor("#0E7C7B")
AMBER = HexColor("#C27A00")
SOFT = HexColor("#EEF3F8")
SOFT_TEAL = HexColor("#E8F5F4")
SOFT_AMBER = HexColor("#FFF6E8")
LINE = HexColor("#C9D3DF")
MUTED = HexColor("#5B6B7C")
DARK = HexColor("#1A2332")


def styles():
    base = getSampleStyleSheet()
    return {
        "cover_title": ParagraphStyle(
            "cover_title", parent=base["Title"], fontName="Helvetica-Bold",
            fontSize=26, leading=32, textColor=white, alignment=TA_CENTER, spaceAfter=10,
        ),
        "cover_sub": ParagraphStyle(
            "cover_sub", parent=base["Normal"], fontName="Helvetica",
            fontSize=12, leading=16, textColor=HexColor("#D6E4F5"), alignment=TA_CENTER, spaceAfter=6,
        ),
        "h1": ParagraphStyle(
            "h1", parent=base["Heading1"], fontName="Helvetica-Bold",
            fontSize=16, leading=20, textColor=NAVY, spaceBefore=4, spaceAfter=8,
        ),
        "h2": ParagraphStyle(
            "h2", parent=base["Heading2"], fontName="Helvetica-Bold",
            fontSize=12, leading=15, textColor=STEEL, spaceBefore=10, spaceAfter=5,
        ),
        "body": ParagraphStyle(
            "body", parent=base["Normal"], fontName="Helvetica",
            fontSize=9.5, leading=13, textColor=DARK, alignment=TA_JUSTIFY, spaceAfter=6,
        ),
        "bullet": ParagraphStyle(
            "bullet", parent=base["Normal"], fontName="Helvetica",
            fontSize=9.5, leading=12.5, textColor=DARK, leftIndent=4, spaceAfter=2,
        ),
        "caption": ParagraphStyle(
            "caption", parent=base["Normal"], fontName="Helvetica-Oblique",
            fontSize=8, leading=10, textColor=MUTED, alignment=TA_CENTER, spaceBefore=4, spaceAfter=8,
        ),
        "box_title": ParagraphStyle(
            "box_title", parent=base["Normal"], fontName="Helvetica-Bold",
            fontSize=9, leading=11, textColor=NAVY, alignment=TA_CENTER, spaceAfter=3,
        ),
        "box_body": ParagraphStyle(
            "box_body", parent=base["Normal"], fontName="Helvetica",
            fontSize=8, leading=10.5, textColor=DARK, alignment=TA_CENTER,
        ),
        "small": ParagraphStyle(
            "small", parent=base["Normal"], fontName="Helvetica",
            fontSize=8, leading=10.5, textColor=DARK, alignment=TA_LEFT,
        ),
        "footer": ParagraphStyle(
            "footer", parent=base["Normal"], fontName="Helvetica",
            fontSize=7.5, textColor=MUTED, alignment=TA_CENTER,
        ),
        "mono": ParagraphStyle(
            "mono", parent=base["Normal"], fontName="Courier",
            fontSize=8, leading=10.5, textColor=DARK, alignment=TA_LEFT,
        ),
    }


def bullets(items, style):
    return ListFlowable(
        [ListItem(Paragraph(i, style), leftIndent=12, bulletColor=STEEL) for i in items],
        bulletType="bullet", start="circle", leftIndent=14, bulletFontSize=7,
    )


def layer_box(title, body, bg, s):
    data = [[Paragraph(title, s["box_title"])], [Paragraph(body, s["box_body"])]]
    t = Table(data, colWidths=[6.8 * inch])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), bg),
        ("BOX", (0, 0), (-1, -1), 1, STEEL),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    return t


def arrow(s):
    return Paragraph("↓", ParagraphStyle(
        "arr", parent=s["body"], alignment=TA_CENTER, fontSize=12,
        textColor=STEEL, spaceBefore=2, spaceAfter=2,
    ))


def section_rule():
    return HRFlowable(width="100%", thickness=1, color=LINE, spaceBefore=2, spaceAfter=8)


def footer(canvas, doc):
    canvas.saveState()
    canvas.setStrokeColor(LINE)
    canvas.setLineWidth(0.5)
    canvas.line(0.7 * inch, 0.55 * inch, letter[0] - 0.7 * inch, 0.55 * inch)
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(MUTED)
    canvas.drawString(0.7 * inch, 0.35 * inch, "VAL CoPilot — Synthetic Contract Intelligence Tool-Layer POC")
    canvas.drawRightString(letter[0] - 0.7 * inch, 0.35 * inch, f"Page {doc.page}")
    canvas.restoreState()


def cover_bg(canvas, doc):
    canvas.saveState()
    canvas.setFillColor(NAVY)
    canvas.rect(0, 0, letter[0], letter[1], fill=1, stroke=0)
    canvas.setFillColor(STEEL)
    canvas.rect(0, letter[1] - 1.8 * inch, letter[0], 1.8 * inch, fill=1, stroke=0)
    canvas.setFillColor(TEAL)
    canvas.rect(0, 0, letter[0], 0.35 * inch, fill=1, stroke=0)
    canvas.restoreState()
    footer(canvas, doc)


def build():
    s = styles()
    doc = SimpleDocTemplate(
        str(OUT), pagesize=letter,
        leftMargin=0.7 * inch, rightMargin=0.7 * inch,
        topMargin=0.65 * inch, bottomMargin=0.75 * inch,
    )
    story = []

    # Cover
    story.append(Spacer(1, 2.2 * inch))
    story.append(Paragraph("VAL CoPilot", s["cover_title"]))
    story.append(Paragraph(
        "Architecture &amp; Process Flow<br/>Synthetic Contract Intelligence Tool-Layer POC",
        s["cover_sub"],
    ))
    story.append(Spacer(1, 0.35 * inch))
    story.append(Paragraph(
        "Current runtime: Streamlit → Flask Cognitive Router → FastMCP Tools → LinkSquares Fixtures<br/>"
        "+ Persona memory (save / recall / delete) · Compare hard-stop",
        s["cover_sub"],
    ))
    story.append(Spacer(1, 1.6 * inch))
    story.append(Paragraph("Internal Engineering Document · Updated August 2026", s["cover_sub"]))
    story.append(PageBreak())

    # 1 Scope
    story.append(Paragraph("1. Purpose &amp; Scope", s["h1"]))
    story.append(section_rule())
    story.append(Paragraph(
        "VAL CoPilot is a <b>synthetic contract intelligence tool-layer POC</b>. It proves that structured "
        "contract analytics can be exposed as MCP tools and consumed by a cognitive router that produces "
        "deterministic lifecycle workflows. The validated runtime is "
        "<b>Streamlit → Flask → FastMCP → LinkSquares fixtures</b>. It does not claim live Fabric / "
        "LinkSquares production connectivity.",
        s["body"],
    ))
    story.append(Paragraph("In scope", s["h2"]))
    story.append(bullets([
        "Synthetic Gold contract data via <b>LinkSquares</b> offline fixtures "
        "(<font face='Courier'>LinSquare_Contracts_100_Updated_30bb.json</font> + "
        "<font face='Courier'>agreement_9a06.json</font>; <font face='Courier'>USE_OFFLINE_MOCKS=true</font>)",
        "FastMCP tool layer: search, profiles, renewals, spend rollups, overlaps, risk, "
        "<b>N-way compare</b>, missing-field checks",
        "Cognitive router: Azure OpenAI + LangChain tool-calling, or offline keyword router",
        "Hard OOS guardrail for invoice/spend linkage requests",
        "Compare hard-stop when suppliers/IDs are missing (no default CON-0001/CON-0002 pair)",
        "Persona memory: save / pin / filter / retrieve / <b>delete</b> previous searches and conversations",
        "Streamlit Validation UI for local demos",
    ], s["bullet"]))
    story.append(Paragraph("Out of scope for this POC", s["h2"]))
    story.append(bullets([
        "Invoice / AP / spend-actuals data linkage (separate future POC)",
        "Live LinkSquares production ingestion (fixtures stand in today; same ContractRepository later)",
        "Azure AI Foundry / managed-agent deployment (removed from this clean POC copy)",
        "Production Teams bot hosting as the primary demo path",
        "Claiming live Fabric SQL as the current validated demo path",
    ], s["bullet"]))
    story.append(PageBreak())

    # 2 Architecture
    story.append(Paragraph("2. Current Runtime Architecture", s["h1"]))
    story.append(section_rule())
    story.append(Paragraph(
        "Four layers. Local Streamlit + Flask + FastMCP is the sole validated POC path.",
        s["body"],
    ))
    story.append(layer_box(
        "LAYER 1 — Validation UI",
        "Streamlit test_ui/app.py · http://localhost:8501 · POST /api/messages<br/>"
        "Sidebar: persona picker · Saved searches · Delete prior conversations",
        SOFT, s,
    ))
    story.append(arrow(s))
    story.append(layer_box(
        "LAYER 2 — Cognitive Routing + Persona Memory",
        "Flask copilot_agent · AzureChatOpenAI + AgentExecutor, or offline_router.py<br/>"
        "Lifecycle procedures · Invoice/spend OOS · Compare hard-stop · /api/memory/* REST<br/>"
        "SQLite memory/store.py (data/persona_memory.sqlite)",
        SOFT_TEAL, s,
    ))
    story.append(arrow(s))
    story.append(layer_box(
        "LAYER 3 — Data Retrieval (MCP Tools)",
        "FastMCP mcp_server · ContractRepository · analytics + risk helpers<br/>"
        "search_contracts · get_contract_profile · compare_contracts · check_missing_contract_fields<br/>"
        "get_expiring_contracts · get_vendor_spend_summary · find_overlaps · explain_contract_risk<br/>"
        "search_cloud_blob_contracts · fabric_health_check",
        SOFT, s,
    ))
    story.append(arrow(s))
    story.append(layer_box(
        "LAYER 4 — Synthetic Gold Data (LinkSquares fixtures)",
        "LinSquare_Contracts_100_Updated_30bb.json + agreement_9a06.json via linksquares_fixtures.py<br/>"
        "Future: live Fabric SQL / LinkSquares behind the same ContractRepository interface",
        SOFT_AMBER, s,
    ))
    story.append(Paragraph(
        "Figure 1 — Current POC runtime (Streamlit → Flask → FastMCP → LinkSquares fixtures).",
        s["caption"],
    ))

    story.append(Paragraph("Request path", s["h2"]))
    path = [
        ["Step", "Component", "Action"],
        ["1", "Validation UI", "User asks a contract question (optional: recall saved search)"],
        ["2", "Cognitive Router", "OOS / hard-stop / memory-recall → tool plan → MCP calls"],
        ["3", "MCP Tools", "Repository + analytics/risk/compare helpers"],
        ["4", "Synthetic Gold", "LinkSquares fixture rows (or future Fabric/LinkSquares)"],
        ["5", "Cognitive Router", "Lifecycle Markdown + ## Recommendation (skipped on hard-stop)"],
        ["6", "Validation UI", "Render answer; auto-save search-like queries to persona memory"],
    ]
    cell = s["small"]
    hdr = ParagraphStyle("th", parent=cell, fontName="Helvetica-Bold", textColor=white)
    tdata = [[Paragraph(c, hdr if r == 0 else cell) for c in row] for r, row in enumerate(path)]
    t = Table(tdata, colWidths=[0.6 * inch, 1.6 * inch, 4.6 * inch])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("BACKGROUND", (0, 1), (-1, -1), SOFT),
        ("TEXTCOLOR", (0, 0), (-1, 0), white),
        ("GRID", (0, 0), (-1, -1), 0.4, LINE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(t)
    story.append(PageBreak())

    # 3 Tools
    story.append(Paragraph("3. MCP Tool Inventory", s["h1"]))
    story.append(section_rule())
    story.append(Paragraph(
        "All tools are served by FastMCP. Structured contract tools are the primary POC surface.",
        s["body"],
    ))
    tools = [
        ["Tool", "Purpose", "Notes"],
        ["search_contracts", "Structured metadata search", "Vendor/BU/status/type; not-present if empty"],
        ["get_contract_profile", "Full contract record", "By ContractID; not-present if missing"],
        ["compare_contracts", "Pairwise / N-way compare", "Any IDs; hard-stop if unresolved"],
        ["check_missing_contract_fields", "Incomplete field scan", "Commercial completeness"],
        ["get_expiring_contracts", "Renewal window", "DaysAhead; notice fields"],
        ["get_vendor_spend_summary", "Committed value rollup", "Not invoice actuals"],
        ["find_overlaps", "Same-vendor date overlaps", "OverlapFlag-aware"],
        ["explain_contract_risk", "Structured risk brief", "facts / risks / gaps / action"],
        ["search_cloud_blob_contracts", "Clause / doc search", "Azure AI Search path"],
        ["fabric_health_check", "Connectivity probe", "Offline health OK"],
    ]
    tdata = [[Paragraph(c, hdr if r == 0 else cell) for c in row] for r, row in enumerate(tools)]
    t = Table(tdata, colWidths=[2.0 * inch, 2.2 * inch, 2.6 * inch])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("BACKGROUND", (0, 1), (-1, -1), white),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [white, SOFT]),
        ("GRID", (0, 0), (-1, -1), 0.4, LINE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(t)
    story.append(Spacer(1, 0.12 * inch))
    story.append(Paragraph(
        "<b>Hard OOS guardrail:</b> invoice/spend-actuals questions never call tools. Exact reply:<br/>"
        "<font face='Courier'>Invoice/spend data is not part of this synthetic contract intelligence POC. "
        "This requires a separate data-linkage POC.</font>",
        s["body"],
    ))
    story.append(Spacer(1, 0.08 * inch))
    story.append(Paragraph(
        "<b>Compare hard-stop:</b> if any requested supplier or contract ID cannot be resolved, "
        "return <b>only</b> this message — no table, no recommendation, no default CON-0001/CON-0002 pair:<br/>"
        "<font face='Courier'>The contract information requested for the comparison is not available at the moment</font>",
        s["body"],
    ))
    story.append(PageBreak())

    # 4 Repo + risk
    story.append(Paragraph("4. Repository Abstraction &amp; Risk Helpers", s["h1"]))
    story.append(section_rule())
    story.append(Paragraph(
        "<font face='Courier'>ContractRepository</font> isolates tool handlers from storage. "
        "Offline fixtures and future Fabric SQL share the same interface "
        "(<font face='Courier'>list_all</font>, <font face='Courier'>get_by_id</font>, "
        "<font face='Courier'>search</font>, <font face='Courier'>get_by_vendor</font>).",
        s["body"],
    ))
    story.append(Paragraph("Risk helpers (<font face='Courier'>contract_risk.py</font>)", s["h2"]))
    story.append(bullets([
        "<b>find_overlaps</b> — same-vendor Active/Pending contracts with overlapping date windows",
        "<b>explain_contract_risk</b> — returns known_facts, computed_risks, missing_data, recommended_review_action",
        "Demo seed: Microsoft CON-0024 ∩ CON-0029 overlap (OverlapFlag=Yes)",
    ], s["bullet"]))
    story.append(PageBreak())

    # 5 Lifecycle
    story.append(Paragraph("5. Lifecycle Procedures (Cognitive Layer)", s["h1"]))
    story.append(section_rule())
    story.append(Paragraph(
        "Encoded in <font face='Courier'>SYSTEM_PROMPT</font> and mirrored by "
        "<font face='Courier'>offline_router.py</font>. Successful answers end with "
        "<font face='Courier'>## Recommendation</font>. "
        "<b>Exception:</b> compare hard-stop and invoice OOS return a single exact message only.",
        s["body"],
    ))
    procs = [
        ["Procedure", "Trigger", "Output sections"],
        ["Red-Flag Audit", "Risk / compliance / audit", "Risk Register · Missing Protections · ## Recommendation"],
        ["Counter-Clause Drafting", "Negotiate / rewrite", "Weak Language · Counter-Clause · ## Recommendation"],
        ["Financial Exposure", "Liability / TCV / exposure", "Exposure Summary · Liability Map · ## Recommendation"],
        ["Renewal Strategy", "Renew / expire / notice", "Timeline · Decision Matrix · ## Recommendation"],
        ["Comparative Analysis", "Compare succeeds", "Side-by-Side · Trade-offs · ## Recommendation"],
        ["Compare hard-stop", "Any compare side unresolved", "Exact unavailable message only (no table)"],
        ["Persona memory recall", "Previous / saved searches", "SQLite recall via /api/memory/*"],
    ]
    tdata = [[Paragraph(c, hdr if r == 0 else cell) for c in row] for r, row in enumerate(procs)]
    t = Table(tdata, colWidths=[1.7 * inch, 1.8 * inch, 3.3 * inch])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [white, SOFT]),
        ("GRID", (0, 0), (-1, -1), 0.4, LINE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(t)
    story.append(PageBreak())

    # 6 Sequence
    story.append(Paragraph("6. Process Flow — Example Sequences", s["h1"]))
    story.append(section_rule())
    story.append(Paragraph("A. Happy path (renewal)", s["h2"]))
    story.append(bullets([
        "UI → Router: “Which contracts expire in 90 days?”",
        "Router → get_expiring_contracts(90)",
        "MCP → repository filter by EndDate window",
        "Router → Renewal Strategy Sheet + ## Recommendation",
    ], s["bullet"]))
    story.append(Paragraph("B. Overlap / risk path", s["h2"]))
    story.append(bullets([
        "UI → Router: “Any overlapping Microsoft contracts?”",
        "Router → find_overlaps / explain_contract_risk / search_contracts",
        "MCP → risk helpers over repository rows",
        "Router → Red-Flag Audit + ## Recommendation",
    ], s["bullet"]))
    story.append(Paragraph("C. OOS short-circuit", s["h2"]))
    story.append(bullets([
        "UI → Router: “Show invoice totals for Microsoft”",
        "Router detects invoice/spend intent <b>before tools</b>",
        "Exact OOS message returned; no MCP calls",
    ], s["bullet"]))
    story.append(Paragraph("D. Compare hard-stop (missing supplier / ID)", s["h2"]))
    story.append(bullets([
        "UI → Router: “Compare Acme vs Zeta” (or unknown CON-* IDs)",
        "Compare intent forced through offline router (no LLM default pair)",
        "MCP / resolver cannot resolve one or more sides",
        "Return <b>only</b>: “The contract information requested for the comparison is not available at the moment”",
        "No comparative table, no ## Recommendation, no CON-0001 vs CON-0002 fallback",
    ], s["bullet"]))
    story.append(Paragraph("E. Persona memory recall", s["h2"]))
    story.append(bullets([
        "UI → Router: “Show my previous Microsoft searches” (or sidebar Saved searches)",
        "Memory-recall intent forced through offline persona store",
        "Flask <font face='Courier'>/api/memory/recall</font> or Streamlit sidebar → SQLite",
        "Return prior queries / pinned searches for that persona",
    ], s["bullet"]))
    story.append(PageBreak())

    # 7 Local
    story.append(Paragraph("7. Local Runtime Topology", s["h1"]))
    story.append(section_rule())
    ports = [
        ["Process", "Command", "Port / URL"],
        ["MCP server", "python mcp_server/server.py", "stdio (no HTTP port)"],
        ["Cognitive router", "python copilot_agent/app.py", "http://localhost:3978"],
        ["Validation UI", "streamlit run test_ui/app.py", "http://localhost:8501"],
    ]
    tdata = [[Paragraph(c, hdr if r == 0 else cell) for c in row] for r, row in enumerate(ports)]
    t = Table(tdata, colWidths=[1.5 * inch, 2.6 * inch, 2.7 * inch])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [white, SOFT]),
        ("GRID", (0, 0), (-1, -1), 0.4, LINE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(t)
    story.append(Spacer(1, 0.1 * inch))
    story.append(Paragraph("Offline demo flags", s["h2"]))
    story.append(Paragraph(
        "<font face='Courier'>USE_OFFLINE_MOCKS=true</font><br/>"
        "<font face='Courier'>AZURE_OPENAI_FORCE_OFFLINE=true</font> "
        "(optional — keyword router, no Azure OpenAI)",
        s["mono"],
    ))
    story.append(Paragraph("Verification", s["h2"]))
    story.append(bullets([
        "<font face='Courier'>python mcp_server/test_offline_mocks.py</font>",
        "<font face='Courier'>python copilot_agent/test_poc_guards.py</font>",
        "Demo script: <font face='Courier'>docs/demo_script.md</font> (deterministic questions)",
        "Persona memory: <font face='Courier'>python memory/test_store.py</font>",
        "POC changes reference: <font face='Courier'>docs/VAL_CoPilot_POC_Changes_and_Scripts.md</font>",
    ], s["bullet"]))
    story.append(PageBreak())

    # 8 Local run notes
    story.append(Paragraph("8. Local Run Notes", s["h1"]))
    story.append(section_rule())
    story.append(Paragraph("POC path (required for demos)", s["h2"]))
    story.append(bullets([
        "Run Flask cognitive router + Streamlit UI locally with LinkSquares offline fixtures",
        "Persona memory SQLite under <font face='Courier'>data/persona_memory.sqlite</font> "
        "(override with <font face='Courier'>VAL_MEMORY_DB</font>)",
        "Delete prior conversations from the Streamlit sidebar or via "
        "<font face='Courier'>DELETE /api/memory/conversations</font>",
        "Do not commit <font face='Courier'>.env</font> (gitignored; use <font face='Courier'>.env.example</font>)",
    ], s["bullet"]))
    story.append(PageBreak())

    # 9 Future
    story.append(Paragraph("9. Evolution Roadmap", s["h1"]))
    story.append(section_rule())
    story.append(bullets([
        "<b>Now:</b> LinkSquares fixtures + full MCP tools + cognitive router + Streamlit + persona memory",
        "<b>Next:</b> Live Fabric SQL / Azure AI Search behind the same ContractRepository",
        "<b>Later:</b> Live LinkSquares as source behind ContractRepository (tool contracts unchanged)",
        "<b>Separate track:</b> Invoice / spend-actuals data-linkage POC",
    ], s["bullet"]))
    story.append(Spacer(1, 0.25 * inch))
    story.append(Paragraph("Related artifacts", s["h2"]))
    story.append(bullets([
        "<font face='Courier'>docs/VAL_CoPilot_Architecture_and_Process_Flow.pptx</font>",
        "<font face='Courier'>docs/VAL_CoPilot_POC_Changes_and_Scripts.md</font>",
        "<font face='Courier'>docs/VAL_CoPilot_Python_Procedures_Catalog.xlsx</font>",
        "<font face='Courier'>docs/demo_script.md</font>",
        "<font face='Courier'>mcp_server/server.py</font>, <font face='Courier'>linksquares_fixtures.py</font>, "
        "<font face='Courier'>contract_repository.py</font>, <font face='Courier'>contract_risk.py</font>",
        "<font face='Courier'>copilot_agent/agent.py</font>, <font face='Courier'>offline_router.py</font>, "
        "<font face='Courier'>app.py</font>",
        "<font face='Courier'>memory/store.py</font>, <font face='Courier'>test_ui/app.py</font>",
    ], s["bullet"]))
    story.append(Spacer(1, 0.35 * inch))
    story.append(HRFlowable(width="100%", thickness=1.5, color=NAVY, spaceBefore=4, spaceAfter=8))
    story.append(Paragraph(
        "End of document — Synthetic Contract Intelligence Tool-Layer POC · August 2026",
        s["caption"],
    ))

    def first_page(canvas, doc_):
        cover_bg(canvas, doc_)

    def later(canvas, doc_):
        canvas.saveState()
        canvas.setFillColor(SOFT)
        canvas.rect(0, letter[1] - 0.4 * inch, letter[0], 0.4 * inch, fill=1, stroke=0)
        canvas.setStrokeColor(TEAL)
        canvas.setLineWidth(2)
        canvas.line(0, letter[1] - 0.4 * inch, letter[0], letter[1] - 0.4 * inch)
        canvas.restoreState()
        footer(canvas, doc_)

    doc.build(story, onFirstPage=first_page, onLaterPages=later)
    print(f"Wrote {OUT}")
    try:
        ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
        ARTIFACT.write_bytes(OUT.read_bytes())
        print(f"Wrote {ARTIFACT}")
    except OSError as exc:
        print(f"Artifact copy skipped: {exc}")


if __name__ == "__main__":
    build()
