# VAL CoPilot Workspace (`val-copilot-workspace`)

Multi-agent monorepo with three strictly decoupled boundaries. Modify only the
directory that matches your role; keep package management and concerns isolated.

```
val-copilot-workspace/
├── .env                 # single shared secrets file (from .env.example)
├── mcp_server/          # ROLE 1 — Data Retrieval Agent
├── copilot_agent/       # ROLE 2 — Cognitive Routing Agent
└── test_ui/             # ROLE 3 — Validation Agent
```

## Architecture

| Layer | Path | Responsibility |
| --- | --- | --- |
| Data Retrieval | `mcp_server/` | FastMCP tools over Fabric SQL (ODBC 18 + `ActiveDirectoryDefault`) and Azure AI Search (`query_type="semantic"`) |
| Cognitive Routing | `copilot_agent/` | LangChain `create_openai_tools_agent` + `AgentExecutor`, dual stdio MCP clients, Flask `/api/messages` |
| Validation | `test_ui/` | Streamlit harness that mocks Bot Framework activities and posts only to the routing agent |

### Cognitive routing boundary (system prompt)

1. **Relational / Financial** → Fabric SQL (`query_fabric_sql`)
2. **Unstructured document context** → Azure AI Search (`search_azure_documents`)
3. **Operational memory / meta state** → Postgres PGVector (`uvx mcp-server-pgvector`)

## Setup

1. Copy environment template (root only — never duplicate under subfolders):

```bash
cp .env.example .env
# edit .env with Azure OpenAI, Fabric, AI Search, and PGVector values
```

2. Install each layer’s dependencies in its own virtualenv:

```bash
python -m venv mcp_server/.venv && mcp_server/.venv/bin/pip install -r mcp_server/requirements.txt
python -m venv copilot_agent/.venv && copilot_agent/.venv/bin/pip install -r copilot_agent/requirements.txt
python -m venv test_ui/.venv && test_ui/.venv/bin/pip install -r test_ui/requirements.txt
```

> Cognitive routing uses LangChain’s `create_openai_tools_agent` + `AgentExecutor`
> (via `langchain-classic` on LangChain 1.x) with `AzureChatOpenAI`.

3. Ensure [ODBC Driver 18 for SQL Server](https://learn.microsoft.com/sql/connect/odbc/download-odbc-driver-for-sql-server) and `uv`/`uvx` are available on the host for Fabric SQL and PGVector MCP.

## Run

Terminal A — Cognitive Routing Agent (spawns both MCP clients):

```bash
cd copilot_agent && .venv/bin/python app.py
# listens on http://0.0.0.0:3978  →  POST /api/messages
```

Terminal B — Validation UI:

```bash
cd test_ui && .venv/bin/streamlit run app.py
```

Data Retrieval Agent is not started manually in normal operation; Client A in
`copilot_agent/mcp_clients.py` spawns `python ../mcp_server/server.py` over stdio.
Client B spawns `uvx mcp-server-pgvector`.

## Tool / route contract (cross-layer)

| Surface | Owner | Consumers must update when changed |
| --- | --- | --- |
| `query_fabric_sql`, `search_azure_documents`, `fabric_health_check` | `mcp_server/server.py` | `copilot_agent/agent.py` system prompt |
| PGVector tools (external) | `uvx mcp-server-pgvector` | `copilot_agent/mcp_clients.py`, system prompt |
| `POST /api/messages` | `copilot_agent/app.py` | `test_ui/app.py` (`COPILOT_MESSAGES_URL`) |

## Testing the Validation UI

Without Azure credentials, use the mock messages backend:

```bash
# Terminal A — mock Bot Framework /api/messages on :3978
cd test_ui && .venv/bin/python mock_messages_server.py

# Terminal B — Streamlit UI
cd test_ui && .venv/bin/streamlit run app.py
```

Open `http://localhost:8501`, send a chat message, and confirm the assistant
echo reply plus the expandable Bot Framework exchange (`channelId=emulator`).

Automated checks:

```bash
cd test_ui && .venv/bin/python test_bot_schema.py
cd test_ui && .venv/bin/python test_streamlit_ui.py
```

For a full path, run `copilot_agent/app.py` instead of the mock (requires `.env`).
