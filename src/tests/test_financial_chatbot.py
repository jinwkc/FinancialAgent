"""재무 상담 프롬프트, MCP 도구 경계, PDF 출력의 오프라인 회귀 테스트."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

# 앱 모듈 import 시 Settings가 키를 요구하지만, 이 테스트들은 외부 API를 호출하지 않는다.
os.environ.setdefault("OPENAI_API_KEY", "offline-test-key")
SRC_DIR = Path(__file__).resolve().parents[1]
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import pymupdf
from langchain_core.messages import AIMessage, HumanMessage

from app import mcp_tools
from app.prompts import UNDERSTANDING_LEVELS, build_financial_system_prompt
from app import pdf_report


class FinancialPromptTests(unittest.TestCase):
    def test_each_level_has_a_distinct_prompt_with_required_tool_guidance(self) -> None:
        prompts = [build_financial_system_prompt(level) for level in UNDERSTANDING_LEVELS]

        self.assertEqual(len(UNDERSTANDING_LEVELS), 4)
        self.assertEqual(len(set(prompts)), 4)
        for prompt in prompts:
            self.assertIn("get_company_financial_data", prompt)
            self.assertIn("create_financial_report_pdf", prompt)
            self.assertIn("corp_code", prompt)

    def test_unknown_level_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            build_financial_system_prompt("5. 회계사")

    def test_agent_uses_default_model_parameters_without_temperature_override(self) -> None:
        import app.agent as agent_module

        class FakeBoundModel:
            def bind_tools(self, tools, **kwargs):
                return self

            def invoke(self, messages):
                return AIMessage(content="offline response")

        class FakeChatOpenAI:
            def __init__(self, **kwargs):
                self.kwargs = kwargs
                self.bound_model = FakeBoundModel()
                self_instances.append(self)

            def bind_tools(self, tools, **kwargs):
                return self.bound_model

        self_instances = []
        with patch.object(agent_module, "ChatOpenAI", FakeChatOpenAI):
            graph = agent_module._compile_agent("offline system prompt", [])
            result = graph.invoke({"messages": [HumanMessage(content="offline question")]})

        self.assertEqual(len(self_instances), 1)
        self.assertNotIn("temperature", self_instances[0].kwargs)
        self.assertEqual(result["messages"][-1].content, "offline response")


class FinancialMCPToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_company_name_tool_forwards_arguments_and_serializes_result(self) -> None:
        tool = mcp_tools.get_company_financial_data
        forwarded: list[dict[str, object]] = []

        async def fake_fetch(**kwargs):
            forwarded.append(kwargs)
            return {"company_name": kwargs["company_name"], "reports": ["latest"]}

        with patch("app.mcp_tools._fetch_company_financial_data", new=fake_fetch):
            result = await tool("삼성전자", history_count=2, fs_div="OFS")

        self.assertEqual(
            forwarded,
            [{"company_name": "삼성전자", "history_count": 2, "fs_div": "OFS"}],
        )
        self.assertEqual(json.loads(result), {"company_name": "삼성전자", "reports": ["latest"]})

    async def test_company_name_tool_rejects_invalid_query_options(self) -> None:
        tool = mcp_tools.get_company_financial_data

        with self.assertRaises(ValueError):
            await tool("삼성전자", history_count=0, fs_div="CFS")
        with self.assertRaises(ValueError):
            await tool("삼성전자", history_count=1, fs_div="INVALID")

    async def test_tool_end_to_end_uses_minimal_api_calls_and_serializes_none_fields(
        self,
    ) -> None:
        """mcp_tools 진입점에서 실제 callImportantAPI 경로까지 최소 API 정책이 유지되는지 확인한다."""
        from app.callImportantAPI import OpenDartImportantClient

        fake_report = {
            "rcept_no": "20240101000001",
            "report_nm": "2023사업보고서",
            "rcept_dt": "20240101",
            "reprt_code": "11011",
            "bsns_year": "2023",
        }

        async def fake_resolve_company_name(self, company_name, database_url=None, limit=10):
            return {"corp_code": "00126380", "corp_name": company_name}

        async def fake_get_periodic_reports(self, corp_code, history_count=1, database_url=None):
            return [fake_report]

        async def fake_get_single_indices(self, corp_code, bsns_year, reprt_code, idx_cl_code):
            return {"status": "000", "list": []}

        async def fake_get_single_accounts_all(self, corp_code, bsns_year, reprt_code, fs_div):
            return {"status": "000", "list": []}

        single_accounts_calls: list[tuple[str, str, str]] = []
        company_calls: list[str] = []

        async def spy_get_single_accounts(self, corp_code, bsns_year, reprt_code):
            single_accounts_calls.append((corp_code, bsns_year, reprt_code))
            return {"status": "000", "list": []}

        async def spy_get_company(self, corp_code):
            company_calls.append(corp_code)
            return {"status": "000", "corp_name": "테스트"}

        with patch.dict(os.environ, {"DART_API_KEY": "offline-test-key"}), \
                patch.object(OpenDartImportantClient, "resolve_company_name", new=fake_resolve_company_name), \
                patch.object(OpenDartImportantClient, "get_periodic_reports", new=fake_get_periodic_reports), \
                patch.object(OpenDartImportantClient, "get_single_indices", new=fake_get_single_indices), \
                patch.object(OpenDartImportantClient, "get_single_accounts_all", new=fake_get_single_accounts_all), \
                patch.object(OpenDartImportantClient, "get_single_accounts", new=spy_get_single_accounts), \
                patch.object(OpenDartImportantClient, "get_company", new=spy_get_company):
            raw_result = await mcp_tools.get_company_financial_data("테스트기업")

        self.assertEqual(single_accounts_calls, [])
        self.assertEqual(company_calls, [])

        payload = json.loads(raw_result)
        self.assertIsNone(payload["company_detail"])
        self.assertIsNone(payload["reports"][0]["accounts"])
        self.assertEqual(payload["reports"][0]["accounts_all"], {"status": "000", "list": []})


class OpenDartMinimalApiCallTests(unittest.IsolatedAsyncioTestCase):
    """최소 API 호출 정책(get_single_accounts/get_company 생략)을 검증한다."""

    async def test_get_company_financial_data_skips_single_accounts_and_company_calls(
        self,
    ) -> None:
        from app.callImportantAPI import OpenDartImportantClient

        client = OpenDartImportantClient(api_key="offline-test-key")

        fake_report = {
            "rcept_no": "20240101000001",
            "report_nm": "2023사업보고서",
            "rcept_dt": "20240101",
            "reprt_code": "11011",
            "bsns_year": "2023",
        }

        async def fake_resolve_company_name(company_name, database_url=None, limit=10):
            return {"corp_code": "00126380", "corp_name": company_name}

        async def fake_get_periodic_reports(corp_code, history_count=1, database_url=None):
            return [fake_report]

        async def fake_get_single_indices(corp_code, bsns_year, reprt_code, idx_cl_code):
            return {"status": "000", "list": []}

        async def fake_get_single_accounts_all(corp_code, bsns_year, reprt_code, fs_div):
            return {"status": "000", "list": []}

        single_accounts_calls: list[tuple[str, str, str]] = []
        company_calls: list[str] = []

        async def spy_get_single_accounts(corp_code, bsns_year, reprt_code):
            single_accounts_calls.append((corp_code, bsns_year, reprt_code))
            return {"status": "000", "list": []}

        async def spy_get_company(corp_code):
            company_calls.append(corp_code)
            return {"status": "000", "corp_name": "테스트"}

        with patch.object(client, "resolve_company_name", new=fake_resolve_company_name), \
                patch.object(client, "get_periodic_reports", new=fake_get_periodic_reports), \
                patch.object(client, "get_single_indices", new=fake_get_single_indices), \
                patch.object(client, "get_single_accounts_all", new=fake_get_single_accounts_all), \
                patch.object(client, "get_single_accounts", new=spy_get_single_accounts), \
                patch.object(client, "get_company", new=spy_get_company):
            result = await client.get_company_financial_data(company_name="테스트기업")

        self.assertEqual(single_accounts_calls, [])
        self.assertEqual(company_calls, [])
        self.assertIsNone(result["reports"][0]["accounts"])
        self.assertIsNone(result["company_detail"])
        self.assertEqual(result["reports"][0]["accounts_all"], {"status": "000", "list": []})


class FinancialPDFTests(unittest.TestCase):
    def test_report_contains_korean_text_and_download_token(self) -> None:
        with tempfile.TemporaryDirectory(prefix="financial-report-test-") as temp_dir:
            with patch.object(pdf_report, "REPORT_DIR", Path(temp_dir)):
                result = pdf_report.generate_financial_report_pdf(
                    company_name="삼성전자",
                    report_period="2025년 사업보고서",
                    executive_summary="매출과 영업이익 요약",
                    financial_analysis="자산과 부채 변화를 분석합니다.",
                    key_metrics="매출액: 100원",
                    caveats="연결 기준 공시자료입니다.",
                    sources="OpenDART 사업보고서",
                )

            output_path = Path(temp_dir) / f"{result['report_id']}.pdf"
            self.assertTrue(output_path.is_file())
            self.assertIn(f"PDF_READY:{result['report_id']}:", result["download_token"])
            with pymupdf.open(output_path) as document:
                extracted = "\n".join(page.get_text() for page in document)
                self.assertIn("삼성전자", extracted)
                self.assertIn("OpenDART 사업보고서", extracted)

    def test_blank_company_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="financial-report-test-") as temp_dir:
            with patch.object(pdf_report, "REPORT_DIR", Path(temp_dir)):
                with self.assertRaises(ValueError):
                    pdf_report.generate_financial_report_pdf(
                        company_name=" ", report_period="", executive_summary="",
                        financial_analysis="", key_metrics="", caveats="", sources="",
                    )
            self.assertEqual(list(Path(temp_dir).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
