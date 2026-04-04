# EarningWhisperer v3.3.0 구현 보고서

## 1. 요약

이번 고도화는 세 가지 축으로 진행했다.

- LLM 엔진을 `빠른 1차 판단 + 필요 시 self-consistency 재판단` 구조로 바꿨다.
- 실적 이벤트 전략을 `텍스트 감성`에서 `정량 이벤트 트레이딩 의사결정`으로 확장했다.
- 출력은 유지하면서 배치 처리, 다중 콜 분리, 백테스트, 운용 스타일 추천 기능을 추가했다.

핵심 원칙은 다음과 같다.

- `TradingSignalV3` 출력은 유지한다.
- HFT는 지양하고, 이벤트 드리븐 인트라데이와 스윙 중심으로 운용한다.
- 승률 50% 이상은 보장하지 않으며, 연구용 API와 게이트 조정으로 목표 관리한다.

## 2. 반영한 기능

### 2.1 토큰 예산과 모델 라우팅

추가 파일:

- `core/token_budgeter.py`

반영 내용:

- 프롬프트 문자 수를 보수적으로 토큰 수로 환산한다.
- 프롬프트 크기에 따라 `small`, `medium`, `large`로 구분한다.
- 작은 요청은 빠른 모델, 큰 요청은 기본 모델을 사용하도록 했다.
- 너무 큰 프롬프트는 자동 compact 처리한다.

운영 의미:

- 비용과 지연시간을 줄이면서도 긴 트랜스크립트에서 실패율을 낮춘다.

### 2.2 LLM 결과 일관성 강화

추가 파일:

- `core/llm_consistency.py`

반영 내용:

- confidence가 낮거나
- 방향성이 약하거나
- 완곡어법이 많거나
- 프롬프트가 큰 경우

에만 consensus 추론을 수행한다.

consensus 방식:

- 여러 샘플의 방향을 가중 투표한다.
- confidence와 magnitude를 같이 반영한다.
- 대표 rationale과 catalyst를 선택한다.
- `consensus_score`와 `disagreement_score`를 남긴다.

운영 의미:

- 단순히 항상 N회 호출하는 방식보다 빠르고 저렴하다.
- 애매한 콜일수록 재평가하므로 일관성이 올라간다.

### 2.3 다중 어닝콜/배치 처리

수정 파일:

- `api/analyze_router.py`
- `models/request_models.py`

반영 내용:

- `call_id`, `event_id`, `batch_id`를 추가했다.
- 세션 키를 `ticker`, `ticker:call_id`, `ticker:event_id`, `ticker:batch_id`로 분리한다.
- `POST /api/v1/analyze/batch`를 추가했다.
- 배치 동시성은 설정 상한 `analysis_batch_concurrency`로 제한한다.

운영 의미:

- 같은 티커라도 다른 분기 콜이나 다른 이벤트가 컨텍스트를 오염시키지 않는다.
- STT 조각이 많거나 여러 종목을 동시에 처리할 때 운영이 쉬워진다.

### 2.4 정량 게이트 강화

수정 파일:

- `core/five_gate_filter.py`

반영 내용:

- 기존 거래량 게이트에 더해
- `bid_ask_spread_bps > 35`면 차단
- `liquidity_score < 0.25`면 차단
- `volume_ratio`가 없어도 스프레드와 유동성 품질이 괜찮으면 통과 가능

운영 의미:

- 텍스트가 좋아도 실제로 체결하기 어려운 종목을 더 잘 걸러낸다.

### 2.5 연구/백테스트 API

추가 파일:

- `models/research_models.py`
- `core/backtester.py`
- `core/execution_style.py`
- `api/research_router.py`

수정 파일:

- `main.py`

반영 내용:

- `POST /api/v1/research/backtest`
- `POST /api/v1/research/style`

제공 결과:

- 총 시그널 수
- 승인 수
- 승/패 수
- 승률
- 평균 수익률
- 샤프
- 최대 낙폭
- 전략별 통계
- 평균 일별 거래 횟수
- 목표 승률 충족 여부
- 운용 모드 추천

운영 의미:

- "승률 50% 이상" 같은 목표를 코드 레벨에서 추적 가능하게 만들었다.

## 3. 전체 로직 흐름

1. `/api/v1/analyze` 또는 `/api/v1/analyze/batch`로 텍스트 조각과 시장 데이터를 받는다.
2. `call_id/event_id/batch_id`를 이용해 세션을 분리한다.
3. 컨텍스트 매니저가 최근 조각을 모아 프롬프트를 만든다.
4. `token_budgeter`가 프롬프트 크기를 추정하고 사용할 모델을 정한다.
5. `analysis_service`가 1차 추론을 수행한다.
6. 애매한 결과면 `llm_consistency`가 consensus 재추론을 수행한다.
7. integrity validator가 원문과 결과의 방향 불일치를 검사한다.
8. raw score, SUE, momentum, composite, regime, risk를 계산한다.
9. 5-gate가 거래 승인 여부를 결정한다.
10. 전략 오케스트레이터가 전략명을 정한다.
11. 리스크 매니저가 포지션, 손절, 익절을 계산한다.
12. 최종적으로 기존과 동일한 `TradingSignalV3`를 발행한다.

## 4. 매매는 어떻게 하는가

### 4.1 권장 운용 방식

기본 권장 방식은 `HFT`가 아니라 `이벤트 드리븐 인트라데이 + 선택적 스윙`이다.

이유:

- 어닝콜 데이터는 STT, 텍스트 정리, LLM 추론, 게이트 판단을 거치므로 초고빈도 체결에 맞지 않는다.
- 실적 이벤트의 알파는 초당 수백 건 체결보다, 발표 직후 수분~수시간의 가격 발견과 1~3일 PEAD 구간에 더 잘 맞는다.

### 4.2 몇 번 거래하는가

현재 구현 기준 추천값:

- `INTRADAY_EVENT`: 세션당 최대 2회
- `EVENT_SWING`: 세션당 최대 1회
- `SCALP`: 세션당 최대 3회, 최대 보유 45분
- `NO_TRADE`: 0회

실전 권장:

- 한 종목당 본진입 1회, 재진입 1회 정도로 제한하는 것이 적절하다.
- 어닝 시즌 전체 포트폴리오 관점에서는 하루 3~8개 승인 시그널 수준이 현실적 상한이다.

### 4.3 여러 어닝콜이 있으면 어떻게 하는가

- 같은 티커라도 서로 다른 `call_id`나 `event_id`를 부여해 완전히 다른 세션으로 처리한다.
- prepared remarks와 Q&A가 분리 유입되면 `section_type`으로 구분한다.
- Q&A는 경영진 즉답과 analyst interaction이 포함되므로 더 정보량이 크다고 보고, 실행 스타일 추천에서 `EVENT_SWING` 쪽으로 더 기울게 했다.
- 서로 다른 콜을 억지로 실시간 합산하지 않고, 백테스트/연구 단계에서만 묶어 성과를 본다.

## 5. 사용한 API와 입력

### 5.1 실시간 분석 API

- `POST /api/v1/analyze`
- `POST /api/v1/analyze/batch`

주요 입력:

- `ticker`
- `text_chunk`
- `sequence`
- `timestamp`
- `is_final`
- `market_data`
- `call_id`
- `event_id`
- `batch_id`
- `source_type`
- `section_type`
- `speaker_role`
- `speaker_name`

### 5.2 연구 API

- `POST /api/v1/research/backtest`
- `POST /api/v1/research/style`

백테스트 입력:

- `ticker`
- `timestamp`
- `composite_score`
- `raw_score`
- `trade_approved`
- `strategy`
- `actual_return`

스타일 추천 입력:

- `strategy`
- `composite_score`
- `confidence`
- `trade_approved`
- `market_data`
- `section_type`

## 6. 참고한 로직과 레퍼런스

### 6.1 J.P. Morgan / Goldman Sachs 공개 레퍼런스에서 가져온 방향성

- J.P. Morgan `Fusion` 계열 공개 자료는 데이터 소스 분리, 데이터 플랫폼화, 분석용 계층 분리를 참고하는 데 적합했다.
- J.P. Morgan `abides-jpmc-public`는 시장 미시구조와 이벤트 연구를 분리된 시뮬레이션 환경에서 다뤄야 한다는 점을 시사한다.
- Goldman Sachs `gs-quant`는 실시간 시그널 생성과 별도로 연구, 위험, 분석 계층을 나누는 접근을 참고하기 좋았다.

이번 구현에 반영된 해석:

- 분석 엔진과 연구 엔진을 분리했다.
- 실시간 의사결정과 백테스트/운용 추천을 별도 API로 분리했다.
- 다중 소스와 배치를 고려한 세션 메타데이터를 넣었다.

### 6.2 논문/연구에서 반영한 방향

- PEAD: 좋은 실적/가이던스 충격은 발표 후 며칠 동안 지연 반응이 이어질 수 있으므로, `EVENT_SWING` 모드와 SUE/PEAD 정합성 게이트를 유지했다.
- Earnings call Q&A research: prepared remarks보다 Q&A가 정보량이 더 클 수 있으므로, `section_type=Q_AND_A`일 때 더 보수적으로 스윙 관점을 택하도록 했다.
- Self-consistency: 애매한 LLM 결과는 다중 샘플 합의로 안정화하도록 했다.

## 7. 왜 HFT가 아닌가

이 시스템은 다음 이유로 HFT가 아니다.

- 실적 발표 텍스트 수집 자체가 밀리초 단위 확정 데이터가 아니다.
- STT 및 정제 과정이 존재한다.
- LLM 추론은 거래소 공장형 코로케이션 지연과 비교할 수 없다.
- 텍스트 기반 신호는 체결 속도보다 해석 품질과 체결 가능성 필터가 더 중요하다.

따라서 추천 전략은 다음 우선순위를 갖는다.

- 1순위: `INTRADAY_EVENT`
- 2순위: `EVENT_SWING`
- 3순위: 제한적 `SCALP`
- 비추천: HFT

## 8. 아직 더 붙일 만한 기능

다음은 다음 단계 개발 후보로 추천한다.

- 실시간 옵션 체인/IV surface API 연동
- analyst revision 및 estimate dispersion 외부 API 연동
- transcript embedding cache와 semantic retrieval
- event study 데이터베이스 구축
- walk-forward backtest
- 거래 비용, 슬리피지, borrow cost 반영
- 포트폴리오 레벨 익스포저 관리
- Q&A speaker-role별 가중치 모델
- audio prosody 분석

## 9. 참고 링크

아래 링크는 이번 설계 해석에 참고한 공개 자료다.

- Goldman Sachs `gs-quant`: https://github.com/goldmansachs/gs-quant
- Goldman Sachs GitHub org: https://github.com/goldmansachs
- J.P. Morgan `abides-jpmc-public`: https://github.com/jpmorganchase/abides-jpmc-public
- J.P. Morgan Fusion Java SDK: https://github.com/jpmorganchase/fusion-java-sdk
- Google Gemini model docs: https://ai.google.dev/gemini-api/docs/models/experimental-models
- Self-Consistency paper: https://doi.org/10.48550/arXiv.2203.11171
- PEAD classic paper entry: https://www.jstor.org/stable/2491062
- CEO/Q&A tone paper: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4115713
- Vocal delivery quality in earnings calls: https://doi.org/10.1016/j.jacceco.2024.101763

## 10. 이번 구현에서 실제 수정된 핵심 파일

- `config.py`
- `models/request_models.py`
- `models/research_models.py`
- `core/analysis_service.py`
- `core/token_budgeter.py`
- `core/llm_consistency.py`
- `core/execution_style.py`
- `core/backtester.py`
- `core/five_gate_filter.py`
- `api/analyze_router.py`
- `api/research_router.py`
- `main.py`

## 11. 한계와 주의사항

- 승률 50% 이상은 약속할 수 없다.
- 실적 시즌의 종목군, 장세, 유동성, 슬리피지에 따라 결과는 크게 달라진다.
- 현재 백테스터는 연구용 경량 버전이라 실제 체결 비용과 포트폴리오 상호작용은 더 보강해야 한다.
- `gordmansocks`는 공개 맥락상 Goldman Sachs 계열 레퍼런스로 해석해 반영했다.
