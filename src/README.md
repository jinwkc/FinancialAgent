# OpenDART 재무 상담 앱

Streamlit UI에서 재무 설명 수준을 선택하고, LangGraph 에이전트가 stdio MCP 도구를 호출해 OpenDART 자료를 조회합니다. 재무 요약은 요청에 따라 PDF로 저장하고 다운로드할 수 있습니다. 이 앱에는 B2B 제안서 작성 기능이 없습니다.

## 실행

프로젝트 루트의 `.env`에 `OPENAI_API_KEY`, `OPENDART_API_KEY`(또는 `DART_API_KEY`), `CORP_CODE_DATABASE_URL`을 설정합니다. 키 값은 저장소에 넣지 마세요.

```bash
python -m pip install -r src/requirements.txt
streamlit run src/app/streamlit_app.py
```

MCP 서버는 앱이 필요할 때 `src/` 디렉터리를 작업 위치로 하여 `python -m app.mcp_server` 명령으로 stdio 실행합니다. 에이전트가 MCP에서 받는 도구는 다음과 같습니다.

- `get_company_financial_data`: 회사명으로 기업 식별 및 재무자료 조회
- `call_important_api`: `app/callImportantAPI.py`의 OpenDART JSON API 클라이언트 호출
- `create_financial_report_pdf`: 재무 상담 결과 PDF 생성

## 구조

| 파일 | 역할 |
| --- | --- |
| `app/streamlit_app.py` | 설명 수준 선택, 대화 UI, PDF 다운로드 |
| `app/agent.py` | LangGraph 에이전트 생성 및 stdio MCP 연결 |
| `app/mcp_server.py` | MCP 서버 실행 진입점 |
| `app/mcp_tools.py` | 재무 조회·일반 API·PDF MCP 도구 정의 |
| `app/callImportantAPI.py` | OpenDART HTTP 호출, 보고서 선택, 재무자료 정규화 |
| `app/corp_code_sync.py` | CorpCode 데이터베이스 조회·동기화 및 ZIP 파싱 |
| `app/pdf_report.py` | 재무 요약 PDF 생성 |
| `app/prompts.py` | 설명 수준별 재무 상담 지침 |

OpenDART HTTP 요청은 `app/callImportantAPI.py`의 `OpenDartImportantClient`에서 처리합니다. 에이전트는 MCP 도구로 이 기능을 사용합니다. CorpCode 동기화 모듈은 같은 클라이언트를 위임 호출하며, 조회와 파싱 외의 DB 동기화는 별도 운영 명령에서 실행합니다.

PDF 결과는 `src/data/reports/`에 저장됩니다. 보고서에는 `app/assets/fonts/NanumGothic-Regular.ttf`를 포함해 Windows와 macOS에서 같은 한글 글꼴로 표시하며, 글꼴 라이선스는 같은 디렉터리의 `OFL.txt`에 있습니다. 데이터베이스와 보고서 파일은 실행 데이터이므로 Git에 추가하지 않습니다.
