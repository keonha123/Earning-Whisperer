# Gemini 호출 실패 원인과 수정 — 2026-10-02

> 후속 검증 완료: `REMOTE-INTEGRATION-20261002.md` 우선 확인. 사용자의 새 실행 승인으로 실호출을 재개했다. 최종AI337/PDF21검사 통과, 실제Electron 번역·QA 확인. 추가로 구어 숫자/부호 동등성 검증과 전체 계층 대기 시간을 수정했다(번역12초, QA25초, backend30초, terminal35초). 아래 초기6/8/12초 설정과 승인거절 상태는 원인 분석 당시 기록이다.

## 확인된 원인

### 1. 실제 provider 503 과부하

`gemini-diagnosis-baseline2.provider.json`에서 동일 PDF capex 번역 호출이 **503 UNAVAILABLE**로 실패했다. provider 메시지는 해당 모델의 수요 급증을 명시한다. 모델은 `gemini-3.1-flash-lite`, SDK는 `google-genai 1.70.0`이다. 같은 키/모델로 직전 실행은 21개 검사와 provider 8회 호출이 모두 성공했으므로 키 부재·항상 잘못된 모델명으로 설명되는 실패가 아니다. 이번 기록에 401/403/429 오류는 없다.

Google도 503을 일시 과부하/서비스 불가로 설명하며 429/503에는 지수 백오프를 권장한다: [공식 문제 해결](https://ai.google.dev/gemini-api/docs/troubleshooting), [공식 API 오류](https://ai.google.dev/gemini-api/docs/api-errors).

### 2. 사용자 대기 제한과 SDK 호출 수명의 불일치

동일 baseline2 QA에서 후보 생성은 2.402초, 검증 호출은 **16.330초**였다. QA 전체 제한은 12초이므로 호출자는 먼저 timeout을 받았다. 기존 `asyncio.wait_for(asyncio.to_thread(...))`는 기다리는 coroutine만 취소하며 진행 중인 동기 SDK 네트워크 호출을 중단하지 않는다.

설치 SDK 소스 introspection 결과 `retry_args(None)`는 **1회만 시도**한다. `HttpRetryOptions`를 따로 제공할 때 적용되는 기본 5회와 혼동하면 안 된다. 기존 코드에는 명시적 transport timeout도 없었고 설정의 `GEMINI_MAX_RETRIES`는 실제 생성 재시도에 연결되지 않았다. backend 번역/QA HTTP read 제한은 16초라서 AI 제한만 30초로 늘리는 방안은 올바른 통합 수정이 아니다.

### 3. 동시 호출 취소 처리 오류

동일 요청을 모으는 기존 공유 Future에 follower가 직접 await했다. 한 follower 취소가 Future를 취소해 owner의 `set_result`에서 `InvalidStateError`를 일으켰다. owner 취소 시에는 Future를 완료하지 않고 map에서만 지워 기존 follower가 계속 대기했다. 표준 asyncio 재현과 신규 제품 회귀 테스트로 검증했다. 이 결함이 이전 단일 PDF 실행 실패를 일으켰다고 단정하지 않으며, 확인된 별도 결함으로 수정했다.

### 4. 진단을 가리던 fallback 처리

이전 PDF 작업에서 실패 fallback의 캐시 저장을 이미 수정했다. 이번에는 provider 장애와 근거 검증 실패를 구분했다. 기존에는 503도 generic fallback JSON을 거쳐 `qa_answer_not_verified`처럼 보일 수 있었다.

## 적용한 수정

- 요청당 전체 재시도 예산 기본 12초, 네트워크 시도당 최대 6초. 번역/QA는 호출자가 전달한 더 짧은 남은 예산을 사용한다. 기본 번역8초/QA12초는 유지했다.
- SDK 자체 시도는 1회로 명시하고 애플리케이션에서만 재시도한다. 408/429/500/502/503/504와 transport/timeout에만 최대 3회 재시도하되 남은 예산이 없으면 중단한다. 지수 백오프·지터·숫자형 Retry-After를 적용한다. 400/401/403/404는 반복하지 않는다.
- 같은 요청은 공유 Task로 처리하고 모든 caller는 shield를 통해 대기한다. 한 caller 취소가 다른 caller를 취소하거나 동일 provider 작업을 추가 실행하지 않는다. 실제 공유 작업이 끝나야 inflight 항목을 제거한다.
- 내부 fallback은 캐시하지 않는다. 생성되지 않은 fallback 토큰/비용은 0으로 표시한다. `error_code`, `attempts`를 보존하고 분석 metadata의 `generation.available`로 모델 결과 여부를 명시한다.
- 번역/QA provider 장애는 `translation_provider_http_503`, `qa_provider_http_503` 같은 코드로 제공하며 QA는 `model_unavailable`로 구분한다. 숫자·단위·정확한 인용·독립 검증 조건은 유지한다.
- analysis route가 선택한 `thinking_level`을 실제 SDK 설정에 전달한다. 기존에는 설정을 고르고도 전달하지 않았다.
- thinking 설정 호환성 재시도는 해당 400 오류에만 수행하고 이미 소비한 시간을 뺀다.

## 실제 검증에서 발견한 서버 deadline 제약

최초 수정본 실호출(`gemini-fixed-live1.provider.json`)은 HTTP timeout6초를 설정하자 **400 INVALID_ARGUMENT: minimum deadline 10s**로 실패했다. SDK가 timeout을 `X-Server-Timeout`으로 복사했기 때문이다. 해당 실패 기록도 보존했다.

SDK 소스의 `populate_server_timeout_header`는 명시된 `X-Server-Timeout`을 덮어쓰지 않는 것을 확인했다. 최종 코드는 서버 deadline을 최소10초로 명시하고, 로컬 HTTP timeout은 실제 남은 시도 예산으로 별도 설정한다. 관련 객체 설정 및 thinking 재시도의 남은 시간 회귀 테스트는 통과했다.

이 설정은 Google 서버 작업을 강제로 중단한다는 뜻이 아니다. HTTP timeout은 네트워크 phase별 제한이며, 외부 응답의 wall-clock 제한은 기존 `wait_for`가 담당한다. 이미 수행 중인 서버 작업은 로컬 timeout 이후에도 종료까지 시간이 걸릴 수 있다. 무제한 시간 확대 또는 모든 요청 성공 보장이 아니다.

## 검증 상태

| 검사 | 결과 |
|---|---|
| 수정 전 계측 baseline1 | PDF 21/21, SDK 8회 모두 성공 |
| 수정 전 계측 baseline2 | 실제 503 및 16.33초 verifier 지연 재현 |
| 최초 timeout 수정 실호출 | 서버 최소 deadline 제약으로 400; 수정 후 코드에 반영 |
| 최종 집중 회귀 | **52 passed** |
| 최종 전체 AI suite | **324 passed**, tokenizer deprecation warning1개, 30.03초 |
| 최종 수정본 실호출 | **실행 승인 거절로 미실행**. 재요청/우회하지 않음 |

따라서 **원인 진단 및 확인된 코드 결함 수정은 완료**, 최종 deadline 헤더 조합과 재시도의 실제 provider 복구 효과는 미확인이다. 최종 수정본으로 PDF 전체 경로를 반복 검증해야 실호출 복구 완료라고 판단할 수 있다. 기존 backend/terminal/Linux release 검증도 이 작업으로 대체되지 않는다. 커밋/push/실주문 없음.

재현: `tasks/validation/diagnose_gemini_pdf.py`에 원본 PDF, 기존 로컬 env 경로, 새로운 `--output` JSON 경로를 전달한다. 키와 프롬프트 본문은 provider 진단에 출력하지 않으며, provider 메시지의 키 패턴도 제거한다. 전체 진단 JSON/log는 gitignored 로컬 증거다.
