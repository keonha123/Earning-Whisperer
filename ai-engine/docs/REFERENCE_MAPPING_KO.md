# 공개 레퍼런스 반영 메모

## Goldman Sachs `gs-quant`

참고 포인트:

- 연구/분석/실행 관심사를 하나의 거대한 서비스에 섞지 않고 계층적으로 나누는 방식
- 데이터 모델과 연산 계층을 분리하는 방식

우리 코드 반영:

- `models/`에 계약/분석/통합 모델을 분리
- `research_router.py`와 실시간 분석 API 분리
- `contract_adapter.py`로 외부 계약과 내부 모델 분리

## JPMorganChase `fusion-java-sdk`

참고 포인트:

- 데이터 플랫폼과 소비자 애플리케이션 사이를 계약 중심 인터페이스로 잇는 방식
- SDK/서비스 경계가 명확한 구조

우리 코드 반영:

- `integration_router.py`로 collector/desktop/web 경계를 명확히 노출
- `integration_state.py`로 외부 입력을 내부 분석과 분리해 관리
- Redis 최소 계약과 enriched 계약을 분리

## JPMorganChase `abides-jpmc-public`

참고 포인트:

- 연구용 환경과 실시간 실행 경로를 구분하는 관점
- 이벤트/시장 미시구조를 별도 상태 계층에서 다루는 방식

우리 코드 반영:

- `backtester.py`와 연구 API를 별도 경로로 유지
- live-room용 분석 뷰와 실제 trade 승인용 내부 신호 분리
- 여러 earnings call을 세션 키 단위로 분리

## 주의

이 문서는 공개 저장소의 구조적 아이디어를 참고한 해석 메모다.
특정 기관의 독점 전략을 복제했다는 의미는 아니다.
