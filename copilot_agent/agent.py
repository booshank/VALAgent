"""
Central cognitive processing node: AzureChatOpenAI + OpenAI tools agent.

Strict routing boundary is enforced in the system prompt (not in mcp_server).
Falls back to the offline MCP router when Azure OpenAI is firewalled (403) or
when USE_OFFLINE_MOCKS / AZURE_OPENAI_FORCE_OFFLINE is enabled.
"""

from __future__ import annotations

import logging
from typing import Any

try:
    from langchain.agents import AgentExecutor, create_openai_tools_agent
except ImportError:
    # LangChain 1.x relocated the OpenAI tools agent stack into langchain-classic.
    from langchain_classic.agents import AgentExecutor, create_openai_tools_agent

from langchain_core.messages import AIMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_openai import AzureChatOpenAI

from config import get, require
from mcp_clients import bridge
from offline_router import run_offline_turn

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are VAL CoPilot, an enterprise cognitive routing agent.

Strict Cognitive Routing Boundary — choose tools by intent domain:

1. Relational / Financial (purchase orders, vendor spend metrics, dates, aggregates)
   → Use Fabric SQL tools from the fabric_data MCP server
     (`get_expiring_contracts`, `get_vendor_spend_summary`).

2. Contract analytics (compare two contracts, find missing/incomplete fields)
   → Use Fabric analytics tools from the fabric_data MCP server
     (`compare_contracts`, `check_missing_contract_fields`).
   Lookup/filter contracts by ContractID/Number, SupplierName, ContractName,
   ContractType, and/or AnnualContractValue (same dimensions on expiring/spend/search tools).

3. Unstructured Deep Document Context (legal liabilities, contract language, raw PDF/text)
   → Use Azure AI Search tools from the fabric_data MCP server
     (`search_cloud_blob_contracts`).

4. Localized Meta State / Operational Memory (session notes, prior decisions, embeddings)
   → Use Postgres / PGVector tools from the pgvector MCP server.

Rules:
- Never invent financial figures or legal clauses; always ground answers in tool results.
- Prefer the narrowest tool that satisfies the user intent.
- When multiple domains apply, call each relevant tool and synthesize a single answer.
- Keep responses concise and cite which data source backed each claim.
"""

_agent_executor: AgentExecutor | None = None


def _truthy(name: str) -> bool:
    return get(name, "").lower() in {"1", "true", "yes", "on"}


def _force_offline_llm() -> bool:
    return _truthy("USE_OFFLINE_MOCKS") or _truthy("AZURE_OPENAI_FORCE_OFFLINE")


def _is_azure_network_block(exc: BaseException) -> bool:
    text = str(exc).lower()
    markers = (
        "access denied due to virtual network/firewall rules",
        "virtual network/firewall",
        "error code: 403",
        "permissiondenied",
        "firewall rules",
    )
    return any(marker in text for marker in markers)


def _build_llm() -> AzureChatOpenAI:
    return AzureChatOpenAI(
        azure_endpoint=require("AZURE_OPENAI_ENDPOINT"),
        api_key=require("AZURE_OPENAI_API_KEY"),
        azure_deployment=require("AZURE_OPENAI_DEPLOYMENT_NAME"),
        api_version=get("AZURE_OPENAI_API_VERSION", "2024-08-01-preview"),
        temperature=0.1,
        timeout=60,
        max_retries=1,
    )


async def get_agent_executor() -> AgentExecutor:
    global _agent_executor
    if _agent_executor is not None:
        return _agent_executor

    tools = await bridge.get_tools()
    llm = _build_llm()
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", SYSTEM_PROMPT),
            MessagesPlaceholder("chat_history", optional=True),
            ("human", "{input}"),
            MessagesPlaceholder("agent_scratchpad"),
        ]
    )
    agent = create_openai_tools_agent(llm, tools, prompt)
    _agent_executor = AgentExecutor(
        agent=agent,
        tools=tools,
        verbose=True,
        handle_parsing_errors=True,
        max_iterations=8,
        return_intermediate_steps=False,
    )
    return _agent_executor


async def run_turn(user_text: str, chat_history: list[Any] | None = None) -> str:
    """Execute one cognitive turn; returns the final assistant text."""
    if _force_offline_llm():
        logger.warning(
            "Using offline cognitive router "
            "(USE_OFFLINE_MOCKS / AZURE_OPENAI_FORCE_OFFLINE enabled)"
        )
        return await run_offline_turn(user_text)

    try:
        executor = await get_agent_executor()
        result = await executor.ainvoke(
            {
                "input": user_text,
                "chat_history": chat_history or [],
            }
        )
    except Exception as exc:
        if _is_azure_network_block(exc):
            logger.warning(
                "Azure OpenAI blocked by network/firewall (%s); "
                "falling back to offline cognitive router",
                exc,
            )
            return await run_offline_turn(user_text)
        raise

    output = result.get("output", "")
    if isinstance(output, AIMessage):
        return str(output.content)
    return str(output)
