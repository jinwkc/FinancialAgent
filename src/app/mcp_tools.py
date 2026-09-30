# app/mcp_tools.py

"""
LangGraph Agent가 사용할 도구(Tools)를 정의하는 모듈.
비즈니스 로직(Service Layer)과 API 의존성을 분리하여 @tool 데코레이터로 래핑합니다.
"""
# Streamlit 에이전트와 외부 MCP 호스트용 도구 서버
import json as _json
from pathlib import Path as _Path

from dotenv import load_dotenv as _load_dotenv
from mcp.server.fastmcp import FastMCP

_PROJECT_ROOT = _Path(__file__).resolve().parents[2]
_load_dotenv(_PROJECT_ROOT / ".env")

from app.callImportantAPI import (
    OpenDartImportantClient,
    get_company_financial_data as _fetch_company_financial_data,
)
from app.pdf_report import generate_financial_report_pdf

mcp = FastMCP("opendart-financial-assistant", json_response=True)


# LLM 응답 토큰 절감용 후처리
# callImportantAPI.py의 원본 구조(raw 응답 + report 단위 source)는 그대로 두고,
# 여기서만 report별 raw payload(accounts/accounts_all/indices)와 계정·지표
# 항목마다 중복 저장되던 source 메타데이터(corp_code, bsns_year, rcept_no 등,
# 동일 report 내 중복 source 메타데이터 제거
_RAW_REPORT_KEYS = ("accounts", "accounts_all", "indices")


# LLM 전달 전 원본 payload와 중복 source 제거
def _minimize_financial_payload(result: dict) -> dict:
    trimmed_reports = []
    for report in result.get("reports", []):
        trimmed = {key: value for key, value in report.items() if key not in _RAW_REPORT_KEYS}
        trimmed["normalized_accounts"] = [
            {key: value for key, value in row.items() if key != "source"}
            for row in trimmed.get("normalized_accounts", [])
        ]
        trimmed["normalized_indices"] = {
            category: [
                {key: value for key, value in row.items() if key != "source"}
                for row in rows
            ]
            for category, rows in trimmed.get("normalized_indices", {}).items()
        }
        trimmed_reports.append(trimmed)
    return {**result, "reports": trimmed_reports}


# 회사명으로 OpenDART 최신 재무자료를 조회하고 원본 및 정규화 값을 반환
#
# company_name: CorpCode DB 검색용 이름. corp_code 직접 입력 없음
# history_count는 가져올 최신 정기보고서 수이며, fs_div는 연결 CFS 또는 별도 OFS
@mcp.tool()
async def get_company_financial_data(
    company_name: str,
    history_count: int = 1,
    fs_div: str = "CFS",
) -> str:
    """회사명으로 재무자료를 조회하고 원본·정규화 데이터 JSON을 반환한다."""
    if history_count < 1:
        raise ValueError("history_count는 1 이상이어야 합니다.")
    if fs_div not in {"CFS", "OFS"}:
        raise ValueError("fs_div는 CFS 또는 OFS여야 합니다.")
    result = await _fetch_company_financial_data(
        company_name=company_name,
        history_count=history_count,
        fs_div=fs_div,
    )
    # 과거 구현: raw 응답과 중복 source 포함
    # return _json.dumps(result, ensure_ascii=False, default=str)
    # 현재 구현: LLM 전달 JSON에서만 raw payload와 중복 source 제거
    return _json.dumps(_minimize_financial_payload(result), ensure_ascii=False, default=str)


# callImportantAPI.py의 OpenDART JSON API 호출 함수를 MCP 도구로 제공
@mcp.tool()
async def call_important_api(endpoint: str, params: dict[str, str] | None = None) -> str:
    """OpenDART JSON API를 호출하고 결과를 JSON으로 반환한다."""
    async with OpenDartImportantClient() as client:
        result = await client.call_json_api(endpoint, params)
    return _json.dumps(result, ensure_ascii=False, default=str)


# 대화에서 정리한 기업 재무 요약을 지표 카드가 포함된 한국어 PDF로 저장
#
# 성공하면 Streamlit 화면이 다운로드 버튼을 연결할 PDF_READY 토큰을 반환
# key_metrics는 지표마다 한 줄로 작성하고, 가능하면
# ``지표명 | 현재값과 단위 | 비교값과 비교 기간`` 형식을 사용
@mcp.tool()
def create_financial_report_pdf(
    company_name: str,
    report_period: str,
    executive_summary: str,
    financial_analysis: str,
    key_metrics: str,
    caveats: str,
    sources: str,
) -> str:
    """한국어 재무 PDF를 생성하고 다운로드용 PDF_READY 토큰을 반환한다."""
    result = generate_financial_report_pdf(
        company_name=company_name,
        report_period=report_period,
        executive_summary=executive_summary,
        financial_analysis=financial_analysis,
        key_metrics=key_metrics,
        caveats=caveats,
        sources=sources,
    )
    return result["download_token"]


ALL_FINANCIAL_TOOLS = [get_company_financial_data, call_important_api, create_financial_report_pdf]
