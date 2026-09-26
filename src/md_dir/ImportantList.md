# 재무제표 요약·정리 보고서용 OpenDART 중요 API 목록

> 작성 기준일: 2026-09-22
> 작성 기준: 금융감독원 전자공시시스템 OpenDART 공식 개발가이드만 사용
> 목표: 기업의 재무제표를 수집하고, 요약·비교·근거 확인이 가능한 보고서 데이터셋을 만드는 것

## 1. 권장 수집 흐름

```text
고유번호 확보
  → 기업 기본정보 확인
  → 대상 정기보고서 식별
  → 단일회사 주요계정 수집
  → 전체 재무제표·재무지표 보강
  → 다중회사 비교(선택)
  → XBRL·원문 공시로 근거 확인
```

보고서 작성에 필요한 API는 단순히 많이 호출하기보다, `식별 → 요약 → 상세 → 비교 → 검증` 단계로 나누어 수집하는 것이 적절하다.

## 2. 필수 API

| 우선순위 | API | 보고서에서의 역할 | 주요 요청 인자 | 주요 활용 결과 |
|---|---|---|---|---|
| 1 | [`corpCode.xml`](https://opendart.fss.or.kr/api/corpCode.xml) | 기업 고유번호 매핑 | `crtfc_key` | 기업명·영문명·종목코드·`corp_code`·변경일 |
| 2 | [`company.json`](https://opendart.fss.or.kr/api/company.json) | 기업 개황 확인 | `crtfc_key`, `corp_code` | 업종코드, 설립일, 결산월, 전화·팩스 등 |
| 3 | [`list.json`](https://opendart.fss.or.kr/api/list.json) | 대상 보고서와 접수번호 확인 | `crtfc_key`, 선택 `corp_code`, `bgn_de`, `end_de`, `last_reprt_at` | 보고서명, 제출일, `rcept_no`, 정정 여부 |
| 4 | [`fnlttSinglAcnt.json`](https://opendart.fss.or.kr/api/fnlttSinglAcnt.json) | 재무제표 요약의 핵심 | `crtfc_key`, `corp_code`, `bsns_year`, `reprt_code`, `fs_div` | 재무상태표·손익계산서 주요 계정과 금액 |
| 5 | [`fnlttSinglIndx.json`](https://opendart.fss.or.kr/api/fnlttSinglIndx.json) | 수익성·안정성·성장성·활동성 요약 | `crtfc_key`, `corp_code`, `bsns_year`, `reprt_code`, `idx_cl_code` | 지표명·지표코드·지표값 |
| 6 | [`fnlttSinglAcntAll.json`](https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json) | 요약 수치의 상세 근거와 누락 계정 보완 | `crtfc_key`, `corp_code`, `bsns_year`, `reprt_code`, `fs_div` | XBRL 전체 계정, 전기·전전기 및 누적 금액 |
| 7 | [`document.json`](https://opendart.fss.or.kr/api/document.json) | 원문 공시 확인 | `crtfc_key`, `rcept_no` | 원문 문서 파일. 숫자·주석·정정 여부 검증 |

### 필수 API를 이용한 보고서 데이터 구성

| 보고서 항목 | 우선 사용 API | 보완 API |
|---|---|---|
| 기업 개요 | `company` | `corpCode` |
| 보고서 기준일·제출일 | `list` | `document` |
| 자산·부채·자본 | `fnlttSinglAcnt` | `fnlttSinglAcntAll` |
| 매출·영업이익·당기순이익 | `fnlttSinglAcnt` | `fnlttSinglAcntAll` |
| 현금흐름 | `fnlttSinglAcntAll` | 원문 `document` |
| 수익성·안정성·성장성·활동성 | `fnlttSinglIndx` | 주요계정으로 교차 확인 |
| 수치의 출처·주석 | `document` | `list`의 `rcept_no` |

## 3. 비교·분석용 API

필수 API로 한 회사를 요약한 뒤, 아래 API를 선택적으로 추가하면 경쟁사 비교나 산업 내 위치 분석을 할 수 있다.

| API | 사용 목적 | 주요 주의사항 |
|---|---|---|
| [`fnlttMultiAcnt.json`](https://opendart.fss.or.kr/api/fnlttMultiAcnt.json) | 여러 회사의 주요계정 비교 | 동일 연도·동일 보고서·동일 재무제표 구분으로 맞춘다 |
| `fnlttMultiIndx.json` | 여러 회사의 주요 재무지표 비교 | 동일 지표 분류와 기준일을 사용한다 |
| [`xbrlTaxonomy.json`](https://opendart.fss.or.kr/api/xbrlTaxonomy.json) | 계정 ID·계정명·데이터 유형 기준 확인 | 회사별 표시명 차이를 정규화할 때 사용한다 |
| [`fnlttXbrl.xml`](https://opendart.fss.or.kr/api/fnlttXbrl.xml) | XBRL 원본 파일 확보 | 보고서 원문과 함께 보관하고 파일 응답을 별도 처리한다 |

## 4. 선택적 사업·지배구조 보강 API

재무제표 자체의 요약에는 필수는 아니지만, 재무 수치를 해석하는 경영·자본 맥락이 필요할 때 사용한다.

| API | 보강 가능한 내용 | 보고서 사용 예 |
|---|---|---|
| `stockTotqySttus.json` | 주식의 총수 현황 | 발행주식수·자본구조 설명 |
| `exctvSttus.json` | 임원 현황 | 경영진·지배구조 개요 |
| `mrhlSttus.json` | 소액주주 현황 | 주주 분산도 설명 |
| `majorstock.json` | 대량보유 상황보고 | 주요 주주 및 보유 변동 확인 |
| `elestock.json` | 임원·주요주주 소유보고 | 내부자 보유 현황 확인 |
| `indvdlByPayV2.json` | 개인별 보수 지급 금액 | 보수·주식보상 관련 부록 |

이 API들은 손익·재무상태·현금흐름의 원천 수치를 대체하지 않는다. 재무제표 요약을 먼저 확정한 뒤 해석용 부록으로 결합한다.

## 5. 공통 요청 파라미터

| 파라미터 | 의미 | 적용 범위 |
|---|---|---|
| `crtfc_key` | 40자리 OpenDART 인증키 | 모든 API |
| `corp_code` | DART 기업 고유번호 8자리 | 기업 단위 API |
| `bsns_year` | 사업연도 4자리 | 정기보고서 API |
| `reprt_code` | 1분기 `11013`, 반기 `11012`, 3분기 `11014`, 사업 `11011` | 정기보고서 API |
| `fs_div` | 별도 `OFS`, 연결 `CFS` | 재무제표 API |
| `idx_cl_code` | 수익성 `M210000`, 안정성 `M220000`, 성장성 `M230000`, 활동성 `M240000` | 주요 재무지표 API |
| `rcept_no` | 공시 접수번호 14자리 | 원문·공시 근거 조회 |

## 6. 권장 수집 절차

1. `corpCode.xml`에서 기업명 또는 종목코드에 대응하는 `corp_code`를 찾는다.
2. `company.json`으로 기업 개황과 결산월을 확인한다.
3. `list.json`에서 대상 사업연도·보고서의 `rcept_no`, 제출일, 정정 여부를 확인한다.
4. `fnlttSinglAcnt.json`으로 재무상태표·손익계산서 주요 계정을 수집한다.
5. `fnlttSinglIndx.json`으로 공식 제공 재무지표를 수집한다.
6. `fnlttSinglAcntAll.json`으로 현금흐름·세부계정·전기 비교값을 보완한다.
7. `document.json` 또는 `fnlttXbrl.xml`로 숫자와 주석의 원문 근거를 확인한다.
8. 경쟁사 비교가 필요할 때만 `fnlttMultiAcnt`·`fnlttMultiIndx`를 추가한다.

## 7. 보고서 작성 시 데이터 규칙

- `corp_code`, `stock_code`, `rcept_no`를 서로 대체하지 않는다.
- `bsns_year`, `reprt_code`, `fs_div`가 같은 데이터끼리만 기간·연결 기준을 비교한다.
- API의 금액 필드는 표시 문자열일 수 있으므로 쉼표, 빈 문자열, 음수 표기를 확인한 뒤 수치화한다.
- 계정명만으로 합산하지 말고 `account_id`, `sj_div`, `fs_div`, 기준일을 함께 저장한다.
- `fnlttSinglIndx`의 지표값은 원천 계정에서 재계산한 값과 다를 수 있으므로 공식 지표와 자체 계산값을 구분한다.
- `status`가 `000`인지 확인하고, `013`(조회 데이터 없음)과 오류 응답을 구분한다.
- 정정공시가 있으면 최신 제출본만 임의로 선택하지 말고 `list`의 보고서명·접수번호·정정 여부를 기록한다.
- 최종 보고서에는 API 응답 기준일, 사업연도, 보고서 종류, 연결·별도 구분, `rcept_no`를 출처로 남긴다.

## 8. 공식 출처

- [OpenDART 개발가이드](https://opendart.fss.or.kr/guide/main.do)
- [공시정보 API 목록](https://opendart.fss.or.kr/guide/main.do?apiGrpCd=DE001)
- [정기보고서 주요정보 API 목록](https://opendart.fss.or.kr/guide/main.do?apiGrpCd=DS002)
- [정기보고서 재무정보 API 목록](https://opendart.fss.or.kr/guide/main.do?apiGrpCd=DS003)
- [고유번호 API 상세](https://opendart.fss.or.kr/guide/detail.do?apiGrpCd=DE001&apiId=AE00004)
- [단일회사 전체 재무제표 API 상세](https://opendart.fss.or.kr/guide/detail.do?apiGrpCd=DE003&apiId=AE00036)
- [단일회사 주요 재무지표 API 상세](https://opendart.fss.or.kr/guide/detail.do?apiGrpCd=DS003&apiId=2022001)
- [공시 검색 API 상세](https://opendart.fss.or.kr/guide/detail.do?apiGrpCd=DE001&apiId=AE00001)
