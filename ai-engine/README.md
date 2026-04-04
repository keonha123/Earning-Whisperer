# 🧠 AI Engine (AI 추론 서버) 요구사항 정의서

## 1. 모듈의 역할 및 목표
이 모듈은 EarningWhisperer 프로젝트의 '두뇌' 역할을 담당합니다. 
단순한 감성 분석을 넘어, **실시간 알고리즘 매매를 위한 '초저지연(Low Latency) 속도'**와 **유저를 납득시키기 위한 '설명력'**을 동시에 달성하는 **하이브리드 AI 아키텍처**를 구축하는 것이 핵심 목표입니다. 
데이터 파이프라인으로부터 텍스트 청크를 받아 매수/매도 시그널의 강도(Score)와 그 논리적 근거(Rationale)를 생성해 백엔드(Java) 서버로 전달합니다.

## 2. 핵심 기능 요구사항 (Core Features)

### [Feature 1] 슬라이딩 윈도우(Sliding Window) 기반 텍스트 수신 API
- 데이터 파이프라인(수집 서버)이 10~20초 단위의 텍스트를 던져줄 수 있는 비동기 HTTP POST 엔드포인트를 엽니다. (`/api/v1/analyze`)
- **컨텍스트 단절 방지:** 텍스트가 잘릴 때 발생하는 '문맥 왜곡'을 막기 위해, 수집 서버 또는 AI 엔진 단에서 이전 텍스트 청크와 현재 청크가 일부 겹치도록(Overlapping) 슬라이딩 윈도우 기법을 적용하여 입력받습니다.

### [Feature 2] 초고속 감성 스코어링 엔진 (FinBERT) - 속도/크기 담당
- 텍스트 입력 즉시 수 밀리초(ms) 단위로 방향성(+/-)과 강도(Magnitude)를 포함한 감성 점수(`raw_score`: -1.0 ~ +1.0)를 출력합니다.
- **제약사항 (라벨링 방식):** 모델 파인튜닝 시 주가 등락 매핑(노이즈 발생)을 금지합니다. 고성능 LLM(GPT-4 등)을 Teacher 모델로 사용하여 과거 어닝콜 스크립트의 감성을 정량화한 후, 이를 FinBERT(Student)에 학습시키는 **'Teacher-Student 라벨링'** 방식을 채택합니다.
- *참고: 이 스코어를 바탕으로 시계열 누적(EMA)을 계산하고 최종 매매(BUY/SELL)를 결정하는 비즈니스 로직은 Java 백엔드에서 수행합니다.*

### [Feature 3] 대시보드 해설 엔진 (LLM) - 설명력 담당
스코어링 엔진(NLP)이 내린 결론(방향성)을 바탕으로, 프론트엔드 대시보드에 띄워줄 유저 친화적인 해설(Rationale)을 비동기적으로 생성합니다.

* **Phase 1 (MVP 목표): 강제 주입식 프롬프팅 (Conditioned Prompting)**
  - NLP가 도출한 점수(예: `raw_score: -0.85`)를 LLM의 시스템 프롬프트에 '절대적인 팩트(강한 부정)'로 강제 주입합니다.
  - **역할:** LLM은 스스로 방향을 판단하지 않으며, 오직 **"왜 NLP가 이 문장에서 강한 부정 점수를 냈는가?"**를 정당화(Justify)하는 2~3문장의 브리핑만 작성하여 논리적 환각을 차단합니다.

* **Phase 2 (고도화 목표): LangChain + RAG 기반 통계 주입**
  - 단순 논리적 해설을 넘어 **'과거 데이터 기반의 증거'**를 제시합니다.
  - **역할:** 이전 어닝콜 발언 누적 요약 및 과거 데이터는 **외부 Vector DB(예: ChromaDB)**에 저장하여 관리합니다. LLM 해설 생성 시 Vector DB를 조회(RAG)하여, 현재 발언과 가장 유사했던 과거 맥락이나 데이터를 프롬프트에 포함시켜 설득력 높은 데이터 기반 해설을 생성합니다.

### [Feature 4] Redis Pub/Sub 메시지 발행 (Publish)
- NLP의 `raw_score`와 LLM의 `rationale`가 모두 포함된 JSON 객체가 완성되면, 이를 즉시 로컬 메모리 DB인 Redis의 `trading-signals` 채널에 발행(Publish)합니다.
- **제약사항:** RDBMS(MySQL 등)에 직접 접근하여 쓰는 행위는 절대 금지합니다. 오직 Redis 채널에 메시지를 던지고 통신을 종료하여 백엔드와의 결합도를 낮춥니다.

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