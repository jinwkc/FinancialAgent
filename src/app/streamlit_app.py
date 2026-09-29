"""이해 수준을 선택하고 재무 상담 및 PDF 다운로드를 제공하는 Streamlit UI."""

from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path

import plotly.graph_objects as go
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
from app.chart_data import extract_latest_chart_data_list

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

def _metric_map(chart_data: dict, section: str) -> dict:
    return {row["metric"]: row for row in chart_data.get(section, [])}


def _render_single_company_charts(chart_data: dict) -> None:
    """단일 회사는 도넛 + compact 가로 막대를 한 줄에 표시한다."""
    position_rows = _metric_map(chart_data, "financial_position")
    profit_rows = _metric_map(chart_data, "profitability")

    st.markdown("### 주요 재무정보")
    if chart_data.get("report_name"):
        st.caption(f"{chart_data['company_name']} · {chart_data['report_name']} · 단위: 조원")

    assets = position_rows.get("assets")
    liabilities = position_rows.get("liabilities")
    equity = position_rows.get("equity")
    revenue = profit_rows.get("revenue")
    operating_profit = profit_rows.get("operating_profit")
    net_income = profit_rows.get("net_income")

    left, right = st.columns(2, gap="large")

    with left:
        st.markdown("#### 재무상태")
        if assets and liabilities and equity:
            asset_value = assets["value_trillion"]
            liability_value = liabilities["value_trillion"]
            equity_value = equity["value_trillion"]
            financing_total = liability_value + equity_value
            liability_pct = (liability_value / financing_total * 100) if financing_total else 0
            equity_pct = (equity_value / financing_total * 100) if financing_total else 0

            fig = go.Figure(go.Pie(
                labels=["부채", "자본"], values=[liability_value, equity_value],
                hole=0.68, sort=False, direction="clockwise",
                textinfo="percent", textposition="inside",
                hovertemplate="%{label}<br>%{value:,.1f}조원<br>%{percent}<extra></extra>",
            ))
            fig.add_annotation(
                text=f"<b>{asset_value:,.1f}조</b><br><span style='font-size:11px'>자산</span>",
                x=0.5, y=0.5, showarrow=False, align="center",
            )
            fig.update_layout(
                height=235, margin=dict(l=4, r=4, t=0, b=0), showlegend=True,
                legend=dict(orientation="h", yanchor="bottom", y=-0.08, xanchor="center", x=0.5),
            )
            st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
            st.caption(
                f"부채 {liability_value:,.1f}조 ({liability_pct:.1f}%) · "
                f"자본 {equity_value:,.1f}조 ({equity_pct:.1f}%)"
            )
        else:
            st.caption("재무상태 차트에 필요한 자산·부채·자본 값이 부족합니다.")

    with right:
        st.markdown("#### 손익")
        profitability = [row for row in (revenue, operating_profit, net_income) if row]
        if profitability:
            revenue_value = revenue["value_trillion"] if revenue else None
            labels = [row["label"] for row in profitability]
            values = [row["value_trillion"] for row in profitability]
            texts = []
            for row in profitability:
                value = row["value_trillion"]
                pct = (value / revenue_value * 100) if revenue_value else None
                if row["metric"] == "revenue" and revenue_value:
                    pct = 100.0
                texts.append(f"{value:,.1f}조" if pct is None else f"{value:,.1f}조 · {pct:.1f}%")

            fig = go.Figure(go.Bar(
                y=labels, x=values, orientation="h", text=texts, textposition="inside",
                hovertemplate="%{y}<br>%{x:,.1f}조원<extra></extra>",
            ))
            fig.update_layout(
                height=235, showlegend=False, margin=dict(l=4, r=8, t=12, b=18),
                xaxis=dict(visible=False, fixedrange=True),
                yaxis=dict(title=None, fixedrange=True), bargap=0.38,
            )
            fig.update_yaxes(autorange="reversed")
            st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
            if revenue_value:
                st.caption("%는 매출 대비 단순 계산값입니다.")
        else:
            st.caption("손익 차트에 필요한 매출·영업이익·당기순이익 값이 부족합니다.")


def _render_comparison_charts(companies: list[dict]) -> None:
    """여러 회사는 재무구조 도넛과 주요 지표 grouped bar로 비교한다."""
    st.markdown("### 주요 재무정보 비교")
    names = [str(item.get("company_name") or "기업") for item in companies]
    st.caption(f"{' vs '.join(names)} · 단위: 조원")

    report_names = [str(item.get("report_name") or "") for item in companies]
    if len(set(report_names)) > 1:
        st.caption("※ 회사별 조회 보고서가 다를 수 있으므로 각 차트의 보고서 기준을 함께 확인하세요.")

    st.markdown("#### 재무구조")
    cols = st.columns(len(companies), gap="medium")
    for col, data in zip(cols, companies):
        position = _metric_map(data, "financial_position")
        assets = position.get("assets")
        liabilities = position.get("liabilities")
        equity = position.get("equity")
        with col:
            st.markdown(f"**{data.get('company_name', '기업')}**")
            st.caption(str(data.get("report_name") or ""))
            if assets and liabilities and equity:
                av = assets["value_trillion"]
                lv = liabilities["value_trillion"]
                ev = equity["value_trillion"]
                total = lv + ev
                fig = go.Figure(go.Pie(
                    labels=["부채", "자본"], values=[lv, ev], hole=0.68,
                    sort=False, direction="clockwise", textinfo="percent", textposition="inside",
                    hovertemplate="%{label}<br>%{value:,.1f}조원<br>%{percent}<extra></extra>",
                ))
                fig.add_annotation(text=f"<b>{av:,.1f}조</b><br><span style='font-size:11px'>자산</span>",
                                   x=0.5, y=0.5, showarrow=False)
                fig.update_layout(height=210, margin=dict(l=2, r=2, t=0, b=0), showlegend=False)
                st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
                lp = (lv / total * 100) if total else 0
                ep = (ev / total * 100) if total else 0
                st.caption(f"부채 {lp:.1f}% · 자본 {ep:.1f}%")
            else:
                st.caption("자산·부채·자본 값이 부족합니다.")

    st.markdown("#### 주요 지표 비교")
    metric_order = [
        ("assets", "자산", "financial_position"),
        ("liabilities", "부채", "financial_position"),
        ("equity", "자본", "financial_position"),
        ("revenue", "매출", "profitability"),
        ("operating_profit", "영업이익", "profitability"),
        ("net_income", "당기순이익", "profitability"),
    ]

    fig = go.Figure()
    has_value = False
    for data in companies:
        pos = _metric_map(data, "financial_position")
        prof = _metric_map(data, "profitability")
        values = []
        labels = []
        texts = []
        for key, label, section in metric_order:
            row = (pos if section == "financial_position" else prof).get(key)
            if row is None:
                continue
            value = row["value_trillion"]
            labels.append(label)
            values.append(value)
            texts.append(f"{value:,.1f}조")
            has_value = True
        fig.add_trace(go.Bar(
            name=str(data.get("company_name") or "기업"),
            y=labels, x=values, orientation="h", text=texts, textposition="auto",
            hovertemplate=f"{data.get('company_name', '기업')}<br>%{{y}}: %{{x:,.1f}}조원<extra></extra>",
        ))

    if has_value:
        fig.update_layout(
            barmode="group", height=330,
            margin=dict(l=8, r=8, t=8, b=20),
            xaxis=dict(title="조원", fixedrange=True),
            yaxis=dict(title=None, fixedrange=True, categoryorder="array",
                       categoryarray=[item[1] for item in reversed(metric_order)]),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        )
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
    else:
        st.caption("비교 차트에 사용할 주요 재무지표가 없습니다.")


def _render_financial_charts(messages) -> None:
    """최근 질문의 회사 수에 따라 단일/비교 차트를 자동으로 선택한다."""
    chart_data_list = extract_latest_chart_data_list(messages)
    if len(chart_data_list) >= 2:
        _render_comparison_charts(chart_data_list)
        return

    if len(chart_data_list) == 1:
        _render_single_company_charts(chart_data_list[0])

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


_render_financial_charts(messages)

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
