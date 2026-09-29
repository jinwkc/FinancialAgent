"""Unit tests for extracting financial chart data from MCP messages."""

import json
import unittest

from langchain_core.messages import HumanMessage, ToolMessage

from app.chart_data import build_chart_data, extract_latest_chart_data_list


def _payload(company_name: str, assets: int, revenue: int) -> dict:
    return {
        "company": {"corp_name": company_name},
        "reports": [
            {
                "report": {"report_nm": "2025 사업보고서", "rcept_no": "20260301000001"},
                "normalized_accounts": [
                    {"sj_div": "BS", "account_id": "ifrs-full_Assets", "account_nm": "자산총계", "amount": str(assets)},
                    {"sj_div": "BS", "account_id": "ifrs-full_Liabilities", "account_nm": "부채총계", "amount": "400000000000"},
                    {"sj_div": "BS", "account_id": "ifrs-full_Equity", "account_nm": "자본총계", "amount": "600000000000"},
                    {"sj_div": "IS", "account_id": "ifrs-full_Revenue", "account_nm": "매출액", "amount": str(revenue)},
                    {"sj_div": "IS", "account_id": "dart_OperatingIncomeLoss", "account_nm": "영업이익", "amount": "120000000000"},
                    {"sj_div": "IS", "account_id": "ifrs-full_ProfitLoss", "account_nm": "당기순이익", "amount": "90000000000"},
                ],
            }
        ],
    }


class ChartDataTests(unittest.TestCase):
    def test_build_chart_data_uses_normalized_accounts_and_converts_won_to_trillion(self) -> None:
        result = build_chart_data(_payload("삼성전자", 1_000_000_000_000, 2_000_000_000_000))

        self.assertIsNotNone(result)
        self.assertEqual(result["company_name"], "삼성전자")
        self.assertEqual(result["report_name"], "2025 사업보고서")
        self.assertEqual(result["financial_position"][0]["value_trillion"], 1.0)
        self.assertEqual(result["profitability"][0]["value_trillion"], 2.0)

    def test_build_chart_data_returns_none_when_no_supported_metric_is_available(self) -> None:
        payload = {
            "reports": [
                {
                    "report": {},
                    "normalized_accounts": [
                        {"sj_div": "BS", "account_id": "unknown", "account_nm": "기타", "amount": "-"}
                    ],
                }
            ]
        }

        self.assertIsNone(build_chart_data(payload))

    def test_extract_latest_chart_data_uses_only_current_turn_and_latest_company_result(self) -> None:
        old_result = ToolMessage(content=json.dumps(_payload("이전회사", 1, 1)), tool_call_id="old")
        first_results = ToolMessage(
            content=json.dumps([_payload("삼성전자", 1_000_000_000_000, 2_000_000_000_000),
                                _payload("LG전자", 3_000_000_000_000, 4_000_000_000_000)], ensure_ascii=False),
            tool_call_id="first",
        )
        latest_samsung = ToolMessage(
            content=json.dumps(_payload("삼성전자", 5_000_000_000_000, 6_000_000_000_000), ensure_ascii=False),
            tool_call_id="latest",
        )

        results = extract_latest_chart_data_list(
            [HumanMessage(content="지난 조회"), old_result, HumanMessage(content="두 회사를 비교해줘"), first_results, latest_samsung]
        )

        self.assertEqual([item["company_name"] for item in results], ["삼성전자", "LG전자"])
        self.assertEqual(results[0]["financial_position"][0]["value_trillion"], 5.0)
        self.assertEqual(results[1]["financial_position"][0]["value_trillion"], 3.0)


if __name__ == "__main__":
    unittest.main()
