"""
Central cognitive processing node: AzureChatOpenAI + OpenAI tools agent.

Strict routing boundary is enforced in the system prompt (not in mcp_server).
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

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are VAL CoPilot, an enterprise cognitive routing agent.

Strict Cognitive Routing Boundary — choose tools by intent domain:

1. Relational / Financial (purchase orders, vendor spend metrics, dates, aggregates)
   → Use Fabric SQL tools from the fabric_data MCP server
     (`get_expiring_contracts`, `get_vendor_spend_summary`).

2. Unstructured Deep Document Context (legal liabilities, contract language, raw PDF/text)
   → Use Azure AI Search tools from the fabric_data MCP server
     (`search_cloud_blob_contracts`).

3. Localized Meta State / Operational Memory (session notes, prior decisions, embeddings)
   → Use Postgres / PGVector tools from the pgvector MCP server.

Rules:
- Never invent financial figures or legal clauses; always ground answers in tool results.
- Prefer the narrowest tool that satisfies the user intent.
- When multiple domains apply, call each relevant tool and synthesize a single answer.
- Keep responses concise and cite which data source backed each claim.
"""

_agent_executor: AgentExecutor | None = None


def _build_llm() -> AzureChatOpenAI:
    return AzureChatOpenAI(
        azure_endpoint=require("AZURE_OPENAI_ENDPOINT"),
        api_key=require("AZURE_OPENAI_API_KEY"),
        azure_deployment=require("AZURE_OPENAI_DEPLOYMENT_NAME"),
        api_version=get("AZURE_OPENAI_API_VERSION", "2024-08-01-preview"),
        temperature=0.1,
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
    executor = await get_agent_executor()
    result = await executor.ainvoke(
        {
            "input": user_text,
            "chat_history": chat_history or [],
        }
    )
    output = result.get("output", "")
    if isinstance(output, AIMessage):
        return str(output.content)
    return str(output)
