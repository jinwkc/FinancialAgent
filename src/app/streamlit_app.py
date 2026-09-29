"""이해 수준을 선택하고 재무 상담 및 PDF 다운로드를 제공하는 Streamlit UI."""

from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

SRC_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = SRC_DIR.parent
load_dotenv(PROJECT_ROOT / ".env")
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from app.agent import create_financial_agent_graph
from app.pdf_report import REPORT_DIR
# from app.prompts import UNDERSTANDING_LEVELS
from app.compressed_prompts import UNDERSTANDING_LEVELS



st.set_page_config(page_title="OpenDART 재무 요약 챗봇", page_icon="📊", layout="wide")


@st.cache_resource(show_spinner="재무 MCP 도구를 연결하고 있습니다...")
def get_agent(understanding_level: str):
    """선택한 설명 수준에 해당하는 MCP 기반 LangGraph를 재사용한다."""
    return asyncio.run(create_financial_agent_graph(understanding_level))


def _message_text(content) -> str:
    """LangChain 메시지의 텍스트 블록을 화면 표시용 문자열로 바꾼다."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts = []
        for item in content:
            if isinstance(item, str):
                texts.append(item)
            elif isinstance(item, dict) and isinstance(item.get("text"), str):
                texts.append(item["text"])
        return "\n".join(texts)
    return str(content or "")


def _remember_pdf_outputs(messages) -> None:
    """MCP PDF 도구 결과에서 다운로드 ID와 파일명을 보관한다."""
    marker = re.compile(r"PDF_READY:([0-9a-f]{32}):([A-Za-z0-9가-힣_.-]+\.pdf)")
    for message in messages:
        if isinstance(message, ToolMessage):
            match = marker.search(_message_text(message.content))
            if match:
                st.session_state.latest_pdf = {
                    "report_id": match.group(1),
                    "filename": match.group(2),
                }


def _reset_to_level_selection() -> None:
    """설명 수준과 대화 상태를 지우고 첫 화면으로 돌아간다."""
    for key in ("understanding_level", "agent_messages", "latest_pdf"):
        st.session_state.pop(key, None)
    st.rerun()


if "understanding_level" not in st.session_state:
    st.title("OpenDART 재무 요약 챗봇")
    st.write("먼저 재무 설명을 어느 수준으로 듣고 싶은지 선택해 주세요.")
    chosen_level = st.radio(
        "재무 이해 수준",
        UNDERSTANDING_LEVELS,
        index=2,
        help="선택한 수준은 이 대화의 설명 방식과 전문 용어 사용에 반영됩니다.",
    )
    if st.button("대화 시작", type="primary"):
        st.session_state.understanding_level = chosen_level
        st.session_state.agent_messages = []
        st.session_state.latest_pdf = None
        st.rerun()
    st.stop()


level = st.session_state.understanding_level
with st.sidebar:
    st.subheader("현재 설정")
    st.write(f"설명 수준: **{level}**")
    if st.button("이해 수준 다시 선택"):
        _reset_to_level_selection()

st.title("기업 재무제표 상담")
st.caption("회사명을 입력하면 OpenDART 공시를 조회해 설명합니다. 필요하면 대화 요약을 PDF로 요청하세요.")

messages = st.session_state.setdefault("agent_messages", [])
_remember_pdf_outputs(messages)
for message in messages:
    if isinstance(message, HumanMessage):
        with st.chat_message("user"):
            st.markdown(_message_text(message.content))
    elif isinstance(message, AIMessage):
        content = _message_text(message.content)
        if content.strip():
            with st.chat_message("assistant"):
                st.markdown(content)

pdf_info = st.session_state.get("latest_pdf")
if pdf_info:
    pdf_path = REPORT_DIR / f"{pdf_info['report_id']}.pdf"
    if pdf_path.is_file():
        st.download_button(
            "재무 요약 보고서 PDF 다운로드",
            data=pdf_path.read_bytes(),
            file_name=pdf_info["filename"],
            mime="application/pdf",
            key=f"download-{pdf_info['report_id']}",
        )

user_input = st.chat_input("예: 삼성전자 최신 재무제표를 요약해줘")
if user_input:
    with st.chat_message("user"):
        st.markdown(user_input)
    pending_messages = [*messages, HumanMessage(content=user_input)]
    try:
        agent = get_agent(level)
        with st.chat_message("assistant"):
            with st.spinner("공시자료를 확인하고 답변을 작성하고 있습니다..."):
                state = asyncio.run(agent.ainvoke({"messages": pending_messages}))
            final_message = next(
                (item for item in reversed(state["messages"]) if isinstance(item, AIMessage) and _message_text(item.content).strip()),
                None,
            )
            if final_message is not None:
                st.markdown(_message_text(final_message.content))
        st.session_state.agent_messages = state["messages"]
        _remember_pdf_outputs(state["messages"])
        st.rerun()
    except Exception as exc:
        # 모델·MCP 예외에 URL이나 설정값이 포함될 수 있어 사용자 화면에는 유형만 표시한다.
        st.error(f"요청을 처리하지 못했습니다 ({type(exc).__name__}). 설정과 연결 상태를 확인해 주세요.")
