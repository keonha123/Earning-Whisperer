# EarningWhisperer v3.3.0 요구사항 정리

## 1. 목적

이 프로젝트는 어닝콜, 가이던스, 실적 발표 직후 텍스트와 시장 데이터를 함께 해석해, 기존 `TradingSignalV3` 출력 형식을 유지하면서 더 일관된 LLM 분석과 더 보수적인 이벤트 드리븐 매매 의사결정을 제공해야 한다.

이번 요구사항의 핵심은 다음과 같다.

- 출력 스키마는 그대로 유지한다.
- 단일 콜뿐 아니라 여러 어닝콜, 여러 섹션, 여러 소스 배치를 동시에 처리할 수 있어야 한다.
- LLM 응답 속도와 비용을 고려해 빠른 1차 추론과 필요한 경우에만 재검증하는 구조를 사용해야 한다.
- 단순 감성 분석이 아니라 PEAD, 유동성, 스프레드, 변동성, 체결 가능성까지 반영한 이벤트 트레이딩 엔진이어야 한다.
- 승률 50% 이상은 보장 대상이 아니라 운영 목표치로 두고, 백테스트 및 게이트 조정으로 관리해야 한다.

## 2. 비즈니스/운영 요구사항

### 2.1 전략 성격

- 이 엔진은 고빈도 매매용 HFT 엔진이 아니다.
- 기본 운용 철학은 `이벤트 드리븐 인트라데이 + 선택적 이벤트 스윙`이다.
- 스캘핑은 극도로 유동적인 종목에서만 제한적으로 허용한다.
- 어닝콜 텍스트, Q&A, 가이던스 변화, 서프라이즈, 체결 품질을 결합해 진입 여부를 판단한다.

### 2.2 권장 매매 빈도

- 기본 추천 모드는 `EVENT_SWING` 또는 `INTRADAY_EVENT`다.
- 종목별 기본 진입 횟수는 세션당 0~2회 이내로 제한한다.
- `SCALP`는 예외 모드이며 세션당 최대 3회까지만 허용한다.
- 어닝콜 텍스트 기반 의사결정은 뉴스/오디오/STT/LLM 왕복 지연이 존재하므로 HFT처럼 초단타 수십~수백 회 체결을 목표로 하지 않는다.

### 2.3 승률 목표

- `execution_target_win_rate=0.50`을 기본 운영 목표로 둔다.
- 목표 미달 시 게이트를 강화하고, 목표 초과가 표본 수와 함께 확인되면 제한적으로 완화한다.
- 승률은 승인된 시그널 기준으로 측정한다.

## 3. 입력 요구사항

### 3.1 분석 입력

`POST /api/v1/analyze`

- `ticker`
- `text_chunk`
- `sequence`
- `timestamp`
- `is_final`
- `market_data`

### 3.2 다중 콜/다중 소스 입력

다음 메타데이터를 새로 지원해야 한다.

- `call_id`: 개별 어닝콜 식별자
- `event_id`: 소스 이벤트 식별자
- `batch_id`: 대량 입력 배치 식별자
- `source_type`: 어닝콜, 보도자료, 뉴스, 파일링 등 구분
- `section_type`: `PREPARED_REMARKS`, `Q_AND_A`, `OTHER`
- `speaker_role`
- `speaker_name`
- `transcript_language`
- `request_priority`

### 3.3 시장 데이터 입력

기존 가격/기술적 지표 외에 아래 항목을 지원해야 한다.

- `relative_strength_20d`
- `realized_vol_10d`
- `analyst_revision_delta_pct`
- `bid_ask_spread_bps`
- `liquidity_score`
- `options_volume_ratio`
- `implied_move_pct`

## 4. 처리 요구사항

### 4.1 LLM 처리

- 프롬프트 크기를 추정해 토큰 예산을 세워야 한다.
- 작은 프롬프트는 빠른 모델로 처리한다.
- 낮은 confidence, 약한 방향성, 완곡어법 증가, 큰 프롬프트일 때만 consensus 재추론을 수행한다.
- LLM 응답이 텍스트 원문과 충돌하면 integrity retry를 수행해야 한다.

### 4.2 정량 로직

- Raw sentiment 점수
- PEAD 방향 정합성
- Momentum 정합성
- 거래량/유동성/스프레드 품질
- 시장 레짐 및 VIX
- 위험관리와 포지션 사이징

위 로직을 결합해 `trade_approved`를 결정해야 한다.

### 4.3 다중 어닝콜 처리

- 동일 티커라도 `ticker:call_id` 또는 `ticker:event_id` 단위로 세션을 분리해야 한다.
- Q&A와 prepared remarks가 섞여 들어와도 세션 충돌 없이 처리해야 한다.
- 배치 입력 시 동시성은 설정값 상한 내에서 제어해야 한다.
- 서로 다른 콜은 연구/백테스트 층에서만 통합 평가하고, 실시간 판단은 독립 세션으로 유지한다.

## 5. 출력 요구사항

기존 `TradingSignalV3` 출력 형식은 바꾸지 않는다.

- `ticker`
- `raw_score`
- `rationale`
- `text_chunk`
- `timestamp`
- `composite_score`
- `sue_score`
- `momentum_score`
- `trade_approved`
- `primary_strategy`
- `signal_strength`
- `position_pct`
- `market_regime`
- `catalyst_type`
- `stop_loss_price`
- `take_profit_price`
- `stop_loss_pct`
- `take_profit_pct`
- `profit_factor`
- `hold_days_max`
- `failed_gates`
- `whisper_signal`
- `sector_contagion`
- `cot_reasoning`

새 기능은 추가 엔드포인트나 내부 로직으로 제공하고, 최종 거래 시그널 페이로드는 유지한다.

## 6. 연구/운영 보조 API 요구사항

다음 연구용 API를 제공해야 한다.

- `POST /api/v1/analyze/batch`
- `POST /api/v1/research/backtest`
- `POST /api/v1/research/style`

`/research/backtest`는 최소한 다음을 산출해야 한다.

- 승인 비율
- 승률
- 평균 수익률
- 샤프
- 최대 낙폭
- 전략별 통계
- 평균 일별 거래 횟수
- 목표 승률 충족 여부
- 운용 모드 권고

`/research/style`는 최소한 다음을 산출해야 한다.

- 추천 운용 모드
- 세션당 최대 거래 횟수
- 최대 보유 시간
- 추천 사유

## 7. 비기능 요구사항

- API 키가 없더라도 로컬 테스트와 import 단계에서 즉시 실패하지 않아야 한다.
- 배치 처리, 토큰 예산, consensus 재추론은 설정 기반으로 제어 가능해야 한다.
- 결과는 재현 가능하도록 게이트와 연구 지표를 수치화해야 한다.
- 성능 개선은 속도만이 아니라 체결 가능성까지 포함해야 한다.

## 8. 이번 요구사항의 해석상 가정

- 사용자 요청의 `gordmansocks`는 공개 정량 라이브러리 문맥상 Goldman Sachs 및 `gs-quant` 레퍼런스를 의미하는 것으로 해석했다.
- 공개 레퍼런스는 설계와 운영 아이디어 참고용이며, 특정 기관의 독점 전략을 복제한다는 의미는 아니다.
