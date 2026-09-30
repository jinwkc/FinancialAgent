"""OpenDART 정규화 결과를 Streamlit 차트용 데이터로 변환한다.

LLM 답변 텍스트를 다시 파싱하지 않고 MCP ToolMessage의 구조화된
``normalized_accounts`` 값만 사용한다. 차트 표현(Plotly)은 UI 계층에서 담당한다.
"""

from __future__ import annotations

import json
from typing import Any, Iterable


_METRICS = {
    "assets": {
        "label": "자산",
        "statements": {"BS"},
        "account_ids": {"ifrs-full_Assets"},
        "names": {"자산총계", "자산 총계"},
    },
    "liabilities": {
        "label": "부채",
        "statements": {"BS"},
        "account_ids": {"ifrs-full_Liabilities"},
        "names": {"부채총계", "부채 총계"},
    },
    "equity": {
        "label": "자본",
        "statements": {"BS"},
        "account_ids": {"ifrs-full_Equity"},
        "names": {"자본총계", "자본 총계"},
    },
    "revenue": {
        "label": "매출",
        "statements": {"IS", "CIS"},
        "account_ids": {"ifrs-full_Revenue", "ifrs-full_RevenueFromContractsWithCustomers"},
        "names": {"매출액", "수익(매출액)", "영업수익", "매출"},
    },
    "operating_profit": {
        "label": "영업이익",
        "statements": {"IS", "CIS"},
        "account_ids": {"dart_OperatingIncomeLoss"},
        "names": {"영업이익", "영업이익(손실)", "영업손익"},
    },
    "net_income": {
        "label": "당기순이익",
        "statements": {"IS", "CIS"},
        "account_ids": {"ifrs-full_ProfitLoss"},
        "names": {"당기순이익", "당기순이익(손실)", "반기순이익", "분기순이익"},
    },
}


def _message_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts: list[str] = []
        for item in content:
            if isinstance(item, str):
                texts.append(item)
            elif isinstance(item, dict) and isinstance(item.get("text"), str):
                texts.append(item["text"])
        return "\n".join(texts)
    return str(content or "")


def _as_number(value: Any) -> int | float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return value
    try:
        text = str(value).replace(",", "").strip()
        if not text:
            return None
        return float(text) if "." in text else int(text)
    except (TypeError, ValueError):
        return None


def _find_metric(accounts: Iterable[dict[str, Any]], metric_key: str) -> dict[str, Any] | None:
    spec = _METRICS[metric_key]
    rows = [row for row in accounts if row.get("sj_div") in spec["statements"]]

    # 표준 account_id 우선, 기업별 계정명 차이는 이름으로 보완
    for row in rows:
        if row.get("account_id") in spec["account_ids"] and _as_number(row.get("amount")) is not None:
            return row
    for row in rows:
        if str(row.get("account_nm") or "").strip() in spec["names"] and _as_number(row.get("amount")) is not None:
            return row
    return None


# MCP 재무조회 payload 하나를 2개의 핵심 차트 데이터로 변환
#
# 최신 보고서(`reports[0]`)만 사용한다. 찾지 못한 계정은 임의 추정하지 않고
# 차트에서 제외
def build_chart_data(payload: dict[str, Any]) -> dict[str, Any] | None:
    reports = payload.get("reports")
    if not isinstance(reports, list) or not reports:
        return None

    report_block = reports[0]
    accounts = report_block.get("normalized_accounts")
    if not isinstance(accounts, list):
        return None

    report = report_block.get("report") or {}
    company = payload.get("company") or {}
    company_name = company.get("corp_name") or report.get("corp_name") or "기업"
    report_name = report.get("report_nm") or str(report.get("bsns_year") or "")

    def collect(keys: tuple[str, ...]) -> list[dict[str, Any]]:
        result = []
        for key in keys:
            row = _find_metric(accounts, key)
            if row is None:
                continue
            amount = _as_number(row.get("amount"))
            if amount is None:
                continue
            result.append(
                {
                    "metric": key,
                    "label": _METRICS[key]["label"],
                    "value": amount,
                    "value_trillion": amount / 1_000_000_000_000,
                    "currency": row.get("currency") or "KRW",
                    "account_nm": row.get("account_nm"),
                }
            )
        return result

    financial_position = collect(("assets", "liabilities", "equity"))
    profitability = collect(("revenue", "operating_profit", "net_income"))
    if not financial_position and not profitability:
        return None

    return {
        "company_name": company_name,
        "report_name": report_name,
        "rcept_no": report.get("rcept_no"),
        "financial_position": financial_position,
        "profitability": profitability,
    }


# ToolMessage content에서 재무 payload를 가능한 한 보수적으로 추출
#
# - 일반 JSON 객체 1개
# - JSON 배열 안의 여러 payload
# - MCP text block(list[dict])
# - 한 문자열에 JSON 객체가 연속으로 들어온 경우
# 를 지원한다. 재무 payload(`reports`)가 아닌 객체는 무시
def _json_payloads_from_content(content: Any) -> list[dict[str, Any]]:
    texts: list[str] = []
    if isinstance(content, str):
        texts.append(content)
    elif isinstance(content, list):
        for item in content:
            if isinstance(item, str):
                texts.append(item)
            elif isinstance(item, dict):
                if isinstance(item.get("text"), str):
                    texts.append(item["text"])
                elif "reports" in item:
                    texts.append(json.dumps(item, ensure_ascii=False))
    elif isinstance(content, dict):
        if "reports" in content:
            texts.append(json.dumps(content, ensure_ascii=False))
        elif isinstance(content.get("text"), str):
            texts.append(content["text"])

    found: list[dict[str, Any]] = []

    def add(value: Any) -> None:
        if isinstance(value, dict):
            if "reports" in value:
                found.append(value)
            # MCP/도구 래퍼 안에 payload가 들어오는 경우만 제한적으로 탐색
            for key in ("result", "data", "payload", "content"):
                nested = value.get(key)
                if isinstance(nested, (dict, list)):
                    add(nested)
        elif isinstance(value, list):
            for item in value:
                add(item)

    decoder = json.JSONDecoder()
    for raw in texts:
        text = raw.strip()
        if not text:
            continue
        # 먼저 정상 JSON 전체 파싱을 시도
        try:
            add(json.loads(text))
            continue
        except json.JSONDecodeError:
            pass

        # 여러 JSON 객체가 한 ToolMessage 문자열에 이어 붙은 경우를 지원
        idx = 0
        while idx < len(text):
            while idx < len(text) and text[idx].isspace():
                idx += 1
            if idx >= len(text):
                break
            # JSON 시작점이 아니면 다음 객체/배열 시작점까지 이동
            if text[idx] not in "[{":
                candidates = [p for p in (text.find("{", idx + 1), text.find("[", idx + 1)) if p >= 0]
                if not candidates:
                    break
                idx = min(candidates)
            try:
                value, end = decoder.raw_decode(text, idx)
            except json.JSONDecodeError:
                idx += 1
                continue
            add(value)
            idx = end

    return found


# 현재 사용자 질문에서 실제 성공한 모든 회사의 차트 데이터만 반환
#
# 마지막 HumanMessage 이후의 ToolMessage만 사용하므로 조회 실패 시 과거 회사 차트가
# 다시 나타나지 않는다. 한 ToolMessage에 여러 회사 payload가 들어와도 모두 수집
def extract_latest_chart_data_list(messages: Iterable[Any]) -> list[dict[str, Any]]:
    all_messages = list(messages)

    # 마지막 사용자 질문 위치 탐색
    last_human_index = -1
    for i, message in enumerate(all_messages):
        if message.__class__.__name__ == "HumanMessage":
            last_human_index = i

    if last_human_index < 0:
        return []

    current_turn_messages = all_messages[last_human_index + 1:]
    by_company: dict[str, dict[str, Any]] = {}
    company_order: list[str] = []

    for message in current_turn_messages:
        if message.__class__.__name__ != "ToolMessage":
            continue

        for payload in _json_payloads_from_content(getattr(message, "content", "")):
            chart_data = build_chart_data(payload)
            if not chart_data:
                continue

            company_name = str(chart_data.get("company_name") or "").strip()
            if not company_name or company_name == "기업":
                continue

            # 같은 회사가 현재 턴에서 여러 번 조회되면 가장 마지막 성공 결과로 교체
            if company_name not in by_company:
                company_order.append(company_name)
            by_company[company_name] = chart_data

    return [by_company[name] for name in company_order if name in by_company]


# 호환용: 현재 사용자 질문에서 조회된 가장 마지막 회사만 반환
def extract_latest_chart_data(messages: Iterable[Any]) -> dict[str, Any] | None:
    items = extract_latest_chart_data_list(messages)
    return items[-1] if items else None
