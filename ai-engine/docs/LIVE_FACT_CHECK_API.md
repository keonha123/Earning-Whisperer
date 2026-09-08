# Live Fact-Check API — 실시간 어닝콜 팩트체크 엔드포인트

작성 2026-09-09. 대상 독자: ai-engine 담당자, 백엔드 담당자.

## 왜 만들었나

`LiveNewsFactCheckService` 는 이미 구현되어 있었으나 **어떤 라우터에도 연결되어 있지
않아 HTTP 로 호출할 수 없는 상태**였습니다 (`main.py` 가 `app.state` 에 인스턴스만
생성). 어닝콜 시연에서 백엔드가 이 서비스를 호출해야 하므로 라우터를 추가했습니다.

**서비스 로직은 한 줄도 고치지 않았습니다.** 추가한 것은 라우터 파일 1개, DI 헬퍼 1개,
라우터 등록 2줄, 테스트 파일 1개가 전부입니다.

## 기존 `/v1/engine/fact-check` 와의 차이

두 엔드포인트는 이름이 비슷하지만 완전히 다른 물건입니다. 혼동하면 시연이 망가집니다.

| | `/v1/engine/fact-check` (기존) | `/v1/engine/live-fact-check/sentence` (신규) |
| :-- | :-- | :-- |
| 판정 주체 | 키워드/임베딩 유사도 휴리스틱 | **Gemini 2패스** (주장 추출 → 근거 대조) |
| 상태 | 무상태 단발 호출 | ticker 별 **3문장 버퍼** 유지 |
| 입력 | 완성된 `claim` 문자열 | 어닝콜 **문장 1개**씩 |
| 근거 | 요청에 `documents` 인라인 주입 가능 | retriever 에 **사전 적재된 문서만** 검색 |
| 판정값 | `SUPPORTED` / `UNVERIFIED` | `SUPPORTED` / `CONTRADICTED` / `INSUFFICIENT_EVIDENCE` |
| 한국어 설명 | 없음 | `explanation_ko` 제공 |

기존 엔드포인트의 한계를 실제로 확인했습니다. 근거 문서가 "OCI 매출 42% 성장"인
상태에서 "52% 성장했다"는 주장을 넣으면 **`SUPPORTED` (confidence 0.90) 를 반환**합니다.
단어가 겹치는지만 보기 때문에 숫자 모순을 잡지 못합니다. 신규 엔드포인트는 같은
입력에 `CONTRADICTED` (confidence 0.85) 와 근거 인용을 돌려줍니다.

## 엔드포인트

```
POST /v1/engine/live-fact-check/sentence
```

### 요청 (`LiveFactCheckSentenceRequest`)

| 필드 | 타입 | 필수 | 설명 |
| :-- | :-- | :--: | :-- |
| `ticker` | String | Y | 종목 심볼. 내부에서 대문자로 정규화 |
| `sentence` | String | Y | 확정된 어닝콜 문장 1개 (빈 문자열 불가) |
| `sentence_sequence` | Integer (≥0) | Y | 세션 내 문장 순번. 단조 증가 |
| `sentence_timestamp` | Integer (>0) | Y | Unix Epoch **Second**. 근거 검색 기준 시점 |
| `is_session_end` | Boolean | N | 어닝콜 종료 신호 (기본 `false`) |

### 응답 (`LiveFactCheckBatchResponse`)

**HTTP 상태는 성공/실패 흐름 모두 200 입니다.** 요청 스키마 위반만 422 입니다.
호출자는 반드시 본문 `status` 를 분기해야 합니다.

| `status` | 언제 | 호출자가 할 일 |
| :-- | :-- | :-- |
| `BUFFERING` | 3문장이 아직 안 모임 (1~2번째 문장) | 아무것도 안 함. 정상 |
| `COMPLETED` | 3문장이 모여 검증 완료 | `claims[]` 를 화면으로 발행 |
| `REJECTED` | 중복/역행 시퀀스 | 로그만. 재전송하지 말 것 |
| `DISCARDED` | 3문장 미만인 채 세션 종료 | 마지막 자투리 문장 버려짐. 정상 |

주요 필드:

| 필드 | 설명 |
| :-- | :-- |
| `claims[]` | 검증된 주장 목록. `BUFFERING` 일 때는 빈 배열 |
| `excluded_count` | 검증 불가로 걸러진 주장 수 ("고객을 소중히 생각합니다" 같은 것) |
| `extraction_llm_used` / `verification_llm_used` | 각 LLM 패스 실행 여부. 폴백 판단에 사용 |
| `warnings[]` | `sequence_gap`, `claim_retrieval_failed` 등 진단용 |

`claims[]` 각 항목:

| 필드 | 설명 |
| :-- | :-- |
| `claim_id` | `{TICKER}:{시작seq}-{끝seq}:c{n}` 형식 |
| `sentence_index` | 배치 내 문장 위치 (0~2) |
| `source_text` | 원문에서 잘라낸 구간 |
| `claim` | 정규화된 주장 |
| `claim_type` | `numeric_fact` / `current_fact` / `historical_fact` / `event_fact` |
| `verdict` | `SUPPORTED` / `CONTRADICTED` / `INSUFFICIENT_EVIDENCE` |
| `confidence` | 0.0~1.0 |
| `explanation_ko` | 한국어 판정 설명. **UI 에 그대로 노출 가능** |
| `reason_code` | `supported_by_news` / `contradicted_by_news` / `insufficient_relevance` / `evidence_not_specific` / `retrieval_failed` / `llm_failed` / `invalid_llm_response` |
| `evidence[]` | `doc_id`, `title`, `snippet`, `url`, `source`, `published_at`, `relevance_score` |
| `retrieved_count` / `accepted_count` | 검색된 근거 수 / 게이트 통과 수 |

## 호출자가 반드시 알아야 할 세 가지

### 1. 3문장마다 한 번만 결과가 나온다

버퍼가 ticker 별로 유지됩니다. 문장 3개를 넣어야 비로소 LLM 이 돌고 `COMPLETED` 가
나옵니다. 어닝콜 UI 에서 "몇 문장마다 팩트체크 카드가 튀어나오는" 리듬이 여기서
결정됩니다. `sentence_sequence=0` 을 다시 보내면 해당 ticker 버퍼가 초기화됩니다.

### 2. `sentence_timestamp` 가 근거 검색 창을 결정한다 — 가장 흔한 함정

근거 검색은 `sentence_timestamp` 를 기준으로 `FACT_CHECK_NEWS_LOOKBACK_DAYS` 만큼
과거를 봅니다. 타임스탬프가 뉴스 발행 시각과 동떨어지면 **적재된 근거가 있어도 검색
결과가 0건**이 되고, 전부 `INSUFFICIENT_EVIDENCE` 로 떨어집니다.

검증 중 실제로 겪었습니다. 타임스탬프를 임의값(`1900000000`, 2030년)으로 넣었더니
`retrieved_count: 0` 이 나왔고, 현재 시각으로 바꾸자 같은 요청이 정상 판정되었습니다.
**시연 스크립트를 재생할 때는 실제 현재 시각을 넣어야 합니다.**

### 3. 근거가 없으면 아무 판정도 안 나온다

`_gate_evidence` 문턱이 높습니다. 검색된 문서가 강한 관련성 점수를 넘거나, **서로 다른
매체 2곳 이상**에서 나와야 통과합니다. 못 넘기면 근거를 전부 버리고
`INSUFFICIENT_EVIDENCE` 를 냅니다.

즉 **시연 전에 해당 종목의 뉴스·보도자료를 retriever 에 적재하는 작업이 필수**입니다.
적재 경로는 이미 있습니다.

```
POST /api/v1/integration/collector/news
{"items":[{"provider":"reuters","provider_id":"...","ticker":"ORCL",
           "headline":"...","content":"...","url":"...","source":"Reuters",
           "published_at":"2026-09-05T12:00:00Z"}]}
```

`source` 필드가 매체 구분에 쓰이므로 서로 다른 매체 2곳 이상을 넣어야 게이트를
통과하기 쉽습니다.

## 실측 동작

근거 2건(Reuters/Bloomberg, "OCI 매출 42% 성장")을 적재한 뒤 문장 3개를 순서대로 넣은
결과입니다. Gemini 실호출이며 3문장 배치 처리에 약 5초가 걸렸습니다.

```
1: "Oracle Cloud Infrastructure revenue grew 52 percent ..."  → BUFFERING (1)
2: "We remain deeply committed to our customers and partners." → BUFFERING (2)
3: "Capital expenditures will exceed 25 billion dollars ..."   → COMPLETED

claims[0] CONTRADICTED (0.85)
  "제시된 뉴스 증거에 따르면 Oracle Cloud Infrastructure의 매출 성장률은
   52%가 아닌 42%입니다."
  근거: Reuters "Oracle cloud infrastructure revenue rises 42%" (1.00)
        Bloomberg "Oracle OCI growth cools to 42% as capex climbs" (0.52)

claims[1] SUPPORTED (0.85)
  "뉴스 증거에서 오라클 경영진이 자본 지출을 250억 달러 이상으로
   전망했다고 명시하고 있습니다."
  근거: Bloomberg "Oracle OCI growth cools to 42% as capex climbs" (1.00)

excluded_count: 1   ← "고객과 파트너를 소중히" 문장은 검증 대상에서 제외됨
```

2번 문장이 걸러진 것에 주목하세요. 검증 가능한 사실 주장만 남기는 동작이 의도대로
작동합니다.

## 판정값과 UI 표기

엔진의 3종 판정을 계약의 단일 진실 공급원으로 삼습니다. 클라이언트는 아래 표기를
사용합니다. 표기는 사용자가 읽기 좋은 한국어를 우선했습니다.

| `verdict` | UI 표기 | 의미 |
| :-- | :-- | :-- |
| `SUPPORTED` | **사실 확인** | 뉴스 근거와 일치 |
| `CONTRADICTED` | **사실과 다름** | 뉴스 근거와 배치 |
| `INSUFFICIENT_EVIDENCE` | **근거 부족** | 검증할 근거를 찾지 못함 |

시연 기획 초기 목업에 있던 `EXAGGERATED`(과장) / `SHIFTED`(논점 이동) 는 엔진에
없으므로 **채택하지 않습니다.** 다만 위 실측에서 보듯 "52% 라고 말했지만 실제는 42%"
같은 과장 사례는 `CONTRADICTED` 로 잡히고 `explanation_ko` 가 그 차이를 문장으로
설명하므로, 시연에서 전달하려던 메시지는 그대로 살아 있습니다.

## 성능·비용

3문장 배치당 Gemini 호출 2회(추출 1 + 검증 1)입니다. 근거가 하나도 게이트를
통과하지 못하면 검증 패스를 건너뛰므로 1회입니다. 모델은
`GEMINI_PRIMARY_MODEL`(기본 `gemini-3.1-flash-lite`), `route_profile: economy`,
`temperature 0.1` 입니다. 20문장짜리 스크립트면 배치 약 7회 × 최대 2회 = 14회입니다.

관련 타임아웃 설정 (`config.py`):
`FACT_CHECK_EXTRACTION_TIMEOUT_SECONDS`, `FACT_CHECK_LLM_TIMEOUT_SECONDS`,
`FACT_CHECK_RETRIEVAL_TIMEOUT_SECONDS`, `FACT_CHECK_SENTENCE_BUFFER_TTL_SECONDS`.

## 인프라 요구사항

이 경로는 **Postgres·Redis·Qdrant 없이 동작합니다.** DB 를 죽은 주소로 지정하고
기동해도 `/health` 는 `ok` 이고 본 엔드포인트는 정상 응답합니다 (`/health/ready` 만
`degraded`). Postgres 는 이벤트 저장·회귀 리포트·컨트롤 플레인 전용이며 커넥션이
요청 시점에 lazy 로 열리기 때문입니다. `VECTOR_STORE_BACKEND` 기본값이 `memory` 라
Qdrant 도 불필요합니다.

주의: `memory` 백엔드는 프로세스 메모리에 근거를 담으므로 **재기동하면 적재한 뉴스가
사라집니다.** 시연 서버를 재시작했다면 뉴스 적재를 다시 해야 합니다.

## 변경 파일

| 파일 | 내용 |
| :-- | :-- |
| `api/routers/live_fact_check.py` | 신규. 엔드포인트 1개 |
| `api/dependencies.py` | `get_live_news_fact_check_service()` 추가 |
| `api/routers/__init__.py` | 라우터 등록 |
| `tests/test_live_fact_check_api.py` | 신규. 라우터 계층 테스트 6개 |
| `requirements.txt` | `pytest-asyncio` 추가 (아래 참조) |

### `pytest-asyncio` 에 대하여

`tests/test_live_news_fact_check_service.py` 등 async 테스트 18개가 전부 실패
상태였는데, 원인은 코드가 아니라 **`pytest-asyncio` 미설치**였습니다
("async def functions are not natively supported"). `requirements.txt` 에 추가했고,
설치 후 전체 스위트가 **195개 전부 통과**합니다.

```
uv pip install -r requirements.txt   # 또는 pip install pytest-asyncio
python -m pytest -q                  # 195 passed
```
