#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-$PROJECT_ROOT/.venv/bin/python}"

if [[ ! -x "$PYTHON_BIN" ]]; then
    PYTHON_BIN="$(command -v python3 || true)"
fi
if [[ -z "$PYTHON_BIN" || ! -x "$PYTHON_BIN" ]]; then
    printf '%s\n' "Python 3 실행 파일을 찾지 못했습니다. .venv를 만들거나 PYTHON_BIN을 지정하세요." >&2
    exit 2
fi

cd "$PROJECT_ROOT"
exec "$PYTHON_BIN" - "$@" <<'PY'
"""callImportantAPI.py의 순수 함수와 실제 OpenDART/CorpCode 호출을 점검한다."""

import argparse
import asyncio
import sys
import zipfile
from io import BytesIO
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path.cwd()
load_dotenv(ROOT / ".env")
sys.path.insert(0, str(ROOT / "src"))

from app import callImportantAPI as api


parser = argparse.ArgumentParser(description="callImportantAPI.py 모든 함수 실행 점검")
parser.add_argument(
    "--company-name",
    default="삼성전자",
    help="CorpCode DB에서 조회할 회사명 (기본값: 삼성전자)",
)
parser.add_argument(
    "--corp-code",
    default="00126380",
    help="개별 API 시험에 사용할 8자리 기업 고유번호 (기본값: 삼성전자)",
)
parser.add_argument(
    "--history-count",
    type=int,
    default=1,
    help="통합 재무자료 함수가 가져올 최신 보고서 수 (기본값: 1)",
)
args = parser.parse_args()

results = []


def describe(value):
    """응답 원문과 개인정보를 숨기고 반환 형태와 항목 수만 요약한다."""
    if isinstance(value, bytes):
        try:
            with zipfile.ZipFile(BytesIO(value)) as archive:
                return f"ZIP {len(value)} bytes, {len(archive.namelist())} entries"
        except zipfile.BadZipFile:
            return f"binary {len(value)} bytes"
    if isinstance(value, dict):
        details = [f"keys={len(value)}"]
        if "status" in value:
            details.append(f"status={value['status']}")
        if isinstance(value.get("list"), list):
            details.append(f"rows={len(value['list'])}")
        if isinstance(value.get("reports"), list):
            details.append(f"reports={len(value['reports'])}")
        return "dict " + ", ".join(details)
    if isinstance(value, list):
        return f"list {len(value)} items"
    if isinstance(value, str):
        return f"string {len(value)} chars"
    return type(value).__name__


def record(name, value=None, error=None, skipped=False):
    if skipped:
        state, detail = "SKIP", str(value or "필수 입력을 얻지 못함")
    elif error is not None:
        if isinstance(error, api.OpenDartApiError) and error.status == "013":
            state, detail = "NO DATA", "OpenDART status=013 (해당 조건 데이터 없음)"
        else:
            state = "FAIL"
            status = f", status={error.status}" if isinstance(error, api.OpenDartApiError) else ""
            detail = f"{type(error).__name__}{status}"
    else:
        state, detail = "PASS", describe(value)
    results.append((name, state, detail))


def run_sync(name, function, *values):
    try:
        record(name, function(*values))
    except Exception as exc:  # 결과 요약에 예외 메시지나 요청 URL을 노출하지 않는다.
        record(name, error=exc)


async def run_async(name, function, *values, **kwargs):
    try:
        record(name, await function(*values, **kwargs))
    except Exception as exc:
        record(name, error=exc)


def run_helpers():
    """모듈의 입력 검증·보고서 해석·정규화 함수들을 실행한다."""
    try:
        key = api.get_api_key()
        record("get_api_key", "configured" if key else None)
    except Exception as exc:
        record("get_api_key", error=exc)

    run_sync("_require_corp_code", api._require_corp_code, args.corp_code)
    run_sync(
        "_require_report_params",
        api._require_report_params,
        args.corp_code,
        "2025",
        "11012",
    )
    run_sync("_report_code_from_name", api._report_code_from_name, "2025년 반기보고서")
    run_sync(
        "_business_year_from_report",
        api._business_year_from_report,
        {"report_nm": "2025년 반기보고서", "rcept_dt": "20250814"},
    )
    run_sync("_normalize_numeric_text(valid)", api._normalize_numeric_text, "1,234.50")
    run_sync("_normalize_numeric_text(missing)", api._normalize_numeric_text, "-")

    sample_report = {
        "corp_code": args.corp_code,
        "corp_name": args.company_name,
        "bsns_year": "2025",
        "reprt_code": "11012",
        "report_nm": "2025년 반기보고서",
        "rcept_no": "20250814000000",
        "rcept_dt": "20250814",
    }
    run_sync("_report_source_metadata", api._report_source_metadata, sample_report, "CFS")
    run_sync(
        "normalize_account_item",
        api.normalize_account_item,
        {
            "account_id": "ifrs-full_Revenue",
            "account_nm": "매출액",
            "sj_div": "IS",
            "fs_div": "CFS",
            "thstrm_amount": "1000",
            "thstrm_add_amount": "2000",
        },
        sample_report,
    )
    run_sync(
        "normalize_index_item",
        api.normalize_index_item,
        {"idx_cl_code": "M210000", "idx_nm": "수익성", "idx_val": "12.3", "fs_div": "CFS"},
        sample_report,
    )
    try:
        error = api.OpenDartApiError("013", "test")
        record("OpenDartApiError.__init__", error)
    except Exception as exc:
        record("OpenDartApiError.__init__", error=exc)


async def run_api_tests():
    """클라이언트 메서드와 두 모듈 진입점을 실제 서비스에 호출한다."""
    try:
        async with api.OpenDartImportantClient(timeout=45) as client:
            record("OpenDartImportantClient.__init__/__aenter__", "opened")

            # 모든 요청 경로를 별도로 실행해 낮은 수준의 JSON/ZIP 요청도 확인한다.
            await run_async("_request_json", client._request_json, "company.json", {"corp_code": args.corp_code})
            await run_async("_request_binary", client._request_binary, "corpCode.xml", {})
            await run_async("call_json_api", client.call_json_api, "/api/company.json", {"corp_code": args.corp_code})
            await run_async("get_corp_code_zip", client.get_corp_code_zip)

            company = None
            try:
                company = await client.resolve_company_name(args.company_name)
                record("resolve_company_name", company)
            except Exception as exc:
                record("resolve_company_name", error=exc)

            corp_code = str(company.get("corp_code")) if company else args.corp_code
            await run_async("get_company", client.get_company, corp_code)

            reports = []
            try:
                reports = await client.get_periodic_reports(corp_code, args.history_count)
                record("get_periodic_reports", reports)
            except Exception as exc:
                record("get_periodic_reports", error=exc)

            await run_async(
                "search_disclosures",
                client.search_disclosures,
                corp_code=corp_code,
                bgn_de="20250101",
                end_de="20991231",
                page_count=5,
            )

            if reports:
                latest = reports[0]
                year = latest["bsns_year"]
                report_code = latest["reprt_code"]
                receipt_no = latest["rcept_no"]

                await run_async("get_single_accounts", client.get_single_accounts, corp_code, year, report_code)
                await run_async(
                    "get_single_indices",
                    client.get_single_indices,
                    corp_code,
                    year,
                    report_code,
                    "M210000",
                )
                await run_async(
                    "get_single_accounts_all",
                    client.get_single_accounts_all,
                    corp_code,
                    year,
                    report_code,
                    "CFS",
                )
                await run_async("get_document", client.get_document, receipt_no)
                await run_async("get_multi_accounts", client.get_multi_accounts, corp_code, year, report_code)
                await run_async(
                    "get_multi_indices",
                    client.get_multi_indices,
                    corp_code,
                    year,
                    report_code,
                    "M210000",
                    "M210000",
                )
                await run_async("get_xbrl_taxonomy", client.get_xbrl_taxonomy, "BS1")
                await run_async("get_xbrl_file", client.get_xbrl_file, receipt_no, report_code)
                await run_async(
                    "OpenDartImportantClient.get_company_financial_data",
                    client.get_company_financial_data,
                    args.company_name,
                    args.history_count,
                    "CFS",
                )
            else:
                for name in (
                    "get_single_accounts",
                    "get_single_indices",
                    "get_single_accounts_all",
                    "get_document",
                    "get_multi_accounts",
                    "get_multi_indices",
                    "get_xbrl_taxonomy",
                    "get_xbrl_file",
                    "OpenDartImportantClient.get_company_financial_data",
                ):
                    record(name, "최신 정기보고서가 없어 실행할 인자를 만들 수 없음", skipped=True)
    except Exception as exc:
        record("OpenDartImportantClient.__init__/__aenter__", error=exc)
    else:
        record("OpenDartImportantClient.__aexit__", "closed")

    await run_async(
        "call_important_api(module)",
        api.call_important_api,
        "company.json",
        {"corp_code": args.corp_code},
    )
    await run_async(
        "get_company_financial_data(module)",
        api.get_company_financial_data,
        args.company_name,
        args.history_count,
        "CFS",
    )


async def main():
    run_helpers()
    await run_api_tests()
    for name, state, detail in results:
        print(f"{state:7} {name}: {detail}")
    failures = sum(state == "FAIL" for _, state, _ in results)
    skipped = sum(state in {"SKIP", "NO DATA"} for _, state, _ in results)
    passed = sum(state == "PASS" for _, state, _ in results)
    print(f"\nSummary: {passed} passed, {failures} failed, {skipped} skipped/no-data")
    return 1 if failures else 0


raise SystemExit(asyncio.run(main()))
PY
