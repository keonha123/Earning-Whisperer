# 팀 브리핑 반영 ai_engine 호환 정리

## 1. 이번 브리핑에서 읽은 핵심

팀 브리핑 기준으로 현재 시스템은 다음 방향으로 가고 있다.

- `collectors`는 종목별 어닝콜 일정, 종목별 분당주가, 기업리스트, 분석팀 요구 지표를 수집 중이다.
- STT 수집과 시장평가 정보 수집은 아직 작업 중이다.
- 백엔드/분석팀과 API 통신 방식은 아직 최종 합의 전이다.
- 웹은 소개, 데모, 로그인, 일정/관심종목 선택, 어닝콜 라이브룸, 마이페이지, 다운로드 페이지 중심이다.
- 실제 증권사 연동은 중앙 웹서버가 아니라 `Electron desktop + local server` 구조로 이동했다.
- 웹 라이브룸은 매매 관련 없는 버전이 필요하다.

이 브리핑을 바탕으로 `ai_engine`은 "직접 브로커를 잡는 엔진"보다 "분석 엔진 + 팀 간 호환 계층"으로 맞추는 것이 맞다.

## 2. 이번에 ai_engine에서 맞춘 호환 포인트

### 2.1 Collector 친화형 ingest API 추가

추가된 엔드포인트:

- `POST /api/v1/integration/collector/schedules`
- `POST /api/v1/integration/collector/universe`
- `POST /api/v1/integration/collector/indicator-snapshots`
- `POST /api/v1/integration/collector/market-context`
- `POST /api/v1/integration/collector/transcript-chunk`
- `GET /api/v1/integration/collector/state/{ticker}`

의미:

- 수집팀이 이미 만들고 있는 일정/기업리스트/분당가격 기반 지표를 AI 엔진이 따로 받아 임시 캐시할 수 있다.
- STT 수집이 완성되면 기존 `/api/v1/analyze` 대신 collector 전용 의미를 가진 `/collector/transcript-chunk`로 붙일 수 있다.
- 아직 백엔드와 데이터서버 통신 스펙이 덜 정해져 있어도, 우선 REST 계약부터 맞춰서 독립 개발이 가능하다.

### 2.2 분석 요청 시 수집 데이터 자동 병합

바뀐 동작:

- `AnalyzeRequest.market_data`가 일부만 와도 된다.
- collector가 먼저 넣어둔 종목별 지표와 시장 컨텍스트를 엔진이 자동으로 병합한다.
- 따라서 프론트, STT 파이프라인, 분석팀이 각각 데이터를 따로 보내더라도 현재 시점의 최대한 풍부한 입력으로 분석 가능하다.

의미:

- 아직 팀 간 API 조합이 완전하지 않아도 기능 연결이 쉬워진다.

### 2.3 웹 라이브룸 비매매 뷰 분리

추가된 엔드포인트:

- `GET /api/v1/integration/live-room/{ticker}`

반환 방식:

- 방향성
- 요약 rationale
- catalyst
- 시장 레짐
- 텍스트 발췌
- speaker/section 메타데이터

만 제공한다.

제외한 정보:

- `position_pct`
- 손절/익절
- 포지션 관련 값
- 체결 관련 값

의미:

- 웹 라이브룸은 "분석만 보여주는 버전"으로 구성할 수 있다.
- 팀 브리핑에서 말한 "매매 관련 없는 라이브룸" 요구와 맞다.

### 2.4 데스크탑 브로커 구조와 충돌하지 않도록 조정

추가된 엔드포인트:

- `POST /api/v1/integration/desktop/execution-feedback`
- `GET /api/v1/integration/capabilities`

반영된 원칙:

- `ai_engine`은 사용자 증권사 API 키를 저장하지 않는다.
- 브로커 연동 주체는 `desktop local server`다.
- 엔진은 나중에 데스크탑이 보내는 체결 피드백만 받아 연구/리포팅에 활용할 수 있다.

의미:

- 중앙 서버에서 브로커 키를 수집하지 않는 현재 설계와 충돌하지 않는다.

## 3. 팀 브리핑 항목별 대응 상태

### 3.1 이미 collector에서 구현된 부분

- 어닝콜 일정 수집: 대응 완료
- 기업 리스트 수집: 대응 완료
- 종목 지표 수집: 대응 완료
- 분당 주가/지표 기반 입력: 대응 완료

대응 방식:

- collector ingest API
- `IntegrationStateStore` 캐시
- 분석 요청 시 자동 병합

### 3.2 아직 작업 중인 부분

- 어닝콜 STT 수집: 계약 대응 완료, 구현팀 연결 대기
- 시장평가 정보 수집: 계약 대응 완료, 세부 필드 확장 가능
- 백엔드/분석팀 API 합의: 호환용 REST 경계 먼저 제공
- 데이터서버 구동: 아직 ai_engine 레벨에서는 미포함

### 3.3 웹/프론트 요구

- 비매매 라이브룸: 대응 완료
- 프로그램 소개/데모/로그인 페이지: ai_engine 직접 범위 아님
- 관심종목/일정 선택 연동: collector state 및 schedule API로 연결 준비

### 3.4 데스크탑/Electron 요구

- 로컬에서 브로커 연동: 존중
- 필요한 정보만 서버로 콜백: execution feedback 엔드포인트로 수용 가능
- 웹서버에 계좌 키 저장 안 함: ai_engine도 동일 원칙 유지

## 4. 이번 변경으로 생긴 장점

- 팀별 작업 속도가 달라도 AI 엔진이 중간 버퍼 역할을 할 수 있다.
- 아직 결정되지 않은 백엔드 계약을 기다리느라 분석 엔진 개발이 멈추지 않는다.
- 웹은 안전한 라이브룸 데이터만 받을 수 있다.
- 데스크탑은 브로커 키를 로컬에 두면서도 체결 성과를 나중에 피드백할 수 있다.

## 5. 아직 남은 권장 후속 작업

- WebSocket 또는 SSE 라이브룸 스트림
- collector 인증/서명 정책
- execution feedback를 backtester 데이터셋으로 연결
- 시장평가 정보 필드 표준화
- STT chunk ordering / dedup / replay 정책
- backend와의 Redis vs REST vs gRPC 최종 결정

## 6. 관련 파일

- `api/integration_router.py`
- `core/integration_state.py`
- `models/integration_models.py`
- `api/analyze_router.py`
- `main.py`
