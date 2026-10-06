# logothea-assistant

어닝콜 질의응답(#112) 서비스입니다. 개인투자자가 어닝콜을 들으며 던진 질문에, 질문 시점까지 나온 콜 내용과
그 시각 이전에 발행된 자료만 근거로 답하고 근거 위치를 함께 돌려줍니다.

## 위치

backend 가 유일한 외부 진입점입니다. 사용자 인증·하루 한도·질문 시점 확정은 backend 가 하고, 이 서비스는
`127.0.0.1:8100` 에서 backend 의 요청만 받습니다. 근거는 backend 내부 API(콜 세그먼트·실적 추정치·용어 사전)와
ai-engine 검색 API(시점 조건 뉴스·직전 콜 문장)에서 읽습니다(`docs/api-spec.md` 10장).

ai-engine 과 분리한 이유는 부하 형태가 달라서입니다. ai-engine 은 콜마다 한 번 계산해 모든 사용자에게 나눠 주고,
이 서비스는 사용자 질문마다 LLM 을 부릅니다. 같은 프로세스에 두면 질문이 몰릴 때 실시간 분석이 늦어집니다.

## 처리 순서 (1단계 고정 RAG)

1. 분류: 명시적 매매 질문은 규칙으로, 나머지는 LLM 구조화 출력으로 분류합니다. 매매·주가 예측·범위 밖 질문은 생성 없이 정해진 문구로 답합니다.
2. 근거 수집: 세그먼트·실적 추정치·직전 콜 문장은 분류와 동시에, 뉴스는 분류가 만든 검색어로 찾습니다. 정보원마다 3초 안에 오지 않으면 빼고 진행합니다.
3. 생성: 근거마다 `[S12]`(세그먼트), `[N3]`(뉴스), `[P2]`(직전 콜 문장), `[E1]`(실적 추정치) 표시를 붙여 모델에 넣고, 답 문장에도 같은 표시를 달게 합니다.
4. 인용 검증: 답에 쓴 표시가 실제 근거인지, 인용한 문장의 수치가 원문에 있는지 코드로 확인합니다.

## 구조

| 파일 | 역할 |
|---|---|
| `assistant/app.py` | `POST /v1/assistant/ask`(SSE), 내부 비밀 확인 |
| `assistant/pipeline.py` | 단계 조립 |
| `assistant/classifier.py`, `assistant/rules.py` | 질문 분류 |
| `assistant/context.py`, `assistant/clients.py` | 근거 수집 |
| `assistant/prompts.py`, `assistant/citations.py` | 생성 프롬프트, 인용 검증 |
| `assistant/llm.py`, `assistant/openai_client.py` | LLM 인터페이스와 OpenAI 어댑터 |

## 실행

환경변수는 `OPENAI_API_KEY`, `INTERNAL_SECRET`(backend 와 같은 값), `BACKEND_BASE_URL`, `AI_ENGINE_BASE_URL` 입니다.
`logothea-assistant/.env` 에 두어도 됩니다.

    python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
    .venv/bin/uvicorn assistant.main:app --host 127.0.0.1 --port 8100

테스트는 실제 OpenAI·backend·ai-engine 을 부르지 않습니다.

    .venv/bin/python -m pytest -q
