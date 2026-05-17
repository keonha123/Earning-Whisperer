# AI Engine Auto Promotion Execution Note

## 이번 단계에서 추가한 내용
- gate patch 저장/list API
- alert state action 저장/list API
- gate patch apply API
- active gate config 조회 API
- gate config rollback API
- shadow compare API
- auto-promotion policy evaluate API

## 핵심 API
### POST `/v1/engine/controls/gate-patches/auto-promotion/evaluate`
입력된 baseline/candidate shadow 성과와 policy를 비교해 자동 승격 가능 여부를 판단합니다.

정책 항목:
- `min_score`
- `min_sample_size`
- `require_positive_avg_return_delta`
- `max_false_positive_delta`
- `auto_apply`

출력 항목:
- `decision`: `promote_candidate` | `holdout`
- `action`: `none` | `auto_applied`
- `reason_ko`
- `score`
- `comparison`
- `apply_result`

## 검증 결과
- 전체 테스트 통과: `63 passed`
- 주요 저장/조회/롤백/비교/자동승격 API 테스트 포함

## 주의
이 단계는 이전 대화에서 생성된 일부 문서 전용 산출물 때문에, 마지막으로 안정적으로 실행 가능한 전체 AI Engine 패키지를 기준으로 재구성 후 확장했습니다.
