#!/usr/bin/env python3
"""Generate VAL CoPilot Azure Foundry deployment guide (PDF + HTML + Markdown)."""

from __future__ import annotations

from pathlib import Path

from reportlab.lib.colors import HexColor, white
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    HRFlowable,
    ListFlowable,
    ListItem,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
    PageBreak,
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


MARKDOWN = """# VAL CoPilot — Azure AI Foundry Deployment Guide

Step-by-step procedure to provision the LangChain cognitive routing agent into
Microsoft Azure AI Foundry using `copilot_agent/deploy_to_foundry.py`.

**Audience:** Azure Cloud Architects / DevSecOps Engineers  
**SDKs:** `azure-ai-projects==1.0.0` · `azure-ai-agents` · `azure-identity`

---

## 1. Overview

This guide deploys VAL CoPilot as a **managed Azure AI Foundry Agent**. The
deployment script authenticates with Entra ID, wraps Fabric SQL and Azure AI
Search MCP tools in a Foundry **FunctionTool / ToolSet**, and creates the agent
using the existing multi-agent **SYSTEM_PROMPT** (compliance audits, red-flagging,
financial exposure projections, and renewal strategy sheets).

### What gets provisioned

- Managed agent named `val-copilot` (configurable)
- Model deployment referenced by `AZURE_OPENAI_DEPLOYMENT_NAME` or `AZURE_FOUNDRY_MODEL_DEPLOYMENT`
- ToolSet containing: `get_expiring_contracts`, `get_vendor_spend_summary`, `search_cloud_blob_contracts`
- Instructions = full `SYSTEM_PROMPT` from `copilot_agent/agent.py`

---

## 2. Prerequisites

### 2.1 Azure resources

1. An Azure subscription with permission to create / manage AI resources.
2. A **Microsoft Foundry project** (foundry-based, not hub-only) with Agents enabled.
3. A **model deployment** in that project (for example `gpt-4o`).
4. Microsoft Fabric SQL Gold layer reachable via `ActiveDirectoryDefault`.
5. Azure AI Search index with contract documents.

### 2.2 Local workstation

1. Python 3.10+ (3.12 recommended) and a virtual environment.
2. Azure CLI installed; identity able to use `DefaultAzureCredential`.
3. Git clone of the VALAgent repository.
4. Network path to Fabric, Azure AI Search, and the Foundry project endpoint.

### 2.3 Entra ID / RBAC

Assign the deploying identity (user or service principal) at least **Azure AI Developer**
(or equivalent) on the Foundry project, plus access to Fabric and Azure AI Search
data planes used by the wrapped tools.

---

## 3. Gather Foundry Connection Information

In the Azure AI Foundry portal, open your **Project Overview** page and copy the
**Project endpoint**. Preferred form:

```text
https://<ai-services-account>.services.ai.azure.com/api/projects/<project-name>
```

Alternatively, use a legacy semicolon-delimited connection string:

```text
endpoint=https://<account>.services.ai.azure.com/api/projects/<project>;subscriptionId=<guid>;resourceGroupName=<rg>;projectName=<project>
```

> Note: `azure-ai-projects` 2.x removed connection-string factories. This repo pins
> `azure-ai-projects==1.0.0` so `ToolSet` / `FunctionTool` remain available. The script
> parses `AZURE_FOUNDRY_CONNECTION_STRING` and initializes `AIProjectClient` from the endpoint.

---

## 4. Configure Root Environment (`.env`)

Copy `.env.example` to `.env` at the repository root (do **not** create per-folder env files).

| Variable | Required | Purpose |
| --- | --- | --- |
| `AZURE_FOUNDRY_CONNECTION_STRING` | Yes | Foundry project endpoint or legacy connection string |
| `AZURE_OPENAI_DEPLOYMENT_NAME` or `AZURE_FOUNDRY_MODEL_DEPLOYMENT` | Yes | Model deployment name used by the managed agent |
| `AZURE_FOUNDRY_AGENT_NAME` | No | Agent display name (default: `val-copilot`) |
| `FABRIC_SQL_SERVER` / `FABRIC_SQL_DATABASE` | Runtime | Fabric Gold SQL for expiring contracts & spend tools |
| `AZURE_SEARCH_ENDPOINT` / API key / index | Runtime | Azure AI Search for contract document tool |

Example fragment:

```bash
AZURE_FOUNDRY_CONNECTION_STRING=https://myacct.services.ai.azure.com/api/projects/val
AZURE_FOUNDRY_MODEL_DEPLOYMENT=gpt-4o
AZURE_FOUNDRY_AGENT_NAME=val-copilot
AZURE_OPENAI_DEPLOYMENT_NAME=gpt-4o
```

---

## 5. Authenticate with Azure (`DefaultAzureCredential`)

The script uses **DefaultAzureCredential** only (no API keys for Foundry control plane).

1. **Developer workstation:** `az login` (and `az account set --subscription <id>` if needed).
2. **Service principal:** export `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_CLIENT_SECRET`.
3. **Cloud / VM:** attach a managed identity with Foundry + data-plane RBAC.

```bash
az login
az account show --query id -o tsv
```

---

## 6. Install Python Dependencies

```bash
cd copilot_agent
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -r ../mcp_server/requirements.txt
```

Pinned packages: `azure-ai-projects==1.0.0`, `azure-ai-agents>=1.0.0,<2.0.0`,
`azure-identity>=1.19.0`. Do **not** upgrade to `azure-ai-projects` 2.x for this
script — `ToolSet` was removed.

---

## 7. Validate Wiring (Dry Run)

```bash
cd copilot_agent
python deploy_to_foundry.py --dry-run -v
```

Expected JSON highlights:

- `status: dry_run`
- tools list includes `get_expiring_contracts`, `get_vendor_spend_summary`, `search_cloud_blob_contracts`
- non-zero `instructions_chars` (full SYSTEM_PROMPT loaded)
- endpoint / subscription / project fields parsed from `AZURE_FOUNDRY_CONNECTION_STRING`

---

## 8. Deploy the Managed Agent

```bash
cd copilot_agent
python deploy_to_foundry.py -v
# optional name override:
python deploy_to_foundry.py --agent-name val-copilot-prod
```

### What the script does at runtime

1. Load credentials via `DefaultAzureCredential`.
2. Parse `AZURE_FOUNDRY_CONNECTION_STRING` and open `AIProjectClient`.
3. Import MCP tools from `mcp_server/server.py`.
4. Wrap tools with `FunctionTool(...)` and `ToolSet.add(...)`.
5. Call `project_client.agents.create_agent(...)` with model, name, `instructions=SYSTEM_PROMPT`, and toolset.
6. Print a JSON summary including `agent_id` on success.

---

## 9. Verify in Azure AI Foundry Portal

1. Open Azure AI Foundry → your project → **Agents**.
2. Confirm agent `val-copilot` (or custom name) exists.
3. Inspect Instructions — should contain Comparative Analysis and Contract Lifecycle Procedures.
4. Inspect Tools — three function tools for Fabric / Search operations.
5. Smoke-test prompts such as “Show expiring contracts” or “Red-flag compliance audit for CON-0003”.

---

## 10. Runtime & Architecture Notes

The Foundry-managed agent hosts the **cognitive instructions and tool definitions**.
Function tools execute in the process that handles tool calls (this deployment path
wraps the existing Python MCP implementations). Ensure the execution host can reach
Fabric SQL (ODBC Driver 18 + ActiveDirectoryDefault) and Azure AI Search.

### Cognitive procedures encoded in SYSTEM_PROMPT

- Comparative Analysis & Decision Framework → `## Recommendation`
- Red-Flag Compliance Audits → `## Red-Flag Compliance Audit`
- Dynamic Counter-Clause Drafting → `## Dynamic Counter-Clause Drafting`
- Financial Exposure Projections → `## Financial Exposure Projection`
- Proactive Renewal Strategy Sheets → `## Proactive Renewal Strategy Sheet`

---

## 11. Troubleshooting

| Symptom | Likely cause / fix |
| --- | --- |
| Missing `AZURE_FOUNDRY_CONNECTION_STRING` | Set variable in root `.env`; re-run from repo that loads `config.py` |
| Cannot import `ToolSet` / `FunctionTool` | Reinstall pinned `azure-ai-projects==1.0.0` and `azure-ai-agents<2` |
| `DefaultAzureCredential` failed | Run `az login` or configure SP / managed identity env vars |
| 403 / firewall to Azure OpenAI or Foundry | Allowlist egress IPs; confirm Agents enabled in project region |
| Tool returns empty / SQL errors | Validate Fabric + Search env vars; test MCP server locally first |
| Wrong model name | Match `AZURE_FOUNDRY_MODEL_DEPLOYMENT` to an existing project deployment |

---

## 12. Deployment Checklist (Quick Reference)

- [ ] Foundry project endpoint copied
- [ ] Model deployed in the project
- [ ] Root `.env` populated (Foundry + Fabric + Search)
- [ ] `az login` / managed identity ready
- [ ] `pip install -r copilot_agent/requirements.txt` (+ mcp_server deps)
- [ ] `python deploy_to_foundry.py --dry-run` succeeds
- [ ] `python deploy_to_foundry.py` returns `status=created` with `agent_id`
- [ ] Portal Agents view shows tools + SYSTEM_PROMPT procedures
- [ ] Smoke-test expiring contracts / compliance audit prompts

---

*Keep secrets out of Git; commit only `.env.example`. Script path: `copilot_agent/deploy_to_foundry.py`.*
"""


def _build_pdf(path: Path) -> None:
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        name="CoverTitle", fontName="Helvetica-Bold", fontSize=22,
        textColor=NAVY, alignment=TA_CENTER, spaceAfter=10, leading=26,
    ))
    styles.add(ParagraphStyle(
        name="CoverSub", fontName="Helvetica", fontSize=12,
        textColor=SLATE, alignment=TA_CENTER, spaceAfter=6, leading=16,
    ))
    styles.add(ParagraphStyle(
        name="H1Custom", fontName="Helvetica-Bold", fontSize=14,
        textColor=NAVY, spaceBefore=16, spaceAfter=8, leading=18,
    ))
    styles.add(ParagraphStyle(
        name="H2Custom", fontName="Helvetica-Bold", fontSize=11.5,
        textColor=TEAL, spaceBefore=12, spaceAfter=6, leading=15,
    ))
    styles.add(ParagraphStyle(
        name="BodyCustom", fontName="Helvetica", fontSize=10,
        textColor=SLATE, spaceAfter=6, leading=14,
    ))
    styles.add(ParagraphStyle(
        name="BulletBody", fontName="Helvetica", fontSize=10,
        textColor=SLATE, leading=13,
    ))
    styles.add(ParagraphStyle(
        name="CodeBlock", fontName="Courier", fontSize=8.5,
        textColor=NAVY, backColor=LIGHT, leading=11,
        leftIndent=6, rightIndent=6, spaceBefore=4, spaceAfter=8,
    ))
    styles.add(ParagraphStyle(
        name="Note", fontName="Helvetica-Oblique", fontSize=9,
        textColor=SLATE, leftIndent=8, spaceBefore=4, spaceAfter=8, leading=12,
    ))
    styles.add(ParagraphStyle(
        name="Footer", fontName="Helvetica", fontSize=8,
        textColor=HexColor("#64748B"), alignment=TA_CENTER,
    ))
    styles.add(ParagraphStyle(
        name="TableCell", fontName="Helvetica", fontSize=8.5,
        textColor=SLATE, leading=11,
    ))
    styles.add(ParagraphStyle(
        name="TableHeader", fontName="Helvetica-Bold", fontSize=8.5,
        textColor=white, leading=11,
    ))

    def numbered(items: list[str]) -> ListFlowable:
        return ListFlowable(
            [
                ListItem(Paragraph(i, styles["BulletBody"]), leftIndent=12, bulletColor=TEAL)
                for i in items
            ],
            bulletType="1",
            start="1",
            leftIndent=18,
            spaceBefore=2,
            spaceAfter=8,
        )

    def bullets(items: list[str]) -> ListFlowable:
        return ListFlowable(
            [
                ListItem(Paragraph(i, styles["BulletBody"]), leftIndent=12, bulletColor=TEAL)
                for i in items
            ],
            bulletType="bullet",
            leftIndent=18,
            spaceBefore=2,
            spaceAfter=8,
        )

    def code(text: str) -> Paragraph:
        safe = (
            text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace("\n", "<br/>")
        )
        return Paragraph(safe, styles["CodeBlock"])

    def hr() -> HRFlowable:
        return HRFlowable(width="100%", thickness=0.8, color=BORDER, spaceBefore=4, spaceAfter=8)

    story = []
    story.append(Spacer(1, 1.4 * inch))
    story.append(Paragraph("VAL CoPilot", styles["CoverTitle"]))
    story.append(Paragraph("Azure AI Foundry Deployment Guide", styles["CoverTitle"]))
    story.append(Spacer(1, 0.25 * inch))
    story.append(hr())
    story.append(Paragraph(
        "Step-by-step procedure to provision the LangChain cognitive routing agent "
        "into Microsoft Azure AI Foundry using <b>copilot_agent/deploy_to_foundry.py</b>.",
        styles["CoverSub"],
    ))
    story.append(Spacer(1, 0.2 * inch))
    story.append(Paragraph("Audience: Azure Cloud Architects / DevSecOps Engineers", styles["CoverSub"]))
    story.append(Paragraph("Script: copilot_agent/deploy_to_foundry.py", styles["CoverSub"]))
    story.append(Paragraph(
        "SDKs: azure-ai-projects 1.0.0 · azure-ai-agents · azure-identity",
        styles["CoverSub"],
    ))
    story.append(PageBreak())

    story.append(Paragraph("1. Overview", styles["H1Custom"]))
    story.append(hr())
    story.append(Paragraph(
        "This guide deploys VAL CoPilot as a <b>managed Azure AI Foundry Agent</b>. "
        "The deployment script authenticates with Entra ID, wraps Fabric SQL and Azure AI Search "
        "MCP tools in a Foundry <b>FunctionTool / ToolSet</b>, and creates the agent using the "
        "existing multi-agent <b>SYSTEM_PROMPT</b> (compliance audits, red-flagging, financial "
        "exposure projections, and renewal strategy sheets).",
        styles["BodyCustom"],
    ))
    story.append(Paragraph("What gets provisioned", styles["H2Custom"]))
    story.append(bullets([
        "<b>Managed agent</b> named <font face='Courier'>val-copilot</font> (configurable)",
        "<b>Model deployment</b> referenced by AZURE_OPENAI_DEPLOYMENT_NAME or AZURE_FOUNDRY_MODEL_DEPLOYMENT",
        "<b>ToolSet</b> containing: get_expiring_contracts, get_vendor_spend_summary, search_cloud_blob_contracts",
        "<b>Instructions</b> = full SYSTEM_PROMPT from copilot_agent/agent.py",
    ]))

    story.append(Paragraph("2. Prerequisites", styles["H1Custom"]))
    story.append(hr())
    story.append(Paragraph("2.1 Azure resources", styles["H2Custom"]))
    story.append(numbered([
        "An Azure subscription with permission to create / manage AI resources.",
        "A <b>Microsoft Foundry project</b> (foundry-based, not hub-only) with Agents enabled.",
        "A <b>model deployment</b> in that project (for example gpt-4o).",
        "Microsoft Fabric SQL Gold layer reachable via ActiveDirectoryDefault (for tool runtime).",
        "Azure AI Search index with contract documents (for semantic search tool).",
    ]))
    story.append(Paragraph("2.2 Local workstation", styles["H2Custom"]))
    story.append(numbered([
        "Python 3.10+ (3.12 recommended) and a virtual environment.",
        "Azure CLI installed; identity able to use <font face='Courier'>DefaultAzureCredential</font>.",
        "Git clone of the VALAgent repository.",
        "Network path to Fabric, Azure AI Search, and the Foundry project endpoint.",
    ]))
    story.append(Paragraph("2.3 Entra ID / RBAC", styles["H2Custom"]))
    story.append(Paragraph(
        "Assign the deploying identity (user or service principal) at least "
        "<b>Azure AI Developer</b> (or equivalent) on the Foundry project, plus access to "
        "Fabric and Azure AI Search data planes used by the wrapped tools.",
        styles["BodyCustom"],
    ))

    story.append(Paragraph("3. Gather Foundry Connection Information", styles["H1Custom"]))
    story.append(hr())
    story.append(Paragraph(
        "In the Azure AI Foundry portal, open your <b>Project Overview</b> page and copy the "
        "<b>Project endpoint</b>. Preferred form:",
        styles["BodyCustom"],
    ))
    story.append(code(
        "https://&lt;ai-services-account&gt;.services.ai.azure.com/api/projects/&lt;project-name&gt;"
    ))
    story.append(Paragraph(
        "Alternatively, use a legacy semicolon-delimited connection string:",
        styles["BodyCustom"],
    ))
    story.append(code(
        "endpoint=https://&lt;account&gt;.services.ai.azure.com/api/projects/&lt;project&gt;;"
        "subscriptionId=&lt;guid&gt;;resourceGroupName=&lt;rg&gt;;projectName=&lt;project&gt;"
    ))
    story.append(Paragraph(
        "Note: azure-ai-projects 2.x removed connection-string factories. This repo pins "
        "<b>azure-ai-projects==1.0.0</b> so ToolSet / FunctionTool remain available; the script "
        "parses AZURE_FOUNDRY_CONNECTION_STRING and initializes AIProjectClient from the endpoint.",
        styles["Note"],
    ))

    story.append(Paragraph("4. Configure Root Environment (.env)", styles["H1Custom"]))
    story.append(hr())
    story.append(Paragraph(
        "Copy <font face='Courier'>.env.example</font> to <font face='Courier'>.env</font> at the "
        "repository root (do not create per-folder env files). Set at minimum:",
        styles["BodyCustom"],
    ))
    header = [
        Paragraph("Variable", styles["TableHeader"]),
        Paragraph("Required", styles["TableHeader"]),
        Paragraph("Purpose", styles["TableHeader"]),
    ]
    rows = [
        header,
        [
            Paragraph("AZURE_FOUNDRY_CONNECTION_STRING", styles["TableCell"]),
            Paragraph("Yes", styles["TableCell"]),
            Paragraph("Foundry project endpoint or legacy connection string", styles["TableCell"]),
        ],
        [
            Paragraph(
                "AZURE_OPENAI_DEPLOYMENT_NAME<br/>or AZURE_FOUNDRY_MODEL_DEPLOYMENT",
                styles["TableCell"],
            ),
            Paragraph("Yes", styles["TableCell"]),
            Paragraph("Model deployment name used by the managed agent", styles["TableCell"]),
        ],
        [
            Paragraph("AZURE_FOUNDRY_AGENT_NAME", styles["TableCell"]),
            Paragraph("No", styles["TableCell"]),
            Paragraph("Agent display name (default: val-copilot)", styles["TableCell"]),
        ],
        [
            Paragraph("FABRIC_SQL_SERVER / FABRIC_SQL_DATABASE", styles["TableCell"]),
            Paragraph("Runtime", styles["TableCell"]),
            Paragraph(
                "Fabric Gold SQL for expiring contracts &amp; spend tools",
                styles["TableCell"],
            ),
        ],
        [
            Paragraph("AZURE_SEARCH_ENDPOINT / API_KEY / INDEX", styles["TableCell"]),
            Paragraph("Runtime", styles["TableCell"]),
            Paragraph("Azure AI Search for contract document tool", styles["TableCell"]),
        ],
    ]
    table = Table(rows, colWidths=[2.4 * inch, 0.75 * inch, 3.5 * inch])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("BACKGROUND", (0, 1), (-1, -1), LIGHT),
        ("TEXTCOLOR", (0, 0), (-1, 0), white),
        ("GRID", (0, 0), (-1, -1), 0.4, BORDER),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(table)
    story.append(Spacer(1, 0.12 * inch))
    story.append(code(
        "# Example fragment for root .env\n"
        "AZURE_FOUNDRY_CONNECTION_STRING=https://myacct.services.ai.azure.com/api/projects/val\n"
        "AZURE_FOUNDRY_MODEL_DEPLOYMENT=gpt-4o\n"
        "AZURE_FOUNDRY_AGENT_NAME=val-copilot\n"
        "AZURE_OPENAI_DEPLOYMENT_NAME=gpt-4o"
    ))

    story.append(Paragraph("5. Authenticate with Azure (DefaultAzureCredential)", styles["H1Custom"]))
    story.append(hr())
    story.append(Paragraph(
        "The script uses <b>DefaultAzureCredential</b> only (no API keys for Foundry control plane). "
        "Choose one interactive or automated path:",
        styles["BodyCustom"],
    ))
    story.append(numbered([
        "<b>Developer workstation:</b> run <font face='Courier'>az login</font>.",
        "<b>Service principal:</b> export AZURE_CLIENT_ID, AZURE_TENANT_ID, AZURE_CLIENT_SECRET.",
        "<b>Cloud / VM:</b> attach a managed identity with Foundry + data-plane RBAC.",
    ]))
    story.append(code("az login\naz account show --query id -o tsv"))

    story.append(Paragraph("6. Install Python Dependencies", styles["H1Custom"]))
    story.append(hr())
    story.append(code(
        "cd copilot_agent\n"
        "python3 -m venv .venv\n"
        "source .venv/bin/activate\n"
        "pip install -r requirements.txt\n"
        "pip install -r ../mcp_server/requirements.txt"
    ))
    story.append(Paragraph(
        "Pinned packages: azure-ai-projects==1.0.0, azure-ai-agents&gt;=1.0.0,&lt;2.0.0, "
        "azure-identity&gt;=1.19.0. Do not upgrade to azure-ai-projects 2.x for this script.",
        styles["Note"],
    ))

    story.append(Paragraph("7. Validate Wiring (Dry Run)", styles["H1Custom"]))
    story.append(hr())
    story.append(code("cd copilot_agent\npython deploy_to_foundry.py --dry-run -v"))
    story.append(Paragraph("Expected JSON highlights", styles["H2Custom"]))
    story.append(bullets([
        "<font face='Courier'>status: dry_run</font>",
        "tools list includes get_expiring_contracts, get_vendor_spend_summary, search_cloud_blob_contracts",
        "non-zero instructions_chars (full SYSTEM_PROMPT loaded)",
        "endpoint / subscription / project fields parsed from AZURE_FOUNDRY_CONNECTION_STRING",
    ]))

    story.append(Paragraph("8. Deploy the Managed Agent", styles["H1Custom"]))
    story.append(hr())
    story.append(code(
        "cd copilot_agent\n"
        "python deploy_to_foundry.py -v\n"
        "python deploy_to_foundry.py --agent-name val-copilot-prod"
    ))
    story.append(Paragraph("What the script does at runtime", styles["H2Custom"]))
    story.append(numbered([
        "Load credentials via <font face='Courier'>DefaultAzureCredential</font>.",
        "Parse <font face='Courier'>AZURE_FOUNDRY_CONNECTION_STRING</font> and open AIProjectClient.",
        "Import MCP tools from <font face='Courier'>mcp_server/server.py</font>.",
        "Wrap tools with FunctionTool and ToolSet.add.",
        "Call create_agent with model, name, instructions=SYSTEM_PROMPT, and toolset.",
        "Print a JSON summary including agent_id on success.",
    ]))

    story.append(Paragraph("9. Verify in Azure AI Foundry Portal", styles["H1Custom"]))
    story.append(hr())
    story.append(numbered([
        "Open Azure AI Foundry → your project → <b>Agents</b>.",
        "Confirm agent <font face='Courier'>val-copilot</font> exists.",
        "Inspect Instructions for Comparative Analysis and Contract Lifecycle Procedures.",
        "Inspect Tools — three function tools for Fabric / Search operations.",
        "Smoke-test: “Show expiring contracts” / “Red-flag compliance audit for CON-0003”.",
    ]))

    story.append(Paragraph("10. Runtime &amp; Architecture Notes", styles["H1Custom"]))
    story.append(hr())
    story.append(Paragraph(
        "The Foundry-managed agent hosts the <b>cognitive instructions and tool definitions</b>. "
        "Ensure the execution host can reach Fabric SQL (ODBC Driver 18 + ActiveDirectoryDefault) "
        "and Azure AI Search.",
        styles["BodyCustom"],
    ))
    story.append(Paragraph("Cognitive procedures encoded in SYSTEM_PROMPT", styles["H2Custom"]))
    story.append(bullets([
        "Comparative Analysis &amp; Decision Framework → ## Recommendation",
        "Red-Flag Compliance Audits → ## Red-Flag Compliance Audit",
        "Dynamic Counter-Clause Drafting → ## Dynamic Counter-Clause Drafting",
        "Financial Exposure Projections → ## Financial Exposure Projection",
        "Proactive Renewal Strategy Sheets → ## Proactive Renewal Strategy Sheet",
    ]))

    story.append(Paragraph("11. Troubleshooting", styles["H1Custom"]))
    story.append(hr())
    t2_header = [
        Paragraph("Symptom", styles["TableHeader"]),
        Paragraph("Likely cause / fix", styles["TableHeader"]),
    ]
    t2_rows = [
        t2_header,
        [
            Paragraph("Missing AZURE_FOUNDRY_CONNECTION_STRING", styles["TableCell"]),
            Paragraph("Set variable in root .env; re-run from repo that loads config.py", styles["TableCell"]),
        ],
        [
            Paragraph("Cannot import ToolSet / FunctionTool", styles["TableCell"]),
            Paragraph("Reinstall pinned azure-ai-projects==1.0.0 and azure-ai-agents&lt;2", styles["TableCell"]),
        ],
        [
            Paragraph("DefaultAzureCredential failed", styles["TableCell"]),
            Paragraph("Run az login or configure SP / managed identity env vars", styles["TableCell"]),
        ],
        [
            Paragraph("403 / firewall to Azure OpenAI or Foundry", styles["TableCell"]),
            Paragraph("Allowlist egress IPs; confirm Agents enabled in project region", styles["TableCell"]),
        ],
        [
            Paragraph("Tool returns empty / SQL errors", styles["TableCell"]),
            Paragraph("Validate Fabric + Search env vars; test MCP server locally first", styles["TableCell"]),
        ],
        [
            Paragraph("Wrong model name", styles["TableCell"]),
            Paragraph("Match AZURE_FOUNDRY_MODEL_DEPLOYMENT to an existing project deployment", styles["TableCell"]),
        ],
    ]
    t2 = Table(t2_rows, colWidths=[2.3 * inch, 4.35 * inch])
    t2.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("BACKGROUND", (0, 1), (-1, -1), LIGHT),
        ("GRID", (0, 0), (-1, -1), 0.4, BORDER),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(t2)

    story.append(Paragraph("12. Deployment Checklist (Quick Reference)", styles["H1Custom"]))
    story.append(hr())
    story.append(bullets([
        "Foundry project endpoint copied",
        "Model deployed in the project",
        "Root .env populated (Foundry + Fabric + Search)",
        "az login / managed identity ready",
        "pip install -r copilot_agent/requirements.txt (+ mcp_server deps)",
        "python deploy_to_foundry.py --dry-run succeeds",
        "python deploy_to_foundry.py returns status=created with agent_id",
        "Portal Agents view shows tools + SYSTEM_PROMPT procedures",
        "Smoke-test expiring contracts / compliance audit prompts",
    ]))
    story.append(Spacer(1, 0.25 * inch))
    story.append(hr())
    story.append(Paragraph(
        "Document generated for VALAgent · Script path: copilot_agent/deploy_to_foundry.py · "
        "Keep secrets out of Git; commit only .env.example.",
        styles["Footer"],
    ))

    def add_page_number(canvas, doc) -> None:
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(HexColor("#64748B"))
        canvas.drawCentredString(
            letter[0] / 2,
            0.5 * inch,
            f"VAL CoPilot · Azure AI Foundry Deployment · Page {doc.page}",
        )
        canvas.restoreState()

    path.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(path),
        pagesize=letter,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
        topMargin=0.7 * inch,
        bottomMargin=0.7 * inch,
        title="VAL CoPilot Azure AI Foundry Deployment Guide",
        author="VAL CoPilot",
    )
    doc.build(story, onFirstPage=add_page_number, onLaterPages=add_page_number)


def _build_html(md_text: str, path: Path) -> None:
    # Lightweight HTML wrapper so the guide opens in any browser without PDF tooling.
    body = (
        md_text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
    # Very small markdown-ish formatting for readability.
    import html as html_mod
    import re

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
                    "<tr>"
                    + "".join(f"<th>{html_mod.escape(c)}</th>" for c in cells)
                    + "</tr>"
                )
            else:
                lines_out.append(
                    "<tr>"
                    + "".join(f"<td>{html_mod.escape(c)}</td>" for c in cells)
                    + "</tr>"
                )
            continue
        close_table()
        if not line.strip():
            close_lists()
            continue
        if line.startswith("# "):
            close_lists()
            lines_out.append(f"<h1>{html_mod.escape(line[2:])}</h1>")
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
        if re.match(r"^[-*] \[ ste]", line):
            if not in_ul:
                close_lists()
                lines_out.append("<ul>")
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
        # inline code
        text = html_mod.escape(line)
        text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
        text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
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
    :root {{ color-scheme: light; }}
    body {{ font-family: Georgia, "Times New Roman", serif; max-width: 820px;
           margin: 2rem auto; padding: 0 1.25rem 3rem; color: #1e293b;
           background: linear-gradient(180deg, #f8fafc 0%, #eef6f6 100%); }}
    h1,h2,h3 {{ font-family: "Segoe UI", Helvetica, Arial, sans-serif; color: #0b1f33; }}
    h1 {{ border-bottom: 2px solid #0e6b6b; padding-bottom: .35rem; }}
    h2 {{ color: #0e6b6b; margin-top: 1.8rem; }}
    code, pre {{ font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
                 background: #f1f5f9; }}
    pre {{ padding: .9rem 1rem; overflow-x: auto; border-radius: 6px;
          border: 1px solid #cbd5e1; }}
    code {{ padding: .1rem .3rem; border-radius: 3px; }}
    table {{ border-collapse: collapse; width: 100%; margin: 1rem 0; background: #fff; }}
    th, td {{ border: 1px solid #cbd5e1; padding: .55rem .7rem; text-align: left;
              vertical-align: top; font-size: .95rem; }}
    th {{ background: #0b1f33; color: #fff; }}
    tr:nth-child(even) td {{ background: #f8fafc; }}
    blockquote {{ border-left: 4px solid #0e6b6b; margin: 1rem 0; padding: .2rem 1rem;
                  background: #f0fdfa; color: #334155; }}
    hr {{ border: none; border-top: 1px solid #cbd5e1; margin: 1.5rem 0; }}
    .download {{ font-family: "Segoe UI", Helvetica, Arial, sans-serif;
                 background: #0e6b6b; color: #fff !important; text-decoration: none;
                 padding: .55rem .9rem; border-radius: 6px; display: inline-block;
                 margin: .4rem .4rem .4rem 0; }}
    .download.secondary {{ background: #0b1f33; }}
  </style>
</head>
<body>
  <p>
    <a class="download" href="VAL_CoPilot_Azure_Foundry_Deployment_Guide.pdf">Download PDF</a>
    <a class="download secondary" href="VAL_CoPilot_Azure_Foundry_Deployment_Guide.md">View Markdown</a>
  </p>
  {"".join(lines_out)}
</body>
</html>
"""
    # silence unused
    _ = body
    path.write_text(html, encoding="utf-8")


def main() -> None:
    MD_PATH.write_text(MARKDOWN, encoding="utf-8")
    _build_html(MARKDOWN, HTML_PATH)
    _build_pdf(PDF_PATH)
    ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
    ARTIFACT.write_bytes(PDF_PATH.read_bytes())
    print(f"Wrote {MD_PATH} ({MD_PATH.stat().st_size} bytes)")
    print(f"Wrote {HTML_PATH} ({HTML_PATH.stat().st_size} bytes)")
    print(f"Wrote {PDF_PATH} ({PDF_PATH.stat().st_size} bytes)")
    print(f"Wrote {ARTIFACT} ({ARTIFACT.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
