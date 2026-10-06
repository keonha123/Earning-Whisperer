# 로컬 개발 환경

이 문서는 backend, ai-engine, trading-terminal 을 개발 PC 에서 띄우고 시연 어닝콜로 동작을 확인하는 방법을
다룹니다. 처음 저장소를 받은 팀원과 기여자를 위한 문서입니다. 폴더 구성은 [directories.md](directories.md),
테스트 실행은 [testing.md](testing.md)를 참고합니다.

## 필요한 도구

| 도구 | 버전 | 쓰는 곳 | 근거 |
|---|---|---|---|
| JDK | 17 | backend | `build.gradle` 의 toolchain, CI `temurin 17` |
| Node.js | 20 | trading-terminal | CI `setup-node` 버전. `engines` 필드와 `.nvmrc` 는 없습니다 |
| Python | 3.12 | ai-engine, data_pipeline | CI `setup-python` 버전. `.python-version` 은 없습니다 |
| Docker, Docker Compose | - | 로컬 인프라 | `infra/docker-compose.yml` |
| C++ 빌드 도구 | - | trading-terminal | keytar 네이티브 모듈 재빌드. Windows 는 Visual Studio Build Tools, macOS 는 Xcode Command Line Tools |
| Gradle | wrapper | backend | `backend/gradlew` 가 저장소에 있어 따로 설치하지 않습니다 |

## 저장소 받기

```bash
git clone https://github.com/keonha123/Earning-Whisperer.git
cd Earning-Whisperer
```

## 인프라 기동

`infra/docker-compose.yml` 에 개발용 서비스가 정의되어 있습니다. 기본으로 뜨는 서비스는 네 개입니다.

| 서비스 | 컨테이너 | 포트 | 쓰는 모듈 | 접속 정보 |
|---|---|---|---|---|
| `redis` | `ew-redis` | 6379 | backend, ai-engine | - |
| `db` (MySQL 8.0) | `ew-mysql` | 3306 | backend, data_pipeline | DB `earning_whisperer`, root 비밀번호 `root`, 사용자 `user` / `password` |
| `postgres` (16) | `ew-postgres` | 5432 | ai-engine | DB `earningwhisperer`, `postgres` / `postgres` |
| `qdrant` | `ew-qdrant` | 6333, 6334 | ai-engine | - |

```bash
cd infra
docker compose up -d                 # 네 서비스 모두
docker compose up -d redis db        # backend 와 trading-terminal 만 볼 때
```

`browser-webcast`(프로필 `tools`)와 `pipeline-scheduler`(프로필 `ops`)는 data_pipeline 용이라 기본 기동에서
빠집니다. MySQL 컨테이너는 `infra/mysql-init/` 의 SQL 을 초기화 스크립트로 마운트합니다.

## backend

### 환경변수

Spring Boot 는 `backend/.env` 파일을 직접 읽지 않습니다. `backend/.env.example` 은 필요한 키 목록이고
값은 셸 환경변수나 `backend/src/main/resources/application-local.yml`(git 에서 제외됨)로 넣습니다.
`./gradlew bootRun` 은 `local` 프로파일을 자동으로 켭니다. 값을 넣지 않은 항목은 `application.yml` 의
기본값을 씁니다.

`backend/.env.example` 의 변수입니다.

| 변수 | 용도 | 로컬 필수 |
|---|---|---|
| `DB_URL` | MySQL JDBC URL. data_pipeline 과 같은 DB 를 씁니다 | 아니요 (기본값 `localhost:3306/earning_whisperer`) |
| `DB_USERNAME`, `DB_PASSWORD` | MySQL 계정 | 예. 기본값 `root` / `password` 는 compose 계정과 맞지 않습니다 |
| `REDIS_HOST`, `REDIS_PORT` | Redis 주소 | 아니요 (기본값 `localhost:6379`) |
| `JWT_SECRET` | JWT 서명 키, 32자 이상 | 아니요 (개발용 기본값 있음). 단 `.env` 를 셸로 불러올 때 빈 값으로 두면 기본값이 쓰이지 않아 기동에 실패합니다. 배포에서는 필수 |
| `JWT_ISSUER`, `JWT_AUDIENCE` | 토큰의 발급자·대상 | 아니요 |
| `JWT_COOKIE_SECURE` | refresh 토큰 쿠키의 Secure 속성. HTTPS 배포에서 `true` | 아니요 (기본값 `false`) |
| `SERVER_ADDRESS` | 수신 인터페이스. 시연 서버는 `127.0.0.1` | 아니요. 로컬에서는 비워 둡니다 |
| `CORS_ALLOWED_ORIGINS` | 허용 출처 목록 | 아니요 |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URIS` | Google OAuth | OAuth 로그인을 쓸 때만 |
| `KAKAO_CLIENT_ID`, `KAKAO_CLIENT_SECRET`, `KAKAO_REDIRECT_URIS` | Kakao OAuth | OAuth 로그인을 쓸 때만 |
| `INTERNAL_SECRET` | `/api/v1/internal/**` 호출용 `X-Internal-Secret` 값. 비어 있으면 해당 경로를 모두 막습니다 | data_pipeline·ai-engine 이 backend 를 호출할 때만 |
| `FINNHUB_API_KEY`, `FMP_API_KEY` | 어닝 일정, S&P 500 동기화 스케줄러. 비어 있으면 키가 필요한 동기화 스케줄러와 Finnhub WebSocket(종목 시세)이 꺼집니다 | 아니요 |
| `TRADE_MANUAL_PENDING_TTL_SECONDS` | 체결을 기다리는 수동 주문(PENDING)의 만료 시간(초). 주석 처리되어 있습니다 | 아니요 (기본값 `86400`) |

`.env.example` 에는 없고 `application.yml` 에만 있는 변수입니다.

| 변수 | 기본값 | 용도 |
|---|---|---|
| `AI_ENGINE_BASE_URL` | `http://localhost:8000` | ai-engine 주소 |
| `AI_ENGINE_FACT_CHECK_ENABLED` | `true` | `false` 면 팩트체크 요청만 끕니다. 종합 판단과 직전 콜 대조 호출은 각자 설정을 따릅니다 |
| `AI_ENGINE_SUMMARY_ENABLED` | `true` | 어닝콜 종료 후 종합 판단 요청 여부 |
| `AI_ENGINE_TIMEOUT_MS` | `50000` | ai-engine 읽기 타임아웃 |
| `DEMO_SCRIPT_PATH` | `data/demo-earnings-call.json` | 시연 스크립트(classpath 기준) |
| `DEMO_SEGMENT_INTERVAL_MS` | `6000` | 시연 세그먼트 발행 간격 |

### 실행

`.env` 파일을 셸로 불러와 실행하는 예입니다. `.env.example` 를 그대로 복사하면 아래 주석의 값을 고쳐야 합니다.

```bash
cd backend
cp .env.example .env
# DB_USERNAME=user, DB_PASSWORD=password 로 고칩니다
# JWT_SECRET 은 32자 이상으로 채우거나 줄을 지웁니다(빈 값이면 기동 실패)
# DB_URL 값은 따옴표로 감쌉니다
set -a; . ./.env; set +a
./gradlew bootRun
```

서버는 8082 포트에서 뜹니다. 기동 시 `StockDataInitializer` 가 `sp500.csv` 의 종목을 `stocks` 테이블에 넣습니다.

```bash
curl http://localhost:8082/actuator/health
```

## ai-engine

ai-engine 은 팩트체크와 종합 판단을 만듭니다. 트랜스크립트 재생만 확인할 때는 띄우지 않고 backend 에
`AI_ENGINE_FACT_CHECK_ENABLED=false`, `AI_ENGINE_SUMMARY_ENABLED=false` 를 주면 됩니다. 직전 콜 대조 호출은
별도 설정(`ai-engine.transcript-diff-enabled`)이라 계속 나가지만, 실패해도 재생에는 영향이 없습니다.

```bash
cd ai-engine
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                 # GEMINI_API_KEY 를 채웁니다
uvicorn main:app --reload
```

8000 포트에서 뜹니다. 설정 클래스(`config.py` 의 `Settings`)는 실행 위치의 `.env` 를 읽으므로 `ai-engine/`
안에서 실행합니다. 상태 확인 엔드포인트는 `GET /health`, `GET /health/live`, `GET /health/ready` 입니다.

`.env` 없이 띄우면 코드 기본값이 적용되어 벡터 저장소가 메모리(`VECTOR_STORE_BACKEND=memory`), 임베딩이
해시(`EMBEDDING_PROVIDER=hash`)가 되고 팩트체크 타임아웃도 짧아집니다. 시연과 같은 동작을 보려면
`.env.example` 을 복사해 씁니다. 주로 확인하는 변수입니다.

| 변수 | `.env.example` 값 | 용도 |
|---|---|---|
| `GEMINI_API_KEY` | (비어 있음) | 판정·종합 판단·임베딩에 쓰는 Gemini 키 |
| `DATABASE_URL` | `postgresql://postgres:postgres@localhost:5432/earningwhisperer` | 이벤트 저장소(PostgreSQL) |
| `VECTOR_STORE_BACKEND`, `QDRANT_URL` | `qdrant`, `http://localhost:6333` | 근거 뉴스 벡터 저장소 |
| `EMBEDDING_PROVIDER`, `EMBEDDING_MODEL` | `gemini`, `gemini-embedding-001` | 임베딩 모델 |
| `GEMINI_PRIMARY_MODEL`, `GEMINI_REVIEW_MODEL` | `gemini-3.1-flash-lite`, `gemini-3.6-flash` | 판정 모델 |
| `FACT_CHECK_EXTRACTION_TIMEOUT_SECONDS`, `FACT_CHECK_LLM_TIMEOUT_SECONDS` | `25.0`, `25.0` | 주장 추출·검증 타임아웃 |

## trading-terminal

```bash
cd trading-terminal
npm install
cp .env.example .env.local
npm run dev
```

`npm install` 의 `postinstall` 이 `electron-rebuild -f -w keytar` 를 실행해 keytar 를 Electron 에 맞춰 다시
빌드합니다. 여기서 실패하면 C++ 빌드 도구 설치 여부를 확인합니다. dev 실행에서는 main process 의
`loadEnv.ts` 가 `.env.local`, `.env` 순으로 값을 읽습니다.

| 변수 | 용도 |
|---|---|
| `BACKEND_URL` | backend 주소. 설정하지 않으면 `http://localhost:8082`. `.env.example` 에는 시연 서버 주소가 들어 있습니다 |
| `OAUTH_GOOGLE_CLIENT_ID`, `OAUTH_KAKAO_CLIENT_ID` | OAuth client ID. 이메일 로그인만 쓸 때는 비워 둬도 앱이 뜹니다 |
| `OAUTH_LOOPBACK_PORT` | OAuth 콜백을 받는 로컬 포트. 기본값 9000 |

로컬 backend 에 붙이려면 `.env.local` 의 `BACKEND_URL` 을 `http://localhost:8082` 로 바꿉니다.

### 로그인

터미널의 회원가입 버튼은 아직 동작하지 않습니다. 이메일 계정은 backend 에 직접 만듭니다. 이메일 도메인의
최상위 도메인이 `.local`, `.test`, `.example`, `.invalid` 이면 거부됩니다(`EmailDomainPolicy`).

```bash
curl -X POST http://localhost:8082/api/v1/auth/signup \
  -H 'Content-Type: application/json' \
  -d '{"email":"dev@example.org","password":"password1234","nickname":"dev"}'
```

로그인 뒤에는 KIS 자격증명 등록 화면이 나옵니다. 모의투자나 실전투자 중 한쪽의 App Key, App Secret,
계좌번호(숫자 8자리 또는 10자리)를 넣어야 대시보드로 넘어갑니다. 저장 직후 KIS 토큰 발급이 실패해도 저장은
완료되며, 이후 KIS 를 호출할 때 발급을 다시 시도합니다.

OAuth 로그인은 터미널이 `http://localhost:9000/auth/callback` 을 redirect URI 로 씁니다(`OAuthService`).
backend 의 `GOOGLE_REDIRECT_URIS`·`KAKAO_REDIRECT_URIS` 기본값은 `http://localhost:3000/auth/callback` 이므로
이 주소를 추가하고 각 OAuth 콘솔에도 같은 주소를 등록해야 합니다.

## 원격 시연 서버에 터미널만 붙이기

backend 와 ai-engine 을 로컬에 띄우지 않고 시연 서버(`https://api.logothea.com`)를 쓸 수 있습니다.
`trading-terminal/.env.local` 에 아래 값을 두고 `npm run dev` 를 실행합니다. `.env.example` 의 기본값과 같습니다.

```bash
BACKEND_URL=https://api.logothea.com
```

시연 서버는 refresh 토큰 쿠키에 Secure 속성을 붙입니다. 평문 `http` 주소로 붙으면 앱이 쿠키를 보관하지 못해
15분 뒤 토큰 갱신에 실패합니다. 서버 인스턴스가 꺼져 있을 수 있으며 켜고 끄는 절차는
[`infra/DEPLOY.md`](../../infra/DEPLOY.md)에 있습니다.

## data_pipeline

시연 확인에는 data_pipeline 서비스를 띄울 필요가 없습니다. 시연용 근거 뉴스를 ai-engine 에 넣을 때 이 모듈의
도구를 씁니다. 의존성은 `data_pipeline/requirements.txt` 에 있고 패키지 경로(`data_pipeline.*`)로 실행하므로
저장소 루트에서 `python -m` 으로 실행합니다. 수집 스케줄러와 웹캐스트 캡처는 `data_pipeline/README.md` 를
참고합니다.

## 시연 데이터로 동작 확인

1. 인프라 네 서비스, ai-engine, backend 를 띄웁니다.
2. 근거 뉴스 스냅샷을 ai-engine 에 넣습니다. 근거가 없으면 팩트체크가 대부분 "근거 부족"으로 나옵니다.

   ```bash
   python -m data_pipeline.tools.demo.collect_demo_evidence ingest \
       --snapshot data_pipeline/data/demo/wmt-2026q2-news.json
   ```

   직전 콜 발언 대조까지 보려면 `data_pipeline.tools.demo.ingest_demo_transcript` 로
   `wmt-2026q1-transcript.json` 을 넣습니다. 인자는 해당 파일의 docstring 에 있습니다.
   적재할 때 ai-engine 이 Gemini 로 직전 콜의 핵심 문장을 추출하므로 `GEMINI_API_KEY` 가 필요합니다.
   콜 1건에 Gemini 약 6회를 동시에 호출하며, 추출에 10초 안팎이 더 걸립니다. 응답의
   `key_statement_counts` 가 저장된 문장 수입니다. 이 도구의 `--purge` 는 저장된 핵심 문장도 함께 지웁니다.
3. 터미널에 로그인합니다.
4. 홈 오른쪽 위의 "시연 재생" 버튼을 누릅니다. WMT 콜 화면이 열리면서 터미널이
   `POST /api/v1/demo/earnings-call/start` 를 호출하고 backend 의 `DemoEarningsCallService` 가
   `backend/src/main/resources/data/demo-earnings-call.json`(월마트 2026-08-20 콜, 24개 세그먼트)을 6초 간격으로
   재생합니다.
5. 트랜스크립트는 `/topic/transcript/{ticker}`, 팩트체크는 `/topic/factcheck/{ticker}`, 종합 판단은
   `/topic/evaluation/{ticker}` 로 화면에 들어옵니다.

<!-- 스크린샷: 시연 재생 중인 트레이딩룸 (트랜스크립트·팩트체크 패널) -->

재생 상태는 `GET /api/v1/demo/earnings-call/status?ticker=WMT` 로 볼 수 있습니다(JWT 필요). 같은 종목이 재생
중일 때 다시 시작하면 409 를 돌려줍니다. 근거 저장소가 비어 있으면 재생은 시작되고 터미널에 경고 토스트가
뜹니다.

## 자주 막히는 지점

### backend 가 MySQL 인증 오류로 뜨지 않음

`application.yml` 의 기본 계정은 `root` / `password` 이고 compose 의 root 비밀번호는 `root` 입니다.
`DB_USERNAME=user`, `DB_PASSWORD=password` 로 맞춥니다. `infra/demo-up.sh` 로 먼저 만든 `ew-mysql` 컨테이너에는
`user` 계정이 없으므로 이 경우 `root` / `root` 를 씁니다.

### `.env` 를 셸로 불러올 때 `DB_URL` 이 적용되지 않음

`DB_URL` 의 `&` 가 셸 연산자로 해석되어 대입이 백그라운드에서 실행되고, 현재 셸에는 `DB_URL` 이 설정되지
않습니다. 기본값과 같은 주소라 로컬에서는 드러나지 않지만 다른 DB 를 쓸 때는 값을 따옴표로 감쌉니다.

### 로컬 backend 를 띄웠는데 터미널이 시연 서버로 붙음

`trading-terminal/.env.example` 의 `BACKEND_URL` 이 시연 서버 주소입니다. 복사한 `.env.local` 에서 바꿔야 합니다.

### 팩트체크가 화면에 나오지 않음

backend 의 `AI_ENGINE_TIMEOUT_MS` 는 ai-engine 의 주장 추출과 검증 타임아웃 합보다 커야 합니다. 더 짧으면
ai-engine 이 작업 중일 때 backend 가 먼저 포기해 팩트체크가 조용히 사라집니다(`application.yml` 주석).
또 `FACT_CHECK_EXTRACTION_TIMEOUT_SECONDS` 를 5.0 으로 두면 실측에서 `claim_extraction_failed` 가 났습니다.

### 판정이 모두 NEUTRAL/HOLD 로 나옴

Gemini 무료 등급 키는 pro 계열 모델 할당량이 0 입니다. pro 모델을 지정하면 호출이 429 로 실패하고 엔진이
confidence 0.0 의 대체 응답을 돌려줍니다. 무료 키에서는 `.env.example` 의 flash 계열 모델을 그대로 씁니다.

### 근거 적재 중 임베딩 요청이 막힘

Gemini 무료 등급 임베딩은 하루 1,000요청이고 배치 안의 항목 하나가 1요청입니다(`ai-engine/.env.example` 주석).
한도는 한국시간 16:00 에 리셋됩니다(`ingest_demo_transcript.py` docstring). 같은 날 여러 번 적재하면 한도에 닿을 수 있습니다.

### `npm ci` 가 `EUSAGE` 로 실패함

현재 `package.json` 과 `package-lock.json` 이 맞지 않아 `npm ci` 가 실패합니다. CI 도 `npm install` 을 씁니다
(`.github/workflows/test.yml` 주석).
