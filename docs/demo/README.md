# 시연 자료 보관소

이 디렉터리는 **프로그램이 렌더링하지 않는** 자료를 보관합니다. 코드가 아니라 참고
자료로 다룹니다.

## fixtures/

Trading Terminal 의 어닝콜 시연 UI 를 처음 만들 때 쓰던 목업 데이터입니다.
`trading-terminal/src/renderer/fixtures/` 에 있던 것을 그대로 옮겼습니다.

| 파일 | 원래 용도 |
| :-- | :-- |
| `sttTranscript.dev-mock.ts` | 어닝콜 스크립트 (Oracle Q4 FY2026 요약·번안) |
| `factCheck.dev-mock.ts` | 팩트체크 카드. 판정 4종 `CONFIRMED`/`EXAGGERATED`/`SHIFTED`/`UNVERIFIED` |
| `earningsEvaluation.dev-mock.ts` | 종합 평가 6축 점수 + 최종 신호 |
| `rippleEffect.dev-mock.ts` | 서플라이체인 파급효과 그래프 (노드·엣지) |
| `speakerProfile.dev-mock.ts` | 발화자 프로필 (재임기간·성향·가이던스 정확도) |
| `useEarningsDemoPlayback.ts` | 렌더러에서 타이머로 스크립트를 재생하던 훅 |
| `liveSession.dev-mock.ts` | 트레이딩룸 헤더·가격 폴백 (회사명·세션 라벨·경과시간·WPM·거래량) |

### 왜 옮겼나

시연 구조가 바뀌었습니다. 예전에는 **렌더러가 목업을 들고 타이머로 뿌리는** 방식이었고,
지금은 **백엔드가 스크립트를 실제 인입 경로로 재생하고 AI Engine 이 실제로 분석**합니다
(`docs/api-spec.md` Contract 7.8 / 4.6 / 9). 프론트가 가짜 데이터를 그리는 코드가 남아
있으면 실연동을 덮어버리므로 화면에서 걷어냈습니다.

데이터 구조 자체는 참고 가치가 있어 지우지 않았습니다.

### 지금 무엇이 실데이터이고 무엇이 아닌가

| 화면 요소 | 상태 |
| :-- | :-- |
| 실시간 스크립트 (`STTScriptPanel`) | **실데이터.** Contract 4.5 STOMP |
| 실시간 팩트체크 (`FactCheckPanel`) | **실데이터.** Contract 4.6 STOMP, Gemini 2패스 검증 |
| 회사명·현재가 | **실데이터.** `STOCK_GET_DETAIL` + `PRICES_UPDATE` |
| 세션 라벨·경과시간·WPM | 소스 없음. 가짜 값을 띄우지 않고 감춘다 |
| 종합 평가 (`EarningsEvaluationCard`) | 미연결. 컴포넌트와 타입만 남아 있음 |
| 최종 신호 (`FinalSignalCard`) | 미연결 |
| 파급효과 (`RippleEffectModal`) | 미연결. AI Engine `/v1/engine/impact-chain/{ticker}` 와 연결 가능 |
| 발화자 프로필 (`SpeakerProfileModal`) | 미연결. 생성 로직 없음 — 사전 조사 정보 성격 |

미연결 4종의 타입은 `trading-terminal/src/renderer/types/` 로 옮겨 두었습니다.
컴포넌트는 그대로 있으므로, 백엔드 발행 경로가 생기면 페이지에 다시 꽂으면 됩니다.

### 판정 어휘가 바뀐 점

목업의 4종 중 `EXAGGERATED`(과장)·`SHIFTED`(논점 이동)는 AI Engine 에 없습니다.
현재 판정은 `SUPPORTED` / `CONTRADICTED` / `INSUFFICIENT_EVIDENCE` 3종이며, 화면에는
각각 **사실 확인 / 사실과 다름 / 근거 부족** 으로 표기합니다.

과장 사례가 사라진 것은 아닙니다. "52% 성장했다" 는 발언에 "실제 42%" 라는 근거가
붙으면 `CONTRADICTED` 로 잡히고, `explanation_ko` 가 그 차이를 문장으로 설명합니다.
