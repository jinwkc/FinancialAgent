"""재무 상담 LangGraph 에이전트와 MCP 서버 연결."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Sequence

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware
from langchain_openai import ChatOpenAI
from langchain_mcp_adapters.client import MultiServerMCPClient

_SRC_DIR = Path(__file__).resolve().parents[1]
_PROJECT_ROOT = _SRC_DIR.parent
load_dotenv(_PROJECT_ROOT / ".env")
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

# from app.prompts import build_financial_system_prompt
from app.compressed_prompts import build_financial_system_prompt


class _SerialToolCallsMiddleware(AgentMiddleware):
    """모델의 도구 호출을 한 번에 하나로 제한하는 middleware."""

    @staticmethod
    def _request_with_serial_tool_calls(request: Any) -> Any:
        model_settings = dict(request.model_settings)
        model_settings["parallel_tool_calls"] = False
        return request.override(model_settings=model_settings)

    def wrap_model_call(self, request: Any, handler: Any) -> Any:
        return handler(self._request_with_serial_tool_calls(request))

    async def awrap_model_call(self, request: Any, handler: Any) -> Any:
        return await handler(self._request_with_serial_tool_calls(request))


# 프롬프트와 MCP 도구로 create_agent Runnable 구성
def _compile_agent(system_prompt: str, tools: Sequence[object]):
    llm = ChatOpenAI(model=os.getenv("DEFAULT_LLM_MODEL", "gpt-5-nano"))
    return create_agent(
        model=llm,
        tools=list(tools),
        system_prompt=system_prompt,
        middleware=[_SerialToolCallsMiddleware()],
    )

# stdio MCP 도구 연결 및 이해 수준별 상담 그래프 생성
async def create_financial_agent_graph(understanding_level: str):
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
