# 📢 EarningWhisperer API & Data Contract Specification

이 문서는 EarningWhisperer 프로젝트의 서비스 간 데이터 통신 규격을 정의합니다. 
모든 팀원은 본 명세에 정의된 필드명과 데이터 타입을 엄격하게 준수하여 시스템 간 결합 시 발생할 수 있는 파싱 에러를 원천 차단해야 합니다.

---

## 1. 전체 데이터 흐름도 (Data Pipeline)
1. **Data Pipeline** (Python) → `[HTTP POST 비동기]` → **AI Engine** (Python)
2. **AI Engine** (Python) → `[Redis Pub/Sub]` → **Backend** (Java Spring Boot)
3. **Backend** (Java) → `[HTTP REST]` → **증권사 모의투자 API**
4. **Backend** (Java) → `[WebSocket STOMP]` → **Frontend** (React/Next.js)

---

## 2. [Contract 1] Data Pipeline ➔ AI Engine
- **통신 방식:** HTTP POST (비동기)
- **엔드포인트:** `http://ai-engine:8000/api/v1/analyze` 
- **설명:** 오디오 스트림에서 추출 및 슬라이딩 윈도우(Overlapping) 처리가 완료된 약 10~15초 단위의 STT 텍스트 조각을 분석 서버로 전송합니다.

| 필드명 | 타입 | 필수 | 설명 |
| :--- | :--- | :---: | :--- |
| `ticker` | String | Y | 분석 대상 종목 심볼 (예: "NVDA") |
| `text_chunk` | String | Y | 슬라이딩 윈도우가 적용된 실시간 STT 텍스트 |
| `sequence` | Integer | Y | 텍스트 조각의 순차 번호 (0부터 1씩 증가, 순서 보장용) |
| `timestamp` | Long | Y | 오디오 캡처 기준 발생 시점 (Unix Epoch Second) |
| `is_final` | Boolean | Y | 해당 어닝콜 세션의 완전 종료 여부 |

**Request Body Example:**
```json
{
  "ticker": "NVDA",
  "text_chunk": "Our data center revenue grew by 400% compared to last year, driven by strong AI demand...",
  "sequence": 12,
  "timestamp": 1741827000,
  "is_final": false
}
```

---

## 3. [Contract 2] AI Engine ➔ Backend (Raw Signal)
- **통신 방식:** Redis Pub/Sub
- **Redis Channel:** `trading-signals`
- **설명:** AI 서버(Stateless)가 텍스트를 분석하여 도출한 **순수 감성 점수(Raw Score)**와 해설, 그리고 프론트엔드 중계를 위한 원문을 백엔드로 브로드캐스팅합니다.

| 필드명 | 타입 | 필수 | 설명 |
| :--- | :--- | :---: | :--- |
| `ticker` | String | Y | 분석 대상 종목 심볼 |
| `raw_score` | Double | Y | 감성 방향 및 강도 (-1.0[강한 매도] ~ +1.0[강한 매수]) |
| `rationale` | String | Y | LLM이 생성한 분석 근거 (UI 노출용) |
| `text_chunk` | String | Y | 분석에 사용된 원문 텍스트 (UI 실시간 타이핑용) |
| `timestamp` | Long | Y | 분석 완료 시점 (Unix Epoch Second) |

**Message Payload Example:**
```json
{
  "ticker": "NVDA",
  "raw_score": 0.85,
  "rationale": "CEO가 데이터 센터 매출의 400% 성장을 언급하며 매우 강한 긍정적 시그널이 감지되었습니다.",
  "text_chunk": "Our data center revenue grew by 400% compared to last year, driven by strong AI demand...",
  "timestamp": 1741827005
}
```

---

## 4. [Contract 3] Backend ➔ Frontend (Live Broadcasting)
- **통신 방식:** WebSocket (STOMP)
- **Topic:** `/topic/live/{ticker}` (예: `/topic/live/NVDA`)
- **설명:** 백엔드가 AI의 데이터와 자신이 계산한 `ema_score`, 그리고 최종 매매(체결) 결과를 조합하여 프론트엔드 라이브 트레이딩 룸으로 쏴주는 종합 데이터 팩입니다.

| 필드명 | 타입 | 필수 | 설명 |
| :--- | :--- | :---: | :--- |
| `text_chunk` | String | Y | 라이브 스크립트 렌더링용 원문 |
| `raw_score` | Double | Y | 텐션 미터기(게이지) 애니메이션용 점수 |
| `ema_score` | Double | Y | 백엔드가 계산한 추세선 차트용 점수 |
| `rationale` | String | Y | AI 시그널 피드용 텍스트 |
| `action` | String | Y | 백엔드 룰 엔진의 최종 결정 (`BUY`, `SELL`, `HOLD`) |
| `executed_qty` | Integer | N | 실제 체결(또는 주문)된 수량 (`action`이 HOLD면 0 또는 null) |

---

## 5. [Contract 4] Backend ➔ Broker API (참고용)
- **통신 방식:** HTTP REST (증권사 모의투자 망)
- **설명:** 백엔드 룰 엔진을 통과한 최종 주문 포맷입니다. (한국투자증권 모의투자 API 규격 참고)

| 필드명 | 타입 | 필수 | 설명 |
| :--- | :--- | :---: | :--- |
| `order_type` | String | Y | 주문 종류 (`00`: 지정가, `01`: 시장가) |
| `order_qty` | Integer | Y | 포트폴리오 룰 엔진을 거쳐 산출된 최종 수량 |
| `price` | Double | N | 주문 단가 (시장가 주문 시 0) |

---

## 6. 공통 개발 가이드라인 (Common Rules)
1. **에러 처리:** REST API 통신 시 에러가 발생하면 무조건 HTTP Status `4xx` 또는 `500`과 함께 `{"error": "에러 상세 원인"}` 형태의 JSON을 반환해야 합니다.
2. **타임존:** 모든 `timestamp`는 **UTC** 기준의 Unix Epoch Second를 사용합니다. 프론트엔드 수신 후 로컬 브라우저 시간으로 변환합니다.
3. **문자 인코딩:** 시스템의 모든 텍스트 통신은 `UTF-8`을 기본으로 합니다.
4. **Fallback (안전망):** 백엔드는 수신된 AI 시그널 파싱에 실패하거나 Redis 통신이 끊길 경우, 유저 보호를 위해 해당 종목의 진행 상태를 무조건 `HOLD(관망 및 매매 중지)`로 전환하고 관리자 로그를 남겨야 합니다.