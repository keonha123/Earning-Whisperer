# AI Engine Hardening Update 3.4.2

## 목적

- FinBERT를 다시 도입한 뒤에도 실시간 처리 경로가 이벤트 루프를 막지 않도록 보완
- 첫 요청 지연과 Redis 장애 시 메시지 유실 위험을 줄이도록 운영 기본값 정리
- phase-1 모델 스키마 검증을 강화해 다른 sentiment 모델 오설정 시 조용히 잘못된 점수가 나오는 문제를 방지

## 반영된 보완 사항

### 1. phase-1 FinBERT 추론의 비동기 경로 분리

- 파일: `api/analyze_router.py`
- 변경: `phase1_scorer.analyze_text()`를 `asyncio.to_thread()`로 실행
- 효과:
  - FastAPI 이벤트 루프가 FinBERT 추론 동안 직접 블로킹되지 않음
  - 배치 요청과 동시 요청에서 처리량 저하를 완화

### 2. startup warmup 기본값 정렬

- 파일: `config.py`, `.env.example`, `main.py`
- 변경:
  - `phase1_warmup_on_startup` 기본값을 `true` 기준으로 정렬
  - 앱 startup 시 `phase1_scorer.warmup()` 실행
- 효과:
  - 첫 실시간 요청이 모델 로딩 비용을 전부 부담하는 상황을 줄임
  - 운영 환경에서 latency spike를 완화

### 3. Redis primary/enriched 백업 큐 분리

- 파일: `core/redis_publisher.py`
- 변경:
  - `trading-signals`용 primary 백업 큐와 `trading-signals-enriched`용 enriched 백업 큐를 분리
  - flush 시 primary 큐를 먼저 비운 뒤 enriched 큐를 전송
  - enriched 큐가 가득 차더라도 primary 큐를 잠식하지 않도록 분리 저장
- 효과:
  - Backend가 반드시 받아야 하는 최소 계약 메시지의 생존성이 높아짐
  - Redis 장애 중에도 핵심 계약 채널의 우선순위가 유지됨

### 4. FinBERT 라벨 스키마 검증 강화

- 파일: `core/phase1_scorer.py`
- 변경:
  - 로딩 시 `POSITIVE`, `NEGATIVE` 라벨 존재 여부를 검증
  - 확률 매핑 함수도 라벨 누락 시 즉시 예외 처리
- 효과:
  - 다른 분류 모델이 실수로 연결되더라도 조용히 잘못된 raw score를 내지 않음
  - phase-1 신뢰성이 올라감

### 5. 운영 상태 관측성 추가

- 파일: `main.py`, `core/phase1_scorer.py`
- 변경:
  - `/stats`에 `phase1_status` 노출
  - 현재 provider, FinBERT 로딩 여부, device, cache size, init_error 확인 가능
- 효과:
  - 운영 중 FinBERT가 실제로 로딩됐는지, lexical fallback으로 내려갔는지 빠르게 진단 가능

## 테스트

- 파일: `tests/test_redis_publisher.py`
- 추가 검증:
  - Redis 장애 시 primary 큐가 enriched 큐 때문에 밀려나지 않는지 확인
  - backup flush 시 primary 채널이 enriched 채널보다 먼저 전송되는지 확인

## 결과

- 현재 구조는 `FinBERT raw score first + Gemini main LLM second`를 유지하면서도
  실시간 경로의 처리량, 장애 복원력, 운영 관측성을 한 단계 더 보강한 상태다.
