"""ImportantList.md에 정의한 OpenDART API의 비동기 호출 클라이언트.

MCP 도구나 FastAPI 핸들러에서 ``await``로 호출할 수 있도록 모든 네트워크
함수를 비동기로 제공한다. JSON 응답은 딕셔너리로, corpCode·공시 원문·XBRL
파일 응답은 ZIP/XML 바이너리로 반환한다.
"""

from __future__ import annotations

import os
import asyncio
import re
import zipfile
from datetime import date
from decimal import Decimal, InvalidOperation
from io import BytesIO
from typing import Any, Mapping

import httpx

from app.corp_code_sync import find_corp_codes_by_name


# OpenDART API 요청 주소를 만들 때 사용하는 공통 기본 URL이다.
OPEN_DART_BASE_URL = "https://opendart.fss.or.kr/api"
# 상장·비상장 법인의 고유번호가 담긴 ZIP/XML 파일을 받는 엔드포인트다.
CORP_CODE_ENDPOINT = "corpCode.xml"
# 법인의 기본 개황 정보를 조회하는 엔드포인트다.
COMPANY_ENDPOINT = "company.json"
# 공시 목록과 접수번호를 검색하는 엔드포인트다.
DISCLOSURE_LIST_ENDPOINT = "list.json"
# 특정 법인의 주요 재무 계정을 조회하는 엔드포인트다.
SINGLE_ACCOUNT_ENDPOINT = "fnlttSinglAcnt.json"
# 특정 법인의 주요 재무지표를 조회하는 엔드포인트다.
SINGLE_INDEX_ENDPOINT = "fnlttSinglIndx.json"
# 특정 법인의 전체 재무제표 계정을 조회하는 엔드포인트다.
SINGLE_ACCOUNT_ALL_ENDPOINT = "fnlttSinglAcntAll.json"
# 공시 원문 ZIP/XML 파일을 받는 기본 엔드포인트다.
DOCUMENT_ENDPOINT = "document.xml"
# 공시 원문 JSON 응답을 시도할 때 사용하는 보조 엔드포인트다.
DOCUMENT_JSON_ENDPOINT = "document.json"
# 여러 법인의 주요 재무 계정을 비교 조회하는 엔드포인트다.
MULTI_ACCOUNT_ENDPOINT = "fnlttMultiAcnt.json"
# 여러 법인의 재무지표를 비교 조회하는 엔드포인트다.
MULTI_INDEX_ENDPOINT = "fnlttCmpnyIndx.json"
# XBRL 재무제표의 계정 분류 체계를 조회하는 엔드포인트다.
XBRL_TAXONOMY_ENDPOINT = "xbrlTaxonomy.json"
# XBRL 원본 재무제표 ZIP/XML 파일을 받는 엔드포인트다.
XBRL_FILE_ENDPOINT = "fnlttXbrl.xml"

# 정기보고서(사업·반기·분기) 종류를 구분하는 OpenDART 보고서 코드 집합이다.
REPORT_CODES = {"11013", "11012", "11014", "11011"}
# 개별재무제표(OFS)와 연결재무제표(CFS)를 허용하는 재무제표 구분 코드 집합이다.
FS_DIVISIONS = {"OFS", "CFS"}


class OpenDartApiError(RuntimeError):
    """OpenDART가 HTTP 또는 API 오류를 반환했을 때 발생하는 예외."""

    def __init__(self, status: str | None, message: str | None):
        self.status = status
        self.message = message or "OpenDART API 오류"
        super().__init__(f"OpenDART 오류 {status}: {self.message}")


def get_api_key(api_key: str | None = None) -> str:
    """OpenDART 인증키를 인자로 받거나 환경변수에서 반환한다.

    Args:
        api_key: 호출자가 직접 전달할 40자리 OpenDART 인증키. 생략하면
            ``DART_API_KEY``와 ``OPENDART_API_KEY``를 순서대로 확인한다.

    Returns:
        사용할 인증키 문자열.

    Raises:
        RuntimeError: 인증키를 찾지 못한 경우.
    """

    key = api_key or os.getenv("DART_API_KEY") or os.getenv("OPENDART_API_KEY")
    if not key:
        raise RuntimeError(
            "DART_API_KEY 또는 OPENDART_API_KEY 환경변수가 설정되어 있지 않습니다."
        )
    return key


def _require_corp_code(corp_code: str) -> str:
    """기업 고유번호가 숫자 8자리인지 검증하고 반환한다."""

    if len(corp_code) != 8 or not corp_code.isdigit():
        raise ValueError("corp_code는 숫자 8자리여야 합니다.")
    return corp_code


def _require_report_params(
    corp_code: str,
    bsns_year: str,
    reprt_code: str,
) -> dict[str, str]:
    """재무 API 공통 필수 파라미터를 검증하고 딕셔너리로 반환한다.

    Args:
        corp_code: OpenDART 기업 고유번호 8자리.
        bsns_year: 사업연도 4자리 문자열(예: ``"2024"``).
        reprt_code: 보고서 코드. 1분기 ``11013``, 반기 ``11012``,
            3분기 ``11014``, 사업보고서 ``11011``.

    Returns:
        검증된 ``corp_code``, ``bsns_year``, ``reprt_code`` 딕셔너리.
    """

    _require_corp_code(corp_code)
    if len(bsns_year) != 4 or not bsns_year.isdigit():
        raise ValueError("bsns_year는 숫자 4자리여야 합니다.")
    if reprt_code not in REPORT_CODES:
        raise ValueError(f"reprt_code는 {sorted(REPORT_CODES)} 중 하나여야 합니다.")
    return {
        "corp_code": corp_code,
        "bsns_year": bsns_year,
        "reprt_code": reprt_code,
    }


def _report_code_from_name(report_name: str) -> str | None:
    """공시 보고서명에서 OpenDART 재무 API용 보고서 코드를 추정한다."""

    if "사업보고서" in report_name:
        return "11011"
    if "반기보고서" in report_name:
        return "11012"
    if "3분기보고서" in report_name or "분기보고서" in report_name:
        return "11014" if "3분기" in report_name else "11013"
    return None


def _business_year_from_report(report: Mapping[str, Any]) -> str:
    """공시 보고서명 또는 접수일에서 재무 API 사업연도를 얻는다."""

    report_name = str(report.get("report_nm") or "")
    year_match = re.search(r"20\d{2}", report_name)
    if year_match:
        return year_match.group(0)
    receipt_date = str(report.get("rcept_dt") or "")
    if len(receipt_date) >= 4 and receipt_date[:4].isdigit():
        # 보고서명에 기간이 없을 때만 접수연도를 보정값으로 사용한다.
        return str(int(receipt_date[:4]) - 1)
    raise ValueError(
        "공시 결과에서 사업연도를 확인할 수 없습니다. bsns_year를 직접 지정하세요."
    )


def _normalize_numeric_text(value: Any) -> dict[str, Any]:
    """금액·지표 문자열을 검증하고 결측 상태를 보존한다.

    Args:
        value: 쉼표가 포함된 금액 문자열, 지표 문자열, ``None`` 또는 ``-``.

    Returns:
        원본 문자열(``raw``), 정규화 문자열(``value``), 사용 가능 여부
        (``available``)를 담은 딕셔너리. 결측값은 0으로 바꾸지 않는다.
    """

    if value is None:
        return {"raw": None, "value": None, "available": False}
    raw = str(value).strip()
    if not raw or raw in {"-", "—"}:
        return {"raw": raw or None, "value": None, "available": False}
    normalized = raw.replace(",", "")
    try:
        Decimal(normalized)
    except (InvalidOperation, ValueError):
        return {"raw": raw, "value": None, "available": False}
    return {"raw": raw, "value": normalized, "available": True}


def _report_source_metadata(
    report: Mapping[str, Any],
    fs_div: str | None = None,
    stlm_dt: str | None = None,
) -> dict[str, Any]:
    """재무 수치의 출처를 재현할 수 있는 공통 메타데이터를 만든다."""

    return {
        "corp_code": report.get("corp_code"),
        "corp_name": report.get("corp_name"),
        "bsns_year": report.get("bsns_year"),
        "reprt_code": report.get("reprt_code"),
        "report_nm": report.get("report_nm"),
        "rcept_no": report.get("rcept_no"),
        "rcept_dt": report.get("rcept_dt"),
        "fs_div": fs_div,
        "stlm_dt": stlm_dt,
    }


def normalize_account_item(
    item: Mapping[str, Any],
    report: Mapping[str, Any],
) -> dict[str, Any]:
    """전체 재무제표 계정을 보고서용 구조로 정규화한다.

    Args:
        item: ``fnlttSinglAcntAll.json``의 개별 계정 응답.
        report: 보고서 메타데이터(``bsns_year``, ``reprt_code`` 등).

    Returns:
        계정 식별자, 선택된 금액, 원본 금액, 출처 메타데이터를 포함한 딕셔너리.
        분기·반기·3분기 손익/현금흐름은 누적 금액 필드를 선택한다.
    """

    sj_div = item.get("sj_div")
    reprt_code = str(report.get("reprt_code") or item.get("reprt_code") or "")
    use_cumulative = sj_div not in {"BS", "SCE"} and reprt_code != "11011"
    amount_field = "thstrm_add_amount" if use_cumulative else "thstrm_amount"
    amount = _normalize_numeric_text(item.get(amount_field))
    source = _report_source_metadata(
        report,
        fs_div=item.get("fs_div"),
        stlm_dt=item.get("thstrm_dt"),
    )
    return {
        "account_id": item.get("account_id"),
        "account_nm": item.get("account_nm"),
        "account_detail": item.get("account_detail"),
        "sj_div": sj_div,
        "fs_div": item.get("fs_div"),
        "amount": amount["value"],
        "amount_raw": amount["raw"],
        "amount_available": amount["available"],
        "amount_field": amount_field,
        "currency": item.get("currency"),
        "source": source,
    }


def normalize_index_item(
    item: Mapping[str, Any],
    report: Mapping[str, Any],
) -> dict[str, Any]:
    """재무지표를 결측값 상태와 출처 메타데이터를 포함해 정규화한다.

    Args:
        item: ``fnlttSinglIndx.json``의 개별 지표 응답.
        report: 보고서 메타데이터.

    Returns:
        지표명, 지표값, 지표값 사용 가능 여부, 기준일, 출처를 포함한 딕셔너리.
        ``idx_val``이 ``None``이면 ``available=False``로 반환하며 0으로 대체하지 않는다.
    """

    value = _normalize_numeric_text(item.get("idx_val"))
    return {
        "idx_cl_code": item.get("idx_cl_code"),
        "idx_cl_nm": item.get("idx_cl_nm"),
        "idx_code": item.get("idx_code"),
        "idx_nm": item.get("idx_nm"),
        "value": value["value"],
        "value_raw": value["raw"],
        "available": value["available"],
        "stlm_dt": item.get("stlm_dt"),
        "source": _report_source_metadata(
            report,
            fs_div=item.get("fs_div"),
            stlm_dt=item.get("stlm_dt"),
        ),
    }


class OpenDartImportantClient:
    """ImportantList.md의 OpenDART API를 비동기로 호출하는 클라이언트.

    Args:
        api_key: OpenDART 인증키. 생략하면 환경변수에서 읽는다.
        timeout: 각 HTTP 요청의 기본 타임아웃(초).
        max_connections: 동시에 사용할 HTTP 연결 수.

    Returns:
        ``async with`` 블록에서 재사용 가능한 비동기 API 클라이언트.
    """

    def __init__(
        self,
        api_key: str | None = None,
        timeout: float = 30.0,
        max_connections: int = 20,
    ) -> None:
        self.api_key = get_api_key(api_key)
        self.timeout = timeout
        self.max_connections = max_connections
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "OpenDartImportantClient":
        """HTTP 연결 풀을 열고 클라이언트를 반환한다."""

        limits = httpx.Limits(
            max_connections=self.max_connections,
            max_keepalive_connections=min(self.max_connections, 10),
        )
        self._client = httpx.AsyncClient(
            base_url=OPEN_DART_BASE_URL,
            timeout=self.timeout,
            limits=limits,
        )
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        """HTTP 연결 풀을 닫는다."""

        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _request_json(
        self,
        endpoint: str,
        params: Mapping[str, str | int | None],
    ) -> dict[str, Any]:
        """JSON API를 호출하고 정상 응답 딕셔너리를 반환한다.

        Args:
            endpoint: ``company.json`` 같은 OpenDART API 파일명.
            params: 인증키를 제외한 API 요청 파라미터.

        Returns:
            OpenDART의 원본 JSON 응답 딕셔너리(``status``, ``message``, ``list`` 등).

        Raises:
            RuntimeError: ``async with`` 외부에서 호출한 경우.
            OpenDartApiError: HTTP 오류 또는 OpenDART ``status``가 ``000``이 아닌 경우.
        """

        if self._client is None:
            raise RuntimeError("클라이언트는 async with 블록 안에서 사용해야 합니다.")
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", endpoint.rsplit("/", 1)[-1]):
            raise ValueError("OpenDART API 엔드포인트 파일명만 지정할 수 있습니다.")
        request_params = {
            "crtfc_key": self.api_key,
            **{
                key: value
                for key, value in params.items()
                if value is not None and key != "crtfc_key"
            },
        }
        response = await self._client.get(endpoint, params=request_params)
        response.raise_for_status()
        payload = response.json()
        if payload.get("status") != "000":
            raise OpenDartApiError(payload.get("status"), payload.get("message"))
        return payload

    async def _request_binary(
        self,
        endpoint: str,
        params: Mapping[str, str | int | None],
    ) -> bytes:
        """ZIP/XML 파일 API를 호출하고 원본 바이트를 반환한다."""

        if self._client is None:
            raise RuntimeError("클라이언트는 async with 블록 안에서 사용해야 합니다.")
        request_params = {
            "crtfc_key": self.api_key,
            **{
                key: value
                for key, value in params.items()
                if value is not None and key != "crtfc_key"
            },
        }
        response = await self._client.get(endpoint, params=request_params)
        response.raise_for_status()
        content = response.content
        content_type = response.headers.get("content-type", "").lower()
        if "json" in content_type or not zipfile.is_zipfile(BytesIO(content)):
            try:
                payload = response.json()
            except ValueError:
                raise OpenDartApiError(None, response.text[:500]) from None
            raise OpenDartApiError(payload.get("status"), payload.get("message"))
        return content

    async def call_json_api(
        self,
        endpoint: str,
        params: Mapping[str, str | int | None] | None = None,
    ) -> dict[str, Any]:
        """ImportantList에 없는 OpenDART JSON API도 비동기로 호출한다.

        Args:
            endpoint: API 파일명 또는 ``/api`` 기준 상대 경로.
            params: API별 요청 인자. ``crtfc_key``는 자동으로 추가된다.

        Returns:
            정상 OpenDART JSON 응답 딕셔너리.
        """

        normalized_endpoint = endpoint.strip("/")
        if normalized_endpoint.startswith("api/"):
            normalized_endpoint = normalized_endpoint[4:]
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", normalized_endpoint):
            raise ValueError("OpenDART API 엔드포인트 파일명만 지정할 수 있습니다.")
        return await self._request_json(normalized_endpoint, params or {})

    async def get_corp_code_zip(self) -> bytes:
        """기업 고유번호 ZIP(``corpCode.xml``)을 반환한다.

        Returns:
            ``CORPCODE.xml``을 포함한 ZIP 바이너리. 파일 저장은 호출자 책임이다.
        """

        return await self._request_binary(CORP_CODE_ENDPOINT, {})

    async def resolve_company_name(
        self,
        company_name: str,
        database_url: str | None = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        """회사명을 CorpCode DB에서 찾아 단일 기업 정보를 반환한다.

        Args:
            company_name: 사용자가 입력한 기업명.
            database_url: CorpCode MySQL의 선택적 SQLAlchemy URL.
            limit: 후보 검색 최대 개수.

        Returns:
            ``corp_code``, 기업명, 종목코드가 포함된 기업 정보 딕셔너리.

        Raises:
            LookupError: 일치하는 기업이 없거나 후보가 여러 개인 경우.
        """

        candidates = await find_corp_codes_by_name(
            company_name,
            database_url=database_url,
            limit=limit,
        )
        if not candidates:
            raise LookupError(f"기업명 '{company_name}'에 해당하는 기업을 찾지 못했습니다.")
        if len(candidates) > 1:
            names = ", ".join(
                f"{item['corp_name']}({item['corp_code']})" for item in candidates
            )
            raise LookupError(
                f"기업명이 여러 기업과 일치합니다: {names}. "
                "정확한 기업명을 입력하세요."
            )
        return candidates[0]

    async def get_company(self, corp_code: str) -> dict[str, Any]:
        """기업개황(``company.json``)을 조회한다.

        Args:
            corp_code: 기업 고유번호 8자리.

        Returns:
            기업명, 대표자, 주소, 업종, 결산월 등이 담긴 원본 JSON 딕셔너리.
        """

        return await self._request_json(
            COMPANY_ENDPOINT,
            {"corp_code": _require_corp_code(corp_code)},
        )

    async def get_periodic_reports(
        self,
        corp_code: str,
        history_count: int = 1,
        database_url: str | None = None,
    ) -> list[dict[str, Any]]:
        """기업의 최신 정기보고서부터 과거 보고서 목록을 반환한다.

        Args:
            corp_code: 기업 고유번호 8자리.
            history_count: 반환할 보고서 수. ``1``이면 최신 보고서만 반환한다.
            database_url: 이 함수에서는 호환성을 위해 받지만 사용하지 않는다.

        Returns:
            정정공시를 하나로 합친 정기보고서 목록. 각 항목에는
            ``rcept_no``, ``report_nm``, ``rcept_dt``, ``reprt_code``,
            ``bsns_year``가 포함된다.
        """

        del database_url  # 회사 식별은 resolve_company_name에서 수행한다.
        _require_corp_code(corp_code)
        if history_count < 1:
            raise ValueError("history_count는 1 이상이어야 합니다.")

        response = await self.search_disclosures(
            corp_code=corp_code,
            bgn_de="20150101",
            end_de=date.today().strftime("%Y%m%d"),
            page_no=1,
            page_count=100,
        )
        periodic: dict[tuple[str, str], dict[str, Any]] = {}
        for item in response.get("list", []):
            report_name = str(item.get("report_nm") or "")
            reprt_code = _report_code_from_name(report_name)
            if reprt_code is None:
                continue
            report = {
                **item,
                "reprt_code": reprt_code,
                "bsns_year": _business_year_from_report(item),
            }
            key = (report["bsns_year"], reprt_code)
            previous = periodic.get(key)
            # 같은 사업연도·보고서의 정정본 중 가장 최근 접수본만 유지한다.
            if previous is None or (
                str(report.get("rcept_no") or "")
                > str(previous.get("rcept_no") or "")
            ):
                periodic[key] = report

        reports = sorted(
            periodic.values(),
            key=lambda item: (
                str(item.get("rcept_dt") or ""),
                str(item.get("rcept_no") or ""),
            ),
            reverse=True,
        )
        return reports[:history_count]

    async def get_company_financial_data(
        self,
        company_name: str,
        history_count: int = 1,
        fs_div: str = "CFS",
        database_url: str | None = None,
    ) -> dict[str, Any]:
        """회사명으로 최신 재무보고서와 선택한 과거 보고서를 수집한다.

        Args:
            company_name: 사용자가 입력한 회사명. corp_code를 직접 받지 않는다.
            history_count: 최신 보고서를 포함해 가져올 보고서 수.
            fs_div: 재무제표 구분. ``CFS``는 연결, ``OFS``는 별도 재무제표다.
            database_url: CorpCode MySQL의 선택적 SQLAlchemy URL.

        Returns:
            기업 식별정보와 보고서별 주요계정·재무지표·전체재무제표를 담은
            중첩 딕셔너리. API 응답의 원본 필드도 보존한다.
        """

        if fs_div not in FS_DIVISIONS:
            raise ValueError("fs_div는 'OFS' 또는 'CFS'여야 합니다.")
        company = await self.resolve_company_name(
            company_name,
            database_url=database_url,
        )
        corp_code = company["corp_code"]
        reports = await self.get_periodic_reports(corp_code, history_count)

        async def collect(report: dict[str, Any]) -> dict[str, Any]:
            """한 보고서에 대한 재무 API 세 가지를 병렬 수집한다."""

            report_code = report["reprt_code"]
            year = report["bsns_year"]
            accounts, indices, accounts_all = await asyncio.gather(
                self.get_single_accounts(corp_code, year, report_code),
                asyncio.gather(
                    *(
                        self.get_single_indices(
                            corp_code,
                            year,
                            report_code,
                            idx_cl_code,
                        )
                        for idx_cl_code in (
                            "M210000",  # 수익성
                            "M220000",  # 안정성
                            "M230000",  # 성장성
                            "M240000",  # 활동성
                        )
                    )
                ),
                self.get_single_accounts_all(corp_code, year, report_code, fs_div),
            )
            index_payloads = {
                category: payload
                for category, payload in zip(
                    ("profitability", "stability", "growth", "activity"),
                    indices,
                )
            }
            return {
                "report": report,
                "accounts": accounts,
                "indices": index_payloads,
                "accounts_all": accounts_all,
                # 원본 응답은 보존하고, 보고서 작성에 바로 사용할 정규화 값도 제공한다.
                "normalized_accounts": [
                    normalize_account_item(row, report)
                    for row in accounts_all.get("list", [])
                ],
                "normalized_indices": {
                    category: [
                        normalize_index_item(row, report)
                        for row in payload.get("list", [])
                    ]
                    for category, payload in index_payloads.items()
                },
                "source": _report_source_metadata(report, fs_div=fs_div),
            }

        report_data = await asyncio.gather(*(collect(report) for report in reports))
        company_detail = await self.get_company(corp_code)
        return {
            "company": company,
            "company_detail": company_detail,
            "reports": list(report_data),
        }

    async def search_disclosures(
        self,
        corp_code: str | None = None,
        bgn_de: str | None = None,
        end_de: str | None = None,
        last_reprt_at: str | None = None,
        pblntf_ty: str | None = None,
        pblntf_detail_ty: str | None = None,
        corp_cls: str | None = None,
        sort: str | None = None,
        sort_mth: str | None = None,
        page_no: int = 1,
        page_count: int = 100,
    ) -> dict[str, Any]:
        """공시검색(``list.json``) 결과를 조회한다.

        Args:
            corp_code: 선택적 기업 고유번호 8자리.
            bgn_de/end_de: 접수일 검색 구간(``YYYYMMDD``).
            last_reprt_at: 최종보고서만 조회할 때 ``"Y"`` 또는 ``"N"``.
            pblntf_ty/pblntf_detail_ty: 공시유형·상세유형 코드.
            corp_cls: 법인구분(``Y``, ``K``, ``N``, ``E``).
            sort/sort_mth: 정렬 기준과 정렬 방식.
            page_no: 페이지 번호(1부터 시작).
            page_count: 페이지당 결과 수.

        Returns:
            ``status``, 페이지 정보, 공시 목록(``list``)을 포함한 딕셔너리.
        """

        if corp_code is not None:
            _require_corp_code(corp_code)
        if page_no < 1 or page_count < 1:
            raise ValueError("page_no와 page_count는 1 이상이어야 합니다.")
        return await self._request_json(
            DISCLOSURE_LIST_ENDPOINT,
            {
                "corp_code": corp_code,
                "bgn_de": bgn_de,
                "end_de": end_de,
                "last_reprt_at": last_reprt_at,
                "pblntf_ty": pblntf_ty,
                "pblntf_detail_ty": pblntf_detail_ty,
                "corp_cls": corp_cls,
                "sort": sort,
                "sort_mth": sort_mth,
                "page_no": page_no,
                "page_count": page_count,
            },
        )

    async def get_single_accounts(
        self,
        corp_code: str,
        bsns_year: str,
        reprt_code: str,
    ) -> dict[str, Any]:
        """단일회사 주요계정(``fnlttSinglAcnt.json``)을 조회한다.

        Args:
            corp_code: 기업 고유번호 8자리.
            bsns_year: 사업연도 4자리.
            reprt_code: ``11013``(1분기), ``11012``(반기), ``11014``(3분기),
                ``11011``(사업보고서).

        Returns:
            재무상태표·손익계산서 주요계정과 기간별 금액을 담은 딕셔너리.
        """

        return await self._request_json(
            SINGLE_ACCOUNT_ENDPOINT,
            _require_report_params(corp_code, bsns_year, reprt_code),
        )

    async def get_single_indices(
        self,
        corp_code: str,
        bsns_year: str,
        reprt_code: str,
        idx_cl_code: str,
    ) -> dict[str, Any]:
        """단일회사 주요 재무지표(``fnlttSinglIndx.json``)를 조회한다.

        Args:
            corp_code: 기업 고유번호 8자리.
            bsns_year: 사업연도 4자리.
            reprt_code: 보고서 코드(``11013``, ``11012``, ``11014``, ``11011``).
            idx_cl_code: 지표분류코드. 수익성 ``M210000``, 안정성 ``M220000``,
                성장성 ``M230000``, 활동성 ``M240000``.

        Returns:
            공식 재무지표 목록을 포함한 딕셔너리.
        """

        if not idx_cl_code:
            raise ValueError("idx_cl_code는 필수입니다.")
        return await self._request_json(
            SINGLE_INDEX_ENDPOINT,
            {
                **_require_report_params(corp_code, bsns_year, reprt_code),
                "idx_cl_code": idx_cl_code,
            },
        )

    async def get_single_accounts_all(
        self,
        corp_code: str,
        bsns_year: str,
        reprt_code: str,
        fs_div: str,
    ) -> dict[str, Any]:
        """단일회사 전체 재무제표(``fnlttSinglAcntAll.json``)를 조회한다.

        Args:
            corp_code: 기업 고유번호 8자리.
            bsns_year: 사업연도 4자리.
            reprt_code: 보고서 코드.
            fs_div: ``OFS``(별도) 또는 ``CFS``(연결).

        Returns:
            BS, IS, CIS, CF, SCE 계정과 기간별 금액을 포함한 딕셔너리.
        """

        if fs_div not in FS_DIVISIONS:
            raise ValueError("fs_div는 'OFS' 또는 'CFS'여야 합니다.")
        return await self._request_json(
            SINGLE_ACCOUNT_ALL_ENDPOINT,
            {
                **_require_report_params(corp_code, bsns_year, reprt_code),
                "fs_div": fs_div,
            },
        )

    async def get_document(self, rcept_no: str) -> bytes:
        """공시 원문을 ZIP 바이너리로 반환한다.

        Args:
            rcept_no: 공시검색 API에서 받은 접수번호 14자리.

        Returns:
            공시 원문 ZIP 바이너리. 파일 저장·압축 해제는 호출자 책임이다.
        """

        if len(rcept_no) != 14 or not rcept_no.isdigit():
            raise ValueError("rcept_no는 숫자 14자리여야 합니다.")
        try:
            # 현재 실서버에서 정상적으로 ZIP을 반환하는 XML 출력 형식을 우선 사용한다.
            return await self._request_binary(
                DOCUMENT_ENDPOINT,
                {"rcept_no": rcept_no},
            )
        except OpenDartApiError as exc:
            # 서버 설정에 따라 JSON 출력 형식만 허용되는 경우를 대비한다.
            if exc.status not in {"101", "014"}:
                raise
            return await self._request_binary(
                DOCUMENT_JSON_ENDPOINT,
                {"rcept_no": rcept_no},
            )

    async def get_multi_accounts(
        self,
        corp_code: str,
        bsns_year: str,
        reprt_code: str,
    ) -> dict[str, Any]:
        """회사간 주요계정 비교(``fnlttMultiAcnt.json``) 결과를 조회한다.

        Args:
            corp_code: 비교 대상 공시회사 고유번호 8자리.
            bsns_year: 비교할 사업연도 4자리.
            reprt_code: 비교할 보고서 코드.

        Returns:
            회사간 주요계정 비교 목록과 원본 응답 상태를 담은 딕셔너리.
        """

        return await self._request_json(
            MULTI_ACCOUNT_ENDPOINT,
            _require_report_params(corp_code, bsns_year, reprt_code),
        )

    async def get_multi_indices(
        self,
        corp_code: str,
        bsns_year: str,
        reprt_code: str,
        stacnt_code: str = "M210000",
        idx_cl_code: str = "M210000",
    ) -> dict[str, Any]:
        """회사간 주요 재무지표 비교 API를 조회한다.

        Args:
            corp_code: 비교 대상 공시회사 고유번호 8자리.
            bsns_year: 비교할 사업연도 4자리.
            reprt_code: 비교할 보고서 코드.
            stacnt_code: 회사간 재무지표 요청의 기준 코드.
            idx_cl_code: 수익성 ``M210000``, 안정성 ``M220000``,
                성장성 ``M230000``, 활동성 ``M240000``.

        Returns:
            회사간 재무지표 비교 결과 딕셔너리.

        Note:
            OpenDART 공식 현재 엔드포인트는 ``fnlttCmpnyIndx.json``이다.
            ImportantList.md의 ``fnlttMultiIndx`` 표기는 이 메서드에서 공식
            엔드포인트로 매핑한다.
        """

        if not stacnt_code or not idx_cl_code:
            raise ValueError("stacnt_code와 idx_cl_code는 필수입니다.")
        return await self._request_json(
            MULTI_INDEX_ENDPOINT,
            {
                **_require_report_params(corp_code, bsns_year, reprt_code),
                "stacnt_code": stacnt_code,
                "idx_cl_code": idx_cl_code,
            },
        )

    async def get_xbrl_taxonomy(self, sj_div: str) -> dict[str, Any]:
        """XBRL 재무제표 계정 체계(``xbrlTaxonomy.json``)를 조회한다.

        Args:
            sj_div: 재무제표 구분 코드. 예: ``BS1``, ``IS1``, ``CF1``, ``SCE1``.

        Returns:
            계정 ID, 계정명, 한·영 표시명, 데이터 유형을 포함한 딕셔너리.
        """

        if not sj_div:
            raise ValueError("sj_div는 필수입니다.")
        return await self._request_json(XBRL_TAXONOMY_ENDPOINT, {"sj_div": sj_div})

    async def get_xbrl_file(
        self,
        rcept_no: str,
        reprt_code: str,
    ) -> bytes:
        """XBRL 원본(``fnlttXbrl.xml``) ZIP을 반환한다.

        Args:
            rcept_no: 공시검색 결과의 접수번호. OpenDART 원문 규격상 숫자 값이다.
            reprt_code: 보고서 코드.

        Returns:
            XBRL 원본 파일이 담긴 ZIP 바이너리.
        """

        if not rcept_no.isdigit():
            raise ValueError("rcept_no는 숫자 문자열이어야 합니다.")
        if reprt_code not in REPORT_CODES:
            raise ValueError(f"reprt_code는 {sorted(REPORT_CODES)} 중 하나여야 합니다.")
        return await self._request_binary(
            XBRL_FILE_ENDPOINT,
            {"rcept_no": rcept_no, "reprt_code": reprt_code},
        )


async def call_important_api(
    endpoint: str,
    params: Mapping[str, str | int | None] | None = None,
    api_key: str | None = None,
) -> dict[str, Any]:
    """MCP에서 동적으로 ImportantList JSON API를 호출할 수 있는 진입점.

    Args:
        endpoint: ``company.json`` 또는 ``/api/company.json`` 같은 엔드포인트.
        params: API별 파라미터. 인증키(``crtfc_key``)는 자동으로 추가된다.
        api_key: 선택적 OpenDART 인증키.

    Returns:
        OpenDART 정상 JSON 응답 딕셔너리.
    """

    async with OpenDartImportantClient(api_key=api_key) as client:
        return await client.call_json_api(endpoint, params)


async def get_company_financial_data(
    company_name: str,
    history_count: int = 1,
    fs_div: str = "CFS",
    api_key: str | None = None,
    database_url: str | None = None,
) -> dict[str, Any]:
    """MCP에서 회사명으로 최신·과거 재무보고서를 바로 조회하는 진입점.

    Args:
        company_name: 사용자가 전달한 회사명.
        history_count: 최신 보고서 포함 과거 보고서 개수.
        fs_div: ``CFS``(연결) 또는 ``OFS``(별도).
        api_key: 선택적 OpenDART 인증키.
        database_url: 선택적 CorpCode MySQL URL.

    Returns:
        CorpCode 식별정보, 기업개황, 보고서별 재무 API 원본 응답을 포함한 딕셔너리.
    """

    async with OpenDartImportantClient(api_key=api_key) as client:
        return await client.get_company_financial_data(
            company_name=company_name,
            history_count=history_count,
            fs_div=fs_div,
            database_url=database_url,
        )


__all__ = [
    "OpenDartApiError",
    "OpenDartImportantClient",
    "call_important_api",
    "get_company_financial_data",
    "get_api_key",
]
