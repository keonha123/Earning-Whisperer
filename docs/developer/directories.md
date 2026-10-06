# 폴더 구성

이 문서는 저장소의 최상위 폴더와 모듈별 주요 하위 폴더가 무엇을 담는지 정리합니다. 코드를 처음 읽는 팀원과
기여자를 위한 문서입니다. 모듈 사이의 관계는 [architecture.md](architecture.md)를 참고합니다.

## 최상위

| 폴더 | 설명 |
|---|---|
| `.github/` | CI 워크플로(`workflows/test.yml`), PR 템플릿, CODEOWNERS |
| `trading-terminal/` | Electron 데스크톱 앱. 화면, KIS 주문, backend 연결 |
| `backend/` | Spring Boot 서버. 인증, 어닝콜 세션, STOMP 전달, 주문 기록, 시장 데이터 수집 |
| `ai-engine/` | FastAPI 서버. 주장 추출, 근거 검색, LLM 판정, 종합 판단 |
| `data_pipeline/` | Python 수집기. 실적 일정·뉴스 수집, 웹캐스트 캡처와 Whisper 음성 인식 |
| `infra/` | 로컬·시연 서버용 docker compose, 배포 스크립트 |
| `docs/` | 프로젝트 문서, 모듈 간 계약(`api-spec.md`), 시연 자료(`demo/`) |
| `frontend/` | Next.js 웹. 존속 여부를 검토 중입니다 |

## trading-terminal

| 폴더 | 설명 |
|---|---|
| `src/main/` | main process. `ipc/`(IPC 핸들러), `services/`(`BackendClient`, `StompService`, `KisService`, `OAuthService` 등), `store/`, `loadEnv.ts` |
| `src/preload/` | renderer 에 노출하는 IPC 브리지 |
| `src/renderer/` | React 화면. `pages/`, `components/`, `hooks/`, `store/`(zustand), `types/` |
| `src/lib/` | main 과 renderer 가 함께 쓰는 IPC 채널 이름, 타입, 주문 가격 계산 |
| `src/test/` | vitest 공통 설정(`setup.ts`)과 테스트 도구 |
| `resources/` | 앱 아이콘 |

## backend

| 폴더 | 설명 |
|---|---|
| `domain/` | `src/main/java/com/earningwhisperer/` 아래 패키지입니다. 엔티티와 도메인 서비스. `user`, `trade`, `portfolio`, `stock`, `market`, `earnings`, `transcript`, `watchlist`, `signal` |
| `infrastructure/` | 외부 연동. `aiengine`(ai-engine 클라이언트), `demo`(시연 재생), `websocket`(STOMP 발행), `finnhub`, `fmp`, `oauth`, `security`, `redis` 등 |
| `presentation/` | REST 컨트롤러. `/api/v1/**` 경로별 패키지 |
| `global/` | 공통 설정(`config/`), 예외 처리, 기반 엔티티 |
| `src/main/resources/data/` | 시연 스크립트(`demo-earnings-call.json`), 종목 목록(`sp500.csv`) |

## ai-engine

| 폴더 | 설명 |
|---|---|
| `api/routers/` | FastAPI 라우터. `/v1/engine/**`, `/health` 등 |
| `core/` | 분석 파이프라인, 프롬프트 구성, 근거 검색 |
| `services/` | 실시간 팩트체크, 뉴스·트랜스크립트 인입, 어닝 인텔리전스 등 서비스 계층 |
| `repositories/`, `db/`, `sql/` | PostgreSQL 이벤트 저장소와 Qdrant 근거 저장소 접근, 스키마 |
| `models/` | 요청·응답 pydantic 모델 |
| `tools/` | 백테스트, 호환성 검증 스크립트 |
| `tests/` | pytest 테스트 |

## data_pipeline

| 폴더 | 설명 |
|---|---|
| `collectors/` | 수집기. `stocks`, `schedules`, `prices`, `financial_statements`, `news`, `transcripts`, `streams` 등 |
| `stt_worker/` | 음성 인식 작업 |
| `tools/demo/` | 시연용 근거 뉴스·직전 콜 트랜스크립트 적재 도구 |
| `data/demo/` | 월마트 시연용 뉴스 스냅샷과 트랜스크립트 |
| `tests/` | unittest·pytest 테스트 |

## infra

| 경로 | 설명 |
|---|---|
| `docker-compose.yml` | 로컬 개발용 MySQL, Redis, PostgreSQL, Qdrant |
| `docker-compose.prod.yml`, `aws/` | 시연 서버용 compose, systemd 유닛, Cloudflare Tunnel 설정 |
| `deploy.sh`, `demo-up.sh`, `demo-down.sh` | 시연 서버 배포, 로컬 시연 스택 기동·종료 |
| `mysql-init/` | MySQL 초기화 SQL |
