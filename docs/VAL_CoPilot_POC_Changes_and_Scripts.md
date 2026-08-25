# VAL CoPilot POC — Changes & Python Scripts Reference

**Project:** Synthetic Contract Intelligence Tool-Layer POC (`booshank/VALAgent`)  
**Scope:** End-to-end Streamlit → Flask → LangChain/offline router → FastMCP → LinkSquares fixtures / Fabric SQL / Azure AI Search  
**Audience:** Engineers continuing the POC, demos, and handoffs  

This document consolidates **what was built**, **behavior rules that must be preserved**, and a **catalog of every meaningful Python script** in the repo.

---

## 1. Architecture overview

```
val-copilot-workspace/
├── .env / .env.example     # single shared secrets file (root only)
├── mcp_server/             # ROLE 1 — Data Retrieval Agent (FastMCP tools)
├── copilot_agent/          # ROLE 2 — Cognitive Routing Agent (Flask + LangChain)
├── test_ui/                # ROLE 3 — Validation Agent (Streamlit)
├── memory/                 # Shared SQLite persona / search memory
└── docs/                   # Architecture generators + guides
```

| Layer | Path | Responsibility |
| --- | --- | --- |
| Data Retrieval | `mcp_server/` | FastMCP tools over Fabric SQL (ODBC 18 + `ActiveDirectoryDefault`) and Azure AI Search |
| Cognitive Routing | `copilot_agent/` | LangChain agent + offline router, dual stdio MCP clients, Flask `/api/messages` |
| Validation | `test_ui/` | Streamlit harness that mocks Bot Framework activities and posts only to the routing agent |
| Persona memory | `memory/` | SQLite store for personas, conversations, messages, and saved searches |

**Runtime flow**

```
Streamlit (test_ui/app.py)
    → POST /api/messages (copilot_agent/app.py)
        → agent.run_turn()  [Azure OpenAI or offline_router]
            → MCP tools (mcp_server/server.py via mcp_clients.py)
                → Fabric SQL / Azure AI Search / LinkSquares offline fixtures
            → optional persona memory (memory/store.py)
        → Bot Framework-style reply JSON
```

---

## 2. Changes delivered in this POC (feature history)

### 2.1 Persona memory — save & retrieve previous searches

- Shared SQLite store at `data/persona_memory.sqlite` (override with `VAL_MEMORY_DB`).
- **Auto-save** of search-like user queries per persona.
- Streamlit sidebar **Saved searches**: filter, pin (**Save last search**), Re-run, Open chat, Delete, Retrieve in chat.
- Streamlit sidebar **Previous conversations**: open, **Delete** (per chat), **Delete current chat**, **Delete all chats**.
- Chat recall phrases: “Show my previous searches”, “Retrieve my saved searches”, “previous searches about {topic}”.
- HTTP APIs on the cognitive agent:
  - `GET /api/memory/searches?persona_id=…&q=…&saved_only=true`
  - `POST /api/memory/searches` `{persona_id, query, conversation_id?, result_preview?}`
  - `DELETE /api/memory/searches/<id>?persona_id=…`
  - `GET /api/memory/recall?persona_id=…&q=…`
  - `GET /api/memory/conversations?persona_id=…`
  - `DELETE /api/memory/conversations/<id>?persona_id=…`
  - `DELETE /api/memory/conversations?persona_id=…` (delete all for persona)
- Streamlit sets `channelData.clientPersistsMemory=true` so Flask does not double-write; Flask persists for other clients.
- Memory-recall intents are forced through the deterministic offline persona store.

### 2.2 Compare hard-stop when contracts / suppliers are missing

- `compare_contracts` supports **any contract IDs** and **N-way** compares (not only first/second catalog rows).
- Supplier expansion: `supplier_names`, `expand_supplier_matches`, `max_contracts`.
- If any requested supplier or contract ID cannot be resolved:
  - **Do not** default to `CON-0001 vs CON-0002`
  - **Do not** emit a comparative table
  - **Do not** emit a recommendation
  - Return **exactly and only**:

    > The contract information requested for the comparison is not available at the moment

- Mixed known/unknown vendors must not collapse into single-supplier catalog expansion.
- Legacy hallucination text is sanitized away:

  > No two resolvable compare sides detected; defaulting comparison to CON-0001 vs CON-0002.

- Unknown vendor **search** / unknown contract **profile** return `error: contract_not_present` with “No such contract is available…”.
- Compare intents (and memory-recall intents) use the offline router for deterministic behavior.

### 2.3 LinkSquares fixtures replace old test contracts

- Active fixtures:
  - `mcp_server/LinSquare_Contracts_100_Updated_30bb.json`
  - `mcp_server/agreement_9a06.json`
- Built into Gold-shaped offline tables by `linksquares_fixtures.py`.
- Removed older `Test_contracts_0397` / `test_fixtures` POC files.

### 2.4 Tool-layer hardening

- Overlap detection (`find_overlaps`) and risk explanations (`explain_contract_risk`).
- `ContractRepository` abstraction for swappable data sources.
- Invoice / actual-spend intents hard out-of-scope (no tool calls).
- Contract lifecycle cognitive procedures in the system prompt (red-flag audit, counter-clause, exposure, renewal).
- **Renewal Window List** procedure via `get_contract_renewals` — list contracts coming up for renewal in a particular window (`days_ahead` or explicit ISO `window_start`/`window_end`); uses RenewalDate with ExpirationDate fallback.
- Comparative analysis decision framework when a compare **succeeds**.

### 2.5 Offline staging & Azure OpenAI bypass

- `USE_OFFLINE_MOCKS=true` installs a LinkSquares interceptor (patches `pyodbc` / `pandas.read_sql` / Azure Search client) while keeping tool bodies production-shaped.
- `AZURE_OPENAI_FORCE_OFFLINE=true` or Azure OpenAI **403 VNet/firewall** → offline cognitive router (`offline_router.py`) still calling the same MCP tools.

### 2.6 Docs

- Architecture / process-flow PDF + PPTX generators.
- POC changes and Python scripts reference.

---

## 3. MCP tools (data surface)

Registered in `mcp_server/server.py`:

| Tool | Purpose |
| --- | --- |
| `get_expiring_contracts` | Contracts approaching expiration (Fabric Gold) |
| `list_renewals_in_window` | Renewal Window List (diagram name) — renewals in a `days_ahead` or `window_start`/`window_end` window |
| `get_contract_renewals` | Alias for `list_renewals_in_window` (backward compatible) |
| `identify_missing_fields` | Missing Data Checker (diagram name) — incomplete commercial field scan |
| `check_missing_contract_fields` | Alias for `identify_missing_fields` (backward compatible) |
| `get_vendor_spend_summary` | Contract-value rollups by supplier (not invoice spend) |
| `compare_contracts` | Pairwise / N-way field comparison; hard-stop if unresolved |
| `check_missing_contract_fields` | Incomplete commercial field scan |
| `search_cloud_blob_contracts` | Unstructured / clause search via Azure AI Search |
| `search_contracts` | Structured Gold metadata search |
| `get_contract_profile` | Full normalized profile for one ContractID |
| `find_overlaps` | Same-vendor effective→expiration overlaps |
| `explain_contract_risk` | known_facts vs computed_risks |
| `fabric_health_check` | Connectivity / offline health probe |

---

## 4. Python scripts catalog

Legend: **R** = runtime · **G** = generator · **T** = test · **C** = config/support · **F** = fixture helper

### 4.1 `mcp_server/` — Data Retrieval Agent

| Script | Kind | Description |
| --- | --- | --- |
| `mcp_server/server.py` | **R** | FastMCP stdio server. Installs offline interceptor when `USE_OFFLINE_MOCKS` is set; registers all MCP tools. Entry: `mcp.run()`. |
| `mcp_server/fabric_sql.py` | **R** | Fabric SQL via ODBC Driver 18 + `ActiveDirectoryDefault`. `get_connection()`, `execute_query()`. |
| `mcp_server/azure_search.py` | **R** | Azure AI Search hybrid semantic client. `hybrid_semantic_search()`. |
| `mcp_server/contract_analytics.py` | **R** | Criteria building, resolve/filter, pairwise & N-way compare, missing-field checks, row normalization. |
| `mcp_server/contract_repository.py` | **R** | Swappable data boundary (`ContractRepository`, `FabricContractRepository`, getters/setters). |
| `mcp_server/contract_risk.py` | **R** | Overlap detection and risk explanation helpers. |
| `mcp_server/linksquares_fixtures.py` | **F/R** | Projects LinkSquares JSON into Gold-shaped offline tables/documents for mocks. |
| `mcp_server/config.py` | **C** | Loads root `.env` only (`require`, `get`). |
| `mcp_server/test_offline_mocks.py` | **T** | Offline interceptor roundtrip; asserts tool bodies have no mock branches; fixture files present. |
| `mcp_server/__init__.py` | **C** | Package marker. |

**Fixture data (non-Python):**

- `mcp_server/LinSquare_Contracts_100_Updated_30bb.json`
- `mcp_server/agreement_9a06.json`

### 4.2 `copilot_agent/` — Cognitive Routing Agent

| Script | Kind | Description |
| --- | --- | --- |
| `copilot_agent/app.py` | **R** | Flask Bot Framework ingress (`POST /api/messages`), health, and persona memory REST APIs. Dedicated asyncio loop for agent turns. |
| `copilot_agent/agent.py` | **R** | LangChain `create_openai_tools_agent` + `AgentExecutor`, system prompt routing domains, offline/403 fallback. Forces offline for compare + memory-recall intents. `run_turn()`. |
| `copilot_agent/offline_router.py` | **R** | Deterministic intent → tool router used when Azure OpenAI is bypassed/firewalled. Compare hard-stop, summarizers, lifecycle sections, persona memory recall. `run_offline_turn()`. |
| `copilot_agent/mcp_clients.py` | **R** | Dual stdio MCP bridge: local `../mcp_server/server.py` + optional `uvx mcp-server-pgvector`. |
| `copilot_agent/config.py` | **C** | Root `.env` loader. |
| `copilot_agent/test_poc_guards.py` | **T** | POC guards: invoice OOS, N-way compare, missing-contract hard-stop, overlaps/risk, repository, persona recall. |
| `copilot_agent/__init__.py` | **C** | Package marker. |

### 4.3 `test_ui/` — Validation Agent

| Script | Kind | Description |
| --- | --- | --- |
| `test_ui/app.py` | **R** | Streamlit chat UI. Builds Bot Framework-style activities, posts to Flask, persists persona conversations/searches via `memory/`. Sidebar for Saved searches and delete prior conversations. |
| `test_ui/mock_messages_server.py` | **R** (local) | Echo `/api/messages` backend for UI testing without the real agent. Port `MOCK_MESSAGES_PORT` (default 3978). |
| `test_ui/config.py` | **C** | Root `.env` loader. |
| `test_ui/test_bot_schema.py` | **T** | Bot Framework mock activity schema smoke test. |
| `test_ui/test_streamlit_ui.py` | **T** | Spawns mock + Streamlit AppTest; chat roundtrip / wiring. |
| `test_ui/__init__.py` | **C** | Package marker. |

### 4.4 `memory/` — Shared persona store

| Script | Kind | Description |
| --- | --- | --- |
| `memory/store.py` | **R** | SQLite personas / conversations / messages / searches. Auto-save search-like queries; explicit `save_search`, `list_searches`, `recall`, `delete_search`. Default DB: `data/persona_memory.sqlite`. |
| `memory/test_store.py` | **T** | Unit tests for store CRUD, pin/filter/delete, search-like detection. |
| `memory/__init__.py` | **C** | Re-exports store API. |

### 4.5 `docs/` — Documentation generators

| Script | Kind | Description |
| --- | --- | --- |
| `docs/generate_architecture_diagram.py` | **G** | ReportLab architecture / process-flow PDF → `VAL_CoPilot_Architecture_and_Process_Flow.pdf`. |
| `docs/generate_architecture_pptx.py` | **G** | PowerPoint architecture deck → `.pptx`. |

**Related docs (non-Python):**

- `docs/demo_script.md` — offline demo prompts and expected tools/outputs  
- `docs/VAL_CoPilot_POC_Changes_and_Scripts.md` — change log / scripts catalog  
- Generated artifacts: architecture PDF/PPTX  
- `docs/VAL_CoPilot_Python_Procedures_Catalog.xlsx` / `.csv` — procedure inventory

---

## 5. Key environment variables

| Variable | Role |
| --- | --- |
| `USE_OFFLINE_MOCKS` | LinkSquares fixture interceptor in `mcp_server`; also forces offline cognitive router |
| `AZURE_OPENAI_FORCE_OFFLINE` | Skip Azure OpenAI; use offline router |
| `AZURE_OPENAI_*` | LangChain AzureChatOpenAI (endpoint, key, deployment, API version) |
| `FABRIC_SQL_*` | Fabric Gold warehouse (auth always AD Default in code) |
| `AZURE_SEARCH_*` | Azure AI Search endpoint / key / index / semantic config |
| `PGVECTOR_DATABASE_URL` / `PGVECTOR_COLLECTION` | Optional pgvector MCP via `uvx` |
| `COPILOT_HOST` / `COPILOT_PORT` | Flask listen address (default `0.0.0.0:3978`) |
| `COPILOT_MESSAGES_URL` | Streamlit → agent URL |
| `VAL_MEMORY_DB` | Override SQLite path for persona memory |
| `MOCK_MESSAGES_PORT` | Mock messages server port (`test_ui`) |

Copy from `.env.example` to root `.env` only — do not duplicate under subfolders.

---

## 6. How to run

```bash
# Cognitive Routing Agent (spawns MCP stdio server)
cd copilot_agent && .venv/bin/python app.py
# → http://0.0.0.0:3978  POST /api/messages

# Validation UI
cd test_ui && .venv/bin/streamlit run app.py
# → http://localhost:8501
```

Offline staging:

```bash
# in root .env
USE_OFFLINE_MOCKS=true
AZURE_OPENAI_FORCE_OFFLINE=true
```

UI-only mock (no real agent):

```bash
cd test_ui && .venv/bin/python mock_messages_server.py
cd test_ui && .venv/bin/streamlit run app.py
```

---

## 7. How to test

```bash
# Offline MCP / fixture interceptor
cd mcp_server && USE_OFFLINE_MOCKS=true .venv/bin/python test_offline_mocks.py

# POC guards (compare hard-stop, N-way, overlaps, risk, memory recall, …)
cd copilot_agent && .venv/bin/python test_poc_guards.py

# Persona memory unit tests
cd memory && python3 test_store.py

# Streamlit / Bot schema
cd test_ui && .venv/bin/python test_bot_schema.py
cd test_ui && .venv/bin/python test_streamlit_ui.py
```

---

## 8. Behavior rules checklist (must preserve)

1. **Boundaries stay strict** — UI never calls MCP/DB directly; MCP tools never own LLM routing.
2. **Missing compare = hard stop** — exact unavailable message only; no table, no recommendation, no `CON-0001`/`CON-0002` default.
3. **Missing search/profile** — “No such contract is available…” with `contract_not_present`.
4. **Invoice/actual spend** — out of scope; refuse without calling spend tools.
5. **Successful compares** — N-way any-ID support + comparative recommendation framework applies only when tools succeed.
6. **Persona memory** — auto-save + explicit pin/retrieve/delete conversations; Streamlit owns writes when `clientPersistsMemory` is set.
7. **Fixtures** — LinkSquares JSON only for offline POC data.
8. **Runtime** — Streamlit → Flask → MCP is the sole validated POC path (no Foundry deploy code in-repo).

---

## 9. One-liner summary

VAL CoPilot is a three-layer tool-layer POC: Streamlit validation UI → Flask/LangChain (or offline) cognitive router → FastMCP Fabric/Search tools backed by LinkSquares fixtures offline. It supports N-way any-ID compares with a hard stop when suppliers/IDs are missing, structured search/profile/overlap/risk tools, and SQLite persona memory for saving, retrieving, and deleting previous searches and conversations.
