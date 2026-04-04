# Gemini 3.x Cost-Aware Routing

## 핵심 구조

- 모든 청크는 최소 1회 Gemini를 호출한다.
- 기본 경로는 `gemini-3-flash-preview`다.
- review가 필요한 경우에만 `gemini-3-pro-preview`로 1회 승격한다.
- 라이브 경로의 호출 상한은 청크당 2회다.

## 라우팅 규칙

### 기본 청크

- route profile: `economy`
- context policy: `delta`
- 모델: `gemini-3-flash-preview`
- 목적: 비용 절감, 짧은 rationale, 축소된 market data 사용

### 중요 청크

다음 중 하나라도 만족하면 `standard`로 올린다.

- `section_type == Q_AND_A`
- `request_priority >= 8`
- `is_final == true`
- `abs(phase1_raw_score) >= 0.45`
- `volume_ratio >= 2.5`
- `abs(gap_pct) >= 3.0`
- `abs(earnings_surprise_pct) >= 10.0`

## Review 승격 규칙

다음 조건에서만 `gemini-3-pro-preview`를 호출한다.

- integrity validation 실패
- Flash 결과와 phase-1 방향 충돌, 양쪽 confidence 모두 `>= 0.70`
- Flash confidence `< 0.68` 이면서 중요 청크
- `euphemism_count >= 2` 이고 Q&A 또는 guidance 문맥
- Flash 결과가 구조화 출력으로 파싱되지 않음

## 프롬프트 프로파일

- `economy`
  - rationale 1문장
  - 축소된 market data
  - `max_output_tokens=384`
  - `thinking_level=minimal`
- `standard`
  - rationale 2문장
  - 전체 relevant market data
  - `max_output_tokens=640`
  - `thinking_level=low`
- `adjudication`
  - 1차 결과, phase-1 score, review reason 포함
  - `max_output_tokens=960`
  - `thinking_level=medium`

## 관측 지표

`/stats`에 아래 항목이 추가된다.

- `route_counts`
- `flash_only_rate`
- `pro_escalation_rate`
- `avg_estimated_prompt_tokens`
- `avg_estimated_output_tokens`
- `economy_prompt_rate`
