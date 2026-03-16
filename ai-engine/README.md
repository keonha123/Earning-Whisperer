# 🧠 AI Engine (AI 추론 서버) 요구사항 정의서

## 1. 모듈의 역할 및 목표
이 모듈은 EarningWhisperer 프로젝트의 '두뇌' 역할을 담당합니다. 
단순한 감성 분석을 넘어, **실시간 초단타 매매를 위한 '속도'**와 **유저를 납득시키기 위한 '설명력'**을 동시에 달성하는 **하이브리드 AI 아키텍처**를 구축하는 것이 핵심 목표입니다. 데이터 파이프라인으로부터 텍스트 청크를 받아 문맥의 흐름을 유지하며 매수/매도 시그널과 그 논리적 근거(Rationale)를 생성해 백엔드(Java) 서버로 전달합니다.

## 2. 핵심 기능 요구사항 (Core Features)

### [Feature 1] 상태 유지형(Stateful) 텍스트 수신 API
- 데이터 파이프라인(수집 서버)이 텍스트를 던져줄 수 있는 비동기 HTTP POST 엔드포인트를 엽니다. (`/api/v1/analyze`)
- **컨텍스트 메모리 관리 (중요):** 10초 단위 텍스트(Chunk)가 잘릴 때 발생하는 '문맥 단절'을 막기 위해, 이전까지의 맥락을 요약한 **'Memory(상태)'** 변수를 서버 메모리에 유지하고 새로운 청크와 함께 분석 모델에 넘겨야 합니다.

### [Feature 2] 초고속 매매 엔진 (자체 NLP / FinBERT) - 속도 담당
- 외부 API 네트워크 지연(I/O) 없이, 텍스트 입력 즉시 수 밀리초(ms) 단위로 매수/매도 확률(Score)을 출력하는 로컬 파이프라인입니다.
- **제약사항:** 모델 파인튜닝 시 사람이 긍정/부정을 라벨링하는 것이 아니라, **과거 어닝콜 발언 직후 15분간의 실제 주가 등락 데이터를 매핑**하여 '주가 하락/상승 확률' 자체를 학습시켜야 합니다.

### [Feature 3] 대시보드 해설 엔진 (LLM) - 설명력 담당
매매 엔진(NLP)이 0.1초 만에 내린 결론을 바탕으로, 프론트엔드 대시보드에 띄워줄 유저 친화적인 해설(Rationale)을 생성합니다. 한정된 리소스와 기한을 고려하여 두 단계(Phase)로 나누어 개발합니다.

* **Phase 1 (MVP 목표): 강제 주입식 프롬프팅 (Conditioned Prompting)**
  - 매매 엔진(NLP)이 도출한 결론(예: `Score: -0.8 매도`)을 LLM의 시스템 프롬프트에 '절대적인 팩트'로 강제 주입합니다.
  - **역할:** LLM은 스스로 판단하지 않으며, 오직 **"왜 NLP가 이 문장에서 매도 결론을 내렸는가?"**를 정당화(Justify)하는 2~3문장의 브리핑만 작성합니다. 이를 통해 AI의 환각(Hallucination)과 인지 부조화를 원천 차단합니다.

* **Phase 2 (고도화 목표): LangChain + RAG 기반 통계 주입**
  - 단순 논리적 해설을 넘어 **'과거 데이터 기반의 증거'**를 제시합니다.
  - **역할:** LangChain과 Vector DB를 연동하여, 현재 발언과 가장 유사했던 과거 어닝콜 발언 3개와 당시의 주가 등락 결과를 검색해 옵니다. 이를 프롬프트에 포함시켜 *"과거 3번의 동일한 발언 시 평균 4%의 주가 하락이 있었음"*과 같은 압도적인 신뢰감의 해설을 생성합니다.

### [Feature 4] Redis Pub/Sub 메시지 발행 (Publish)
- NLP의 Score와 LLM의 Rationale가 모두 포함된 JSON 시그널 객체가 완성되면, 이를 즉시 로컬 메모리 DB인 Redis의 `trading-signals` 채널에 발행(Publish)합니다.
- **제약사항:** DB(MySQL)에 직접 접근하여 쓰는 행위는 절대 금지합니다. 오직 Redis 채널에 던지고 통신을 종료하여 시스템 결합도를 낮춥니다.

## 3. 입출력 명세 (I/O Specification)
- **Input:** 데이터 파이프라인의 HTTP POST Request (`text_chunk`, `ticker`, `timestamp`)
- **내부 State:** `context_memory` (이전 발언 누적 요약)
- **Output:** Redis `trading-signals` 채널에 JSON 스트링 Publish

```json
{
  "ticker": "TSLA",
  "signal": "SELL",
  "score": -0.85,
  "rationale": "CEO가 연간 매출 목표 유지를 언급했으나, 핵심 동력인 신제품 출시가 2분기 지연됨에 따라 단기 마진 악화가 우려되어 매도 시그널이 발생했습니다."
}
```

## 4. 기술 스택 (Python)
- **Core API:** `FastAPI`, `Uvicorn`, `pydantic`
- **Trading Engine:** `transformers` (HuggingFace FinBERT 등), `torch`
- **Explanation Engine:** `openai` 또는 `anthropic` (Phase 1), `langchain`, `chromadb` (Phase 2)
- **Message Broker:** `redis-py`

## 5. 완료 기준 (Definition of Done - DoD)
이 모듈의 개발이 완료되었다고 평가받으려면 다음 테스트를 통과해야 합니다.
1. [ ] **속도 테스트:** 가짜 텍스트를 POST 요청했을 때, NLP 모델의 Score 도출이 100ms 이내에 완료되는가?
2. [ ] **무결성 테스트:** NLP가 '매도'를 외쳤을 때, LLM이 실수로 '긍정적입니다'라는 환각(Hallucination) 해설을 작성하지 않고 완벽하게 동기화되는가?
3. [ ] **통신 테스트:** 파이썬으로 가짜 Subscriber(구독자) 스크립트를 띄워놨을 때, AI 서버가 발행한 시그널이 Redis를 통해 정상 수신되는가?