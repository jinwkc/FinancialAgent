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
"""실제 회사의 OpenDART 통합 조회 반환값을 JSON으로 출력한다."""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path.cwd()
load_dotenv(ROOT / ".env")
sys.path.insert(0, str(ROOT / "src"))

from app.callImportantAPI import OpenDartApiError, get_company_financial_data


parser = argparse.ArgumentParser(
    description="회사명으로 조회한 OpenDART 재무자료 반환값 전체를 JSON으로 출력합니다."
)
parser.add_argument("company_name", help="CorpCode DB에 등록된 정확한 회사명")
parser.add_argument(
    "--history-count",
    type=int,
    default=1,
    help="최신 보고서를 포함해 조회할 보고서 수 (기본값: 1)",
)
parser.add_argument(
    "--fs-div",
    choices=("CFS", "OFS"),
    default="CFS",
    help="연결(CFS) 또는 별도(OFS) 재무제표 (기본값: CFS)",
)
args = parser.parse_args()


async def main():
    result = await get_company_financial_data(
        company_name=args.company_name,
        history_count=args.history_count,
        fs_div=args.fs_div,
    )
    # API 인증키는 반환 데이터에 포함하지 않으며, 반환된 회사·재무자료만 출력한다.
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2, default=str)
    sys.stdout.write("\n")


try:
    asyncio.run(main())
except OpenDartApiError as exc:
    print(f"OpenDART API 오류 (status={exc.status}): {exc.message}", file=sys.stderr)
    raise SystemExit(1)
except Exception as exc:
    # 예외 문자열에 요청 URL 또는 인증 정보가 포함될 수 있어 유형만 표시한다.
    print(f"조회 실패: {type(exc).__name__}", file=sys.stderr)
    raise SystemExit(1)
PY
