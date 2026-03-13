# 📢 EarningWhisperer API & Data Contract Specification

이 문서는 EarningWhisperer 프로젝트의 서비스 간 데이터 통신 규격을 정의합니다. 
모든 팀원은 본 명세에 정의된 필드명과 데이터 타입을 엄격하게 준수하여 파싱 에러를 방지해야 합니다.

---

## 1. 전체 데이터 흐름도 (Data Pipeline)
1. **Data Pipeline (Python)** → `[HTTP POST]` → **AI Engine (Python)**
2. **AI Engine (Python)** → `[Redis Pub/Sub]` → **Backend (Java Spring Boot)**
3. **Backend (Java)** → `[HTTP REST]` → **증권사 API**

---

## 2. [Pipeline 1] Data Pipeline ➔ AI Engine
- **통신 방식:** HTTP POST
- **엔드포인트:** `http://ai-engine:8000/api/v1/analyze` (임시)
- **설명:** 실시간 오디오 스트림에서 추출한 10초 단위의 STT 텍스트 조각(Chunk)을 분석 서버로 전송합니다.

| 필드명 | 타입 | 필수 | 설명 |
| :--- | :--- | :---: | :--- |
| `ticker` | String | Y | 분석 대상 종목 심볼 (예: "NVDA", "AAPL") |
| `text_chunk` | String | Y | 10초 분량의 실시간 STT 텍스트 데이터 |
| `sequence` | Integer | Y | 텍스트 조각의 순차 번호 (0부터 1씩 증가, 순서 보장용) |
| `is_final` | Boolean | Y | 해당 어닝콜 세션의 완전 종료 여부 |

**Request Body Example:**
{
  "ticker": "NVDA",
  "text_chunk": "Our data center revenue grew by 400% compared to last year, driven by strong AI demand...",
  "sequence": 12,
  "is_final": false
}


---

## 3. [Pipeline 2] AI Engine ➔ Backend (Core Signal)
- **통신 방식:** Redis Pub/Sub
- **Redis Channel:** `trading-signals`
- **설명:** AI 서버가 텍스트 문맥을 분석하여 도출한 **최종 매매 시그널**을 자바 백엔드 엔진으로 브로드캐스팅합니다. 백엔드는 이 채널을 구독(Subscribe)하여 실시간으로 주문을 생성합니다.

| 필드명 | 타입 | 필수 | 설명 |
| :--- | :--- | :---: | :--- |
| `ticker` | String | Y | 분석 대상 종목 심볼 (예: "NVDA") |
| `signal` | String | Y | 매매 방향 결정 (무조건 `BUY`, `SELL`, `HOLD` 중 택 1) |
| `score` | Double | Y | 시그널 강도 및 모델의 확신도 (0.0 ~ 1.0) |
| `rationale` | String | Y | AI 분석 근거 요약 (사용자 프론트엔드 UI 노출용 텍스트) |
| `timestamp` | Long | Y | 분석 완료 및 시그널 발행 시점 (Unix Epoch Second) |

**Message Payload Example:**
{
  "ticker": "NVDA",
  "signal": "BUY",
  "score": 0.85,
  "rationale": "CEO가 다음 분기 가이던스를 시장 예상치보다 15% 상향 조정한다고 발표했습니다.",
  "timestamp": 1741827000
}


---

## 4. [Contract 3] Backend ➔ Broker API (참고용)
- **통신 방식:** HTTP REST (외부 망 통신)
- **설명:** 백엔드에서 AI 시그널과 사용자의 잔고를 조합하여 실제 증권사로 전송할 내부 주문 포맷입니다. (한국투자증권 API 등 모의투자 기준)

| 필드명 | 타입 | 필수 | 설명 |
| :--- | :--- | :---: | :--- |
| `order_type` | String | Y | 주문 종류 (`00`: 지정가, `01`: 시장가) |
| `order_qty` | Integer | Y | 포트폴리오 룰 엔진을 거쳐 산출된 최종 매수/매도 수량 |
| `price` | Double | N | 주문 단가 (시장가 주문 시 0으로 세팅) |
| `strategy_id` | String | Y | 어떤 전략/모델(LLM 등)에 의해 발생한 주문인지 추적하기 위한 ID |


---

## 5. 공통 개발 가이드라인 (Common Rules)
1. **에러 처리:** REST API 통신 시 에러가 발생하면 무조건 HTTP Status `500` (또는 적절한 4xx)과 함께 `{"error": "에러 상세 원인"}` 형태의 JSON을 반환해야 합니다.
2. **타임존:** 모든 `timestamp`는 **UTC** 기준의 Unix Epoch Second를 사용합니다. (프론트엔드에서 로컬 시간으로 변환하여 표기)
3. **문자 인코딩:** 시스템의 모든 텍스트 통신은 `UTF-8`을 기본으로 합니다.
4. **Fallback (안전망):** 백엔드는 수신된 시그널의 `score` 범위를 벗어나거나 파싱 에러가 발생하면, 해당 턴을 무조건 `HOLD(관망)`로 처리하고 관리자 로그를 남겨야 합니다.