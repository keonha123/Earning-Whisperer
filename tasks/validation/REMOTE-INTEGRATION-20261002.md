# 최신 원격 통합 검증 — 2026-10-02

## 범위와 원격 기준

사용자가 최신 원격 검토·호환 수정·검증 후 커밋 및 push를 승인했다. 프로젝트에 설정된 원격은 `origin=https://github.com/keonha123/Earning-Whisperer.git` 하나다. 기존 명시 대상 `youngjun`을 유지하며 main이나 다른 기여자 브랜치는 갱신하지 않는다. 인증된 GitHub 계정은 james10419다.

`git fetch --all --prune` 후 main은98d4ab2, youngjun은a3ea806. 열린 PR139(backend glossary),141(AI translation),138(deployment docs)의 실제 내용 및 활성 원격 브랜치를 검토했다. 무관한 개인 저장소 전체를 변경하거나 모든 미병합 기능을 일괄 병합하는 작업은 아니다.

## 통합 내용

- 최신 main의 macOS 전용 창 드래그 변경5파일을 기존 수정본에 반영했다.
- PR139의 패키지 용어집/API/검증을 채택하고 원문에서 긴 표현 우선으로 용어를 골라 번역 요청에 전달한다. 기존 풍부한 정의를 제공하는 transcript glossary 및 QA 경로는 유지한다.
- PR141 요청 계약인 선택적 call_id, terms와 응답 terms_used를 기존 번역 서비스에 통합한다. 같은 URL의 중복 라우터는 등록하지 않는다. QA 및 live enrichment의 엄격한 identity 검증은 유지한다.
- Gemini 일시 오류에 제한시간 내 재시도, shared-task cancellation 격리, 실패 캐시 제외, provider 오류 분류를 유지한다. 번역에는 해당 원문에 필요한 용어만 보내며 숫자/단위/부정/용어 검증을 통과하지 못한 결과는 공개하지 않는다.
- dague의 대규모 capture/recovery 리팩터 전체는 채택하지 않았다. 기존 코드가 이미 import하는 누락 learning 모듈2개만 복원하고, 이를 숨겼던 gitignore를 루트 `/learning/`으로 한정했다. Linux Python3.10 UTC 호환성도 복구했다.
- 터미널 운영 의존성을 호환 가능한 보안 수정 버전으로 갱신하고 tar override를 적용했다. Electron41.10.7 및 CI Node22로 맞추고 네이티브 keytar rebuild,611개 테스트,타입 검사,빌드 통과. 운영 의존성 audit0, Electron 및 critical 경고0. 전체 audit은 개발/빌드 도구68건(7low/20moderate/41high)으로 실패하며 배포 도구 전체 보안 검증 완료로 해석하지 않는다.
- 실제 Electron에서 번역 미표시를 재현해 구어 숫자 `twenty percent`와 `20%`의 거짓 불일치를 수정했다. 영어0~999의 제한된 정규화로 같은 수치를 비교하되,20→30, minus20→20 또는5percentagepoints→5%는 계속 거부한다.
- PDF live5에서 QA 첫 호출 timeout+재시도 후 독립 검증 시간이0.4초밖에 남지 않는 것을 확인해 AIQA25/Backend30/Terminal35초로 맞췄다. live6에서는 두 QA가 성공했지만 번역8초가 재시도에0.5초만 남겨 번역 예산도12초로 맞췄다. 원문 전송은 비동기 번역과 분리되어 지연되지 않는다. SDK 시도당6초/각 생성 총12초 제한은 유지한다.

## 현재 검증 증거

| 대상 | 결과 |
|---|---|
| AI 전체 최종 |337passed, tokenizer deprecation warning1개,73.05초|
| Backend 최종 용어집 연결 포함 |530 tests,79suites, 실패/오류/skip0|
| Pipeline Linux |143 passed,17subtests passed|
| 실제 파일 STT |현재 take.py/cached distil-large-v3, 합성 WAV20%·5%·20% 정확, 정상 final 종료|
| PDF 실제 Gemini live1 |19/21; QA verifier read timeout, 실패 응답/원문 보존|
| PDF 실제 Gemini live2 |19/21; 두 번역 숫자/단위 검증 거부, SDK8호출 자체는 모두 성공|
| PDF 실제 Gemini live3 |21/21, 번역·검증형QA·리포트·분석·실제768차원 임베딩, 실행/발행 차단 확인|
| PDF 실제 Gemini live4 |19/21; 모델이 $를 USD로 바꿔 두 번역 거부; 통화 표기 보존 지침 보강|
| PDF 실제 Gemini live5 |19/21; QA재시도 후 verifier 예산0.4초, 전체 계층 QA 예산 수정|
| PDF 실제 Gemini live6 |20/21; 두QA성공, 번역8초 재시도 예산 부족 확인 후12초로 수정|
| 최종 PDF release |21/21 전체 통과, 최종 번역12초/QA25초 정책. `gemini-current-release` 증거|
| 인증된 실제 Backend |19082/H2/격리 Redis16379, signup/login 및 두 용어집 endpoint200|
| Electron 실제 전달 |Electron41.10.7에서 원문3·번역3·종료1 이벤트, 용어집,20% 답변과 정확한 인용 표시; 실제DOM8검사 통과|
| Terminal 최종 |612tests, 타입 검사, 빌드 통과; QA35초 요청 및 거절응답 보존 회귀 포함|

PDF의 앞선 실패를 성공으로 바꾸어 기록하지 않았다. 마지막21/21은 해당 실행의 성공이며 provider 과부하나 모델의 번역 거부가 앞으로 발생하지 않는다는 보장이 아니다. 영상/실마이크 및 실제 주문은 검증하지 않는다. STT 파일 테스트와 실제 화면 전달 검증은 별도 증거로 구분한다.

Electron 검증 도구의 첫 timestamp는 밀리초여서 backend epoch-seconds 계약에 어긋났다. fixture 수정 후 정상 답변을 확인했으며 제품 timestamp 의미를 바꾸지 않았다. 기존 private React Fiber 응답 추출기는 답변을 인식하지 못했으므로 그 helper 종료를 성공으로 세지 않고 실제 IPC/DOM과 스크린샷8검사를 사용했다. 마지막 대기시간 변경은 전체 회귀와 실제 PDF로 검증했으며, 앞서 성공한 Electron 화면 기록과 구분한다.

키/인증 토큰/로컬 런타임/원본 PDF/진단 JSON·로그는 커밋에서 제외한다. 알려진 키 형식 및 private key marker를 후보 텍스트 파일에서 검사했고 일치 항목은 없었다.

## 커밋 및 push

검증 게이트 통과 후 원격을 다시 확인한다. 기존 진행 중 병합(a3ea806+6a2cdfc)을 커밋하고 최신 main98d4ab2 ancestry를 정상 merge로 포함한다. 이미 최신 main의 코드가 적용돼 있으므로 두 번째 병합 전후 tree를 비교한다. 강제 push 없이 `HEAD:youngjun`만 갱신한다. 이 최초 보고서는 push 직전 준비되며 게시 결과는 아래에 추가한다.
