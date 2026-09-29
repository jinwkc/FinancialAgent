"""재무 상담 LangGraph 에이전트와 MCP 서버 연결."""

from __future__ import annotations

import os
import sys
from functools import partial
from pathlib import Path
from typing import Annotated, Any, Sequence, TypedDict

from dotenv import load_dotenv
from langchain_core.messages import BaseMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

_SRC_DIR = Path(__file__).resolve().parents[1]
_PROJECT_ROOT = _SRC_DIR.parent
load_dotenv(_PROJECT_ROOT / ".env")
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

# from app.prompts import build_financial_system_prompt
from app.compressed_prompts import build_financial_system_prompt


class AgentState(TypedDict):
    """LangGraph가 대화와 도구 실행 메시지를 누적하는 상태."""

    messages: Annotated[Sequence[BaseMessage], add_messages]


# 아래 `_` 접두사 함수들은 이 모듈의 그래프 구성에만 쓰이는 내부 구현이다.
def _call_model_node(
    state: AgentState,
    *,
    system_prompt: str,
    llm_with_tools: Any,
) -> dict[str, list[BaseMessage]]:
    """대화 상태에 시스템 프롬프트를 보장하고 모델을 호출한다."""
    messages = list(state["messages"])
    if not messages or not isinstance(messages[0], SystemMessage):
        messages.insert(0, SystemMessage(content=system_prompt))
    return {"messages": [llm_with_tools.invoke(messages)]}


def _should_continue(state: AgentState) -> str:
    """마지막 모델 응답에 도구 호출이 있으면 도구 노드로 보낸다."""
    last_message = state["messages"][-1]
    return "tools" if getattr(last_message, "tool_calls", None) else END


def _compile_agent(system_prompt: str, tools: Sequence[object]):
    """시스템 프롬프트와 도구 집합으로 재사용 가능한 LangGraph를 만든다."""
    # GPT-5 계열 모델은 temperature 인자를 허용하지 않으므로 기본값을 사용한다.
    llm = ChatOpenAI(model=os.getenv("DEFAULT_LLM_MODEL", "gpt-5-nano"))
    llm_with_tools = llm.bind_tools(list(tools), parallel_tool_calls=False)

    workflow = StateGraph(AgentState)
    workflow.add_node(
        "agent",
        partial(
            _call_model_node,
            system_prompt=system_prompt,
            llm_with_tools=llm_with_tools,
        ),
    )
    workflow.add_node("tools", ToolNode(list(tools)))
    workflow.add_edge(START, "agent")
    workflow.add_conditional_edges("agent", _should_continue)
    workflow.add_edge("tools", "agent")
    return workflow.compile()


async def create_financial_agent_graph(understanding_level: str):
    """stdio MCP 서버에서 도구를 읽어 이해 수준별 재무 상담 그래프를 만든다."""
    system_prompt = build_financial_system_prompt(understanding_level)
    minimal_env = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": str(_SRC_DIR),
        "PYTHONUNBUFFERED": "1",
    }
    mcp_client = MultiServerMCPClient(
        {
            "opendart_financial": {
                "transport": "stdio",
                "command": sys.executable,
                "args": ["-m", "app.mcp_server"],
                "cwd": str(_SRC_DIR),
                "env": minimal_env,
            }
        }
    )
    tools = await mcp_client.get_tools()
    if not tools:
        raise RuntimeError("재무 MCP 서버에서 사용 가능한 도구를 찾지 못했습니다.")
    return _compile_agent(system_prompt, tools)
