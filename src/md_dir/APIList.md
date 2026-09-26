# OpenDART API 목록과 사용 방법

> 작성 기준일: 2026-09-22
> 이 문서는 현재 프로젝트 코드가 아니라 금융감독원 전자공시시스템 OpenDART 공식 개발가이드만 참고해 작성했다.

## 1. 기본 호출 규칙

OpenDART OpenAPI는 기본적으로 `GET` 방식이며, 한국어 API의 기본 URL은 다음과 같다.

```text
https://opendart.fss.or.kr/api/{endpoint}.{format}
```

| 항목 | 공식 사용 방법 |
|---|---|
| 인증 | `crtfc_key`에 발급받은 40자리 인증키 전달 |
| 응답 형식 | 대부분 `.json` 또는 `.xml` 선택 |
| 문자 인코딩 | UTF-8 |
| 기업 식별자 | `corp_code`: DART 고유번호 8자리. 종목코드 6자리와 다름 |
| 보고서 식별 | `bsns_year`와 `reprt_code` 조합 사용 |
| 보고서 코드 | 1분기 `11013`, 반기 `11012`, 3분기 `11014`, 사업 `11011` |
| 정상 응답 | `status`가 `000` |
| 데이터 없음 | `013` |
| 요청 제한 초과 | `020` |
| 잘못된 요청 값 | `100` |

모든 요청에 인증키가 필요하며, 인증키는 코드에 직접 기록하지 않고 환경변수로 관리한다.

## 2. 공시정보 API

공식 분류: [공시정보 개발가이드](https://opendart.fss.or.kr/guide/main.do?apiGrpCd=DE001)

| API | 용도 | 주요 요청 인자 | 응답·사용 방법 |
|---|---|---|---|
| `list.json` / `list.xml` | 공시보고서 검색 | `crtfc_key`, 선택 `corp_code`, `bgn_de`, `end_de`, `last_reprt_at`, 공시 유형·페이지 조건 | `list`의 `rcept_no`를 후속 원문 조회에 사용. `page_no`, `page_count`로 페이지 조회 |
| `company.json` / `company.xml` | 기업개황 조회 | `crtfc_key`, `corp_code` | 기업명, 영문명, 대표전화, 업종코드, 설립일, 결산월 등 기업 기본정보 조회 |
| `document.json` / `document.xml` | 공시 원문 파일 다운로드 | `crtfc_key`, `rcept_no` 14자리 | 공시 원문 파일 응답. 먼저 `list`에서 접수번호를 확보 |
| `corpCode.xml` | DART 고유번호 전체 목록 | `crtfc_key` | ZIP 바이너리 응답. 압축 내부 XML에서 `corp_code`, 기업명, 종목코드, 변경일 추출 |

### 공시 검색 예시

```bash
curl -G 'https://opendart.fss.or.kr/api/list.json' \
  --data-urlencode "crtfc_key=${DART_API_KEY}" \
  --data-urlencode 'corp_code=00126380' \
  --data-urlencode 'bgn_de=20260101' \
  --data-urlencode 'end_de=20261231' \
  --data-urlencode 'page_no=1' \
  --data-urlencode 'page_count=100'
```

## 3. 정기보고서 주요정보 API

공식 분류: [정기보고서 주요정보 개발가이드](https://opendart.fss.or.kr/guide/main.do?apiGrpCd=DS002)

| API | 제공 정보 | 주요 요청 인자 |
|---|---|---|
| `stockTotqySttus.json` | 주식의 총수 현황 | `crtfc_key`, `corp_code`, `bsns_year`, `reprt_code` |
| `exctvSttus.json` | 임원 현황 | `crtfc_key`, `corp_code`, `bsns_year`, `reprt_code` |
| `mrhlSttus.json` | 소액주주 현황 | `crtfc_key`, `corp_code`, `bsns_year`, `reprt_code` |
| `srtpdPsndbtNrdmpBlce.json` | 단기사채 미상환 잔액 | `crtfc_key`, `corp_code`, `bsns_year`, `reprt_code` |
| `cndlCaplScritsNrdmpBlce.json` | 조건부자본증권 미상환 잔액 | `crtfc_key`, `corp_code`, `bsns_year`, `reprt_code` |
| `adtServcCnclsSttus.json` | 감사용역 체결 현황 | `crtfc_key`, `corp_code`, `bsns_year`, `reprt_code` |
| `indvdlByPayV2.json` | 개인별 보수 지급 금액 | `crtfc_key`, `corp_code`, `bsns_year`, `reprt_code` |

각 API의 세부 선택 인자는 공식 상세 가이드에서 확인해야 한다. 예를 들어 주식 총수 API는 보고서 코드별 주식 발행·감소 현황을 반환한다.

## 4. 정기보고서 재무정보 API

공식 분류: [정기보고서 재무정보 개발가이드](https://opendart.fss.or.kr/guide/main.do?apiGrpCd=DS003)

| API | 제공 정보 | 주요 요청 인자 | 응답 형식 |
|---|---|---|---|
| `fnlttSinglAcnt.json` | 단일회사 주요계정 | `crtfc_key`, `corp_code`, `bsns_year`, `reprt_code`, `fs_div` | JSON/XML |
| `fnlttMultiAcnt.json` | 다중회사 주요계정 | `crtfc_key`, 기업·연도·보고서 조건 | JSON/XML |
| `fnlttSinglAcntAll.json` | 단일회사 전체 재무제표 | `crtfc_key`, `corp_code`, `bsns_year`, `reprt_code`, `fs_div` | JSON/XML |
| `fnlttSinglIndx.json` | 단일회사 주요 재무지표 | `crtfc_key`, `corp_code`, `bsns_year`, `reprt_code`, `idx_cl_code` | JSON/XML |
| `fnlttMultiIndx.json` | 다중회사 주요 재무지표 | 기업·연도·보고서·지표 조건 | JSON/XML |
| `xbrlTaxonomy.json` | XBRL 택사노미 재무제표 양식 | `crtfc_key`, `sj_div` 등 | JSON/XML |
| `fnlttXbrl.xml` | XBRL 재무제표 원본 | `crtfc_key`, 보고서 식별 인자 | ZIP 파일 |

`fs_div`는 공식 문서의 재무제표 구분값을 따른다. 대표적으로 `OFS`는 별도재무제표, `CFS`는 연결재무제표를 의미한다. 재무 금액은 API 응답의 문자열 필드를 그대로 숫자로 가정하지 말고, 쉼표·빈 문자열·괄호 음수 여부를 확인한 뒤 변환한다.

### 단일회사 주요계정 호출 예시

```bash
curl -G 'https://opendart.fss.or.kr/api/fnlttSinglAcnt.json' \
  --data-urlencode "crtfc_key=${DART_API_KEY}" \
  --data-urlencode 'corp_code=00126380' \
  --data-urlencode 'bsns_year=2025' \
  --data-urlencode 'reprt_code=11011' \
  --data-urlencode 'fs_div=CFS'
```

## 5. 지분공시 종합정보 API

공식 분류: [지분공시 종합정보 개발가이드](https://opendart.fss.or.kr/guide/main.do?apiGrpCd=DS004)

| API | 제공 정보 | 주요 요청 인자 |
|---|---|---|
| `elestock.json` | 임원·주요주주 소유보고 | `crtfc_key`, `corp_code` |
| `majorstock.json` | 대량보유 상황보고 | `crtfc_key`, `corp_code` |
| 지분공시 세부 API | 대량보유·임원 및 주요주주 변동 정보 | 각 공식 상세 가이드의 필수 인자 |

## 6. 주요사항보고서 주요정보 API

공식 분류: [주요사항보고서 주요정보 개발가이드](https://opendart.fss.or.kr/guide/main.do?apiGrpCd=DS005)

공식 목록에는 자산양수도·풋백옵션, 부도발생, 영업정지, 회생절차, 해산사유, 유상·무상증자, 감자, 소송, 전환사채·신주인수권부사채·교환사채, 자기주식 취득·처분, 영업양수·양도, 자산 양수·양도, 합병·분할·분할합병, 주식교환·이전 등이 포함된다.

| 대표 API | 제공 정보 | 주요 요청 인자 |
|---|---|---|
| `bsnSp.json` | 영업정지 | `crtfc_key`, `corp_code`, 시작일, 종료일 |
| `bnkMngtPcbg.json` | 채권은행 등의 관리절차 개시 | `crtfc_key`, `corp_code` |
| `ovDlstDecsn.json` | 해외 증권시장 상장폐지 결정 | `crtfc_key`, `corp_code` |

세부 사건 API는 회사·보고서별로 요구 인자가 다르므로 위 공식 분류 목록에서 사건명을 선택한 뒤 해당 상세 가이드의 요청 인자를 사용한다.

## 7. 증권신고서 주요정보 API

공식 분류: [증권신고서 주요정보 개발가이드](https://opendart.fss.or.kr/guide/main.do?apiGrpCd=DS006)

| 신고서 유형 | 제공 정보 |
|---|---|
| 지분증권 | 증권신고서(지분증권) 요약 정보 |
| 채무증권 | 증권신고서(채무증권) 요약 정보 |
| 증권예탁증권 | 증권신고서(증권예탁증권) 요약 정보 |
| 합병 | 합병 관련 증권신고서 요약 정보 |
| 주식의 포괄적 교환·이전 | 교환·이전 관련 요약 정보 |
| 분할 | 분할 관련 증권신고서 요약 정보 |

## 8. Python 호출 기본 예시

```python
import os
import requests

url = "https://opendart.fss.or.kr/api/company.json"
params = {
    "crtfc_key": os.environ["DART_API_KEY"],
    "corp_code": "00126380",
}

response = requests.get(url, params=params, timeout=10)
response.raise_for_status()
payload = response.json()

if payload.get("status") != "000":
    raise RuntimeError(
        f"OpenDART error {payload.get('status')}: {payload.get('message')}"
    )

print(payload)
```

## 9. 고유번호 ZIP 처리

`corpCode.xml`은 일반 XML 응답이 아니라 ZIP 바이너리다. 다운로드 후 ZIP 내부 XML을 읽어 기업명과 `corp_code`를 매핑한다.

```python
from io import BytesIO
from zipfile import ZipFile
import requests

response = requests.get(
    "https://opendart.fss.or.kr/api/corpCode.xml",
    params={"crtfc_key": "YOUR_KEY"},
    timeout=30,
)
response.raise_for_status()

with ZipFile(BytesIO(response.content)) as archive:
    names = archive.namelist()
    xml_bytes = archive.read(names[0])
```

## 10. 운영 시 주의사항

1. 인증키는 환경변수나 비밀 저장소로 관리하고 Markdown·로그·Git에 기록하지 않는다.
2. `status == "000"`만 성공으로 처리하지 말고 `message`, 빈 `list`, 응답 건수를 함께 확인한다.
3. `020` 요청 제한 초과에 대비해 요청 횟수를 제한하고, 동일 기업·보고서 응답은 로컬 캐시를 활용한다.
4. `013`은 오류가 아니라 조회 결과가 없다는 의미이므로 업무 로직에서 구분한다.
5. 재무제표는 제출인이 작성한 공시 정보이며, 기준일 이후 정정공시로 값이 변경될 수 있다. 원문 공시와 함께 사용한다.
6. 기업 고유번호(`corp_code`), 종목코드(`stock_code`), 접수번호(`rcept_no`)를 서로 바꾸어 사용하지 않는다.

## 공식 출처

- [OpenDART 개발가이드](https://opendart.fss.or.kr/guide/main.do)
- [공시정보 API 목록](https://opendart.fss.or.kr/guide/main.do?apiGrpCd=DE001)
- [정기보고서 주요정보 API 목록](https://opendart.fss.or.kr/guide/main.do?apiGrpCd=DS002)
- [정기보고서 재무정보 API 목록](https://opendart.fss.or.kr/guide/main.do?apiGrpCd=DS003)
- [지분공시 종합정보 API 목록](https://opendart.fss.or.kr/guide/main.do?apiGrpCd=DS004)
- [주요사항보고서 주요정보 API 목록](https://opendart.fss.or.kr/guide/main.do?apiGrpCd=DS005)
- [증권신고서 주요정보 API 목록](https://opendart.fss.or.kr/guide/main.do?apiGrpCd=DS006)
