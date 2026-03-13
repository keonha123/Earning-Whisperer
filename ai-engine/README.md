# 🧠 AI Engine (AI 추론 서버) 요구사항 정의서

## 1. 모듈의 역할 및 목표
이 모듈은 EarningWhisperer 프로젝트의 '두뇌' 역할을 담당합니다. 
데이터 수집 서버로부터 실시간 어닝콜 텍스트 조각(Chunk)을 전달받아, 최신 LLM(GPT-4o, Claude 3.5 등)을 활용해 금융 문맥을 분석합니다. 분석된 텍스트의 긍정/부정 뉘앙스를 수치화하고, 최종적으로 매수(BUY), 매도(SELL), 관망(HOLD) 시그널을 생성하여 백엔드(Java) 서버로 전달하는 것이 핵심 목표입니다.

## 2. 핵심 기능 요구사항 (Core Features)

### [Feature 1] 텍스트 수신용 REST API 구축
- 데이터 파이프라인(수집 서버)이 텍스트를 던져줄 수 있는 HTTP POST 엔드포인트를 엽니다. (예: `/api/v1/analyze`)
- **제약사항:** 데이터가 초 단위로 들어올 수 있으므로, 비동기(Asynchronous) 처리가 가능한 프레임워크를 사용하여 병목 현상을 방지해야 합니다.

### [Feature 2] 텍스트 감성 분석
시장 상황과 처리 속도 요구사항에 맞춰 두 가지 분석 방식을 모두 구현하고 스위칭할 수 있어야 합니다.

* **Track A: LLM API 기반 분석 (정확도 및 추론 초점)**
    - 수신된 텍스트를 최신 LLM(GPT-4o-mini, Claude 3.5 등)에 전송하여 깊이 있는 금융 감성을 분석합니다.
    - **핵심 로직:** LLM이 불필요한 텍스트를 생성하지 않고, 반드시 `docs/api-spec.md`에 정의된 JSON 규격(`signal`, `score`, `rationale`)으로만 답변하도록 시스템 프롬프트를 강력하게 통제합니다. (JSON Mode 필수)
    - **제약사항:** 과거 어닝콜 발언과 실제 주가 변동 데이터를 활용한 퓨샷(Few-shot) 프롬프팅으로 '실질적인 주가 영향력'을 평가해야 합니다.

* **Track B: 경량 NLP 모델 기반 분석 (초저지연 속도 초점)**
    - **FinBERT** 등 금융 도메인에 특화된 경량 오픈소스 NLP 모델을 자체 서버에 올려(Local Hosting) 추론을 수행합니다.
    - **핵심 로직:** 외부 API 네트워크 지연(I/O) 없이 텍스트 입력 즉시 수 밀리초(ms) 단위로 매수/매도 확률(Score)을 출력하는 초고속 파이프라인을 구축합니다.
    - **제약사항:** 과거 10년 치 어닝콜 스크립트와 해당 발언 직후 15분간의 실제 주가 등락 데이터를 매핑하여, 모델을 우리만의 기준으로 파인튜닝(Fine-tuning)해야 합니다.

### [Feature 3] Redis Pub/Sub 메시지 발행 (Publish)
- LLM으로부터 정상적으로 JSON 시그널을 받아내면, 이를 즉시 로컬 메모리 DB인 Redis의 `trading-signals` 채널에 발행(Publish)합니다.
- **제약사항:** DB(MySQL)에 직접 접근하여 쓰는 행위는 절대 금지합니다. 오직 Redis 채널에 던지고 통신을 종료합니다.

## 3. 입출력 명세 (I/O Specification)
- **Input:** 데이터 파이프라인 서버의 HTTP POST Request (`text_chunk`, `ticker` 등)
- **Output:** Redis `trading-signals` 채널에 JSON 스트링 Publish

## 4. 기술 스택 (Python)
- `FastAPI`: 빠르고 가벼운 비동기 REST API 서버 구축용
- `Uvicorn`: FastAPI 실행을 위한 ASGI 서버
- `openai` 또는 `anthropic`: LLM API 호출용 (팀 예산 및 성능에 따라 선택)
- `redis-py`: 비동기 Redis Pub/Sub 통신용
- `pydantic`: 데이터 검증 및 JSON 파싱용 (FastAPI 기본 내장)

## 5. 완료 기준 (Definition of Done - DoD)
이 모듈의 개발이 완료되었다고 평가받으려면 다음 테스트를 통과해야 합니다.
1. [ ] Postman으로 가짜 텍스트 청크를 POST 요청했을 때, 에러 없이 200 OK를 반환하는가?
2. [ ] LLM이 환각(Hallucination) 없이 무조건 지정된 포맷의 완벽한 JSON만 응답하는가?
3. [ ] 파이썬으로 가짜 Subscriber(구독자) 스크립트를 띄워놨을 때, AI 서버가 분석을 마치고 Redis로 던진 시그널이 1초 이내에 정상 수신되는가?