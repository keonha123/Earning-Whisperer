# 웹 데모 시연 배포 절차

교수님 시연용 **웹 데모**(랜딩 + `/demo` 재생 + OAuth 로그인)를 단일 VM에 올리는 절차다.
`trading-terminal`(Electron)은 배포 대상이 아니다 — 별도 인스톨러 배포가 필요하며 현재
`import.meta.env.DEV` 게이팅 때문에 prod 빌드에 시연 기능이 포함되지 않는다.

## 배포 범위

| 올린다 | 올리지 않는다 |
|---|---|
| backend (Spring Boot, jar 직접 실행) | ai-engine (FastAPI) |
| MySQL, Redis (컨테이너) | data_pipeline (Playwright·Whisper) |
| frontend (Vercel) | PostgreSQL, Qdrant |
| Cloudflare Tunnel | trading-terminal |

ai-engine·data_pipeline을 제외하는 이유는 웹 데모 경로가 이들을 거치지 않기 때문이다.
`DemoReplayService`가 백엔드 기동 시 `mock-nvda-replay.json`을 10초 간격으로 무한 재생해
`/topic/live/demo`로 브로드캐스트하고, 프론트 `useDemoWebSocket`이 이를 수신한다.
LLM·STT 호출이 없으므로 **API 비용이 발생하지 않는다.**

## 준비물

- VM 1대 (4GB RAM으로 충분 — 파이프라인·Whisper를 올리지 않음)
- Cloudflare 계정 (무료)
- Vercel 계정 (Hobby 무료)
- Google Cloud Console / Kakao Developers 접근 권한

도메인 구매는 필요 없다. 프론트는 Vercel이 `*.vercel.app`과 TLS를 무료로 제공하고,
백엔드는 Cloudflare Tunnel이 공개 hostname과 TLS를 담당한다.

---

## 1. 계정·콘솔 작업 (본인 계정이 필요한 단계)

### 1-1. VM 생성

Oracle Cloud Always Free(ARM, 무료) 또는 임의의 저가 VM. Ubuntu 22.04 기준으로 작성했다.

```bash
sudo apt update && sudo apt install -y openjdk-21-jre-headless docker.io docker-compose-v2
sudo usermod -aG docker $USER   # 재로그인 필요
```

Java 버전은 `backend/build.gradle`의 toolchain 설정과 맞춰야 한다.

인바운드 포트는 **열지 않는다.** Cloudflare Tunnel이 아웃바운드 연결만 사용한다.

### 1-2. Cloudflare Tunnel 생성

Zero Trust 대시보드 → Networks → Tunnels → Create a tunnel (Cloudflared).

- 터널 생성 후 발급되는 **토큰**을 복사한다 → `TUNNEL_TOKEN`
- Public hostname 설정:
  - Subdomain/Domain: Cloudflare가 제공하는 것 또는 보유 도메인
  - Service: `HTTP` → `host.docker.internal:8082`
- 발급된 공개 URL을 기록해 둔다 → 이후 `API_BASE`로 사용

백엔드가 컨테이너가 아니라 호스트에서 jar로 돌기 때문에 `host.docker.internal`을 쓴다.
`docker-compose.prod.yml`의 `extra_hosts`가 이를 해석해 준다.

### 1-3. Vercel 프로젝트 생성

GitHub 저장소 연결 → Root Directory를 `frontend`로 지정 → 배포.

빌드 후 발급되는 URL을 기록한다 → 이후 `FRONT_BASE`로 사용.

환경변수 3개를 Vercel 대시보드에 등록한다.

```
NEXT_PUBLIC_API_URL=<1-2에서 받은 터널 URL>
NEXT_PUBLIC_GOOGLE_REDIRECT_URI=<FRONT_BASE>/auth/callback
NEXT_PUBLIC_KAKAO_REDIRECT_URI=<FRONT_BASE>/auth/callback
```

환경변수를 넣은 뒤 **재배포해야 반영된다.** Next.js의 `NEXT_PUBLIC_*`는 빌드 시점에
번들에 박히기 때문이다.

### 1-4. OAuth 콘솔 등록

redirect URI는 **프론트엔드 콜백 주소**다. 백엔드 주소가 아니다.

**Google Cloud Console** → API 및 서비스 → 사용자 인증 정보 → OAuth 클라이언트
- 승인된 리디렉션 URI에 `<FRONT_BASE>/auth/callback` 추가

**Kakao Developers** → 내 애플리케이션
- 플랫폼 → Web → 사이트 도메인에 `<FRONT_BASE>` 추가
- 카카오 로그인 → Redirect URI에 `<FRONT_BASE>/auth/callback` 추가

> 카카오는 **사이트 도메인 등록을 빠뜨리면** redirect URI를 넣어도 인가 단계에서 막힌다.
> 가장 흔한 실패 지점이다.

> 이 프로젝트의 카카오 앱은 개인앱이라 이메일 권한이 없다. 백엔드가
> `kakao_{id}@earningwhisperer.local` sentinel로 우회하므로 도메인이 바뀌어도
> 이 로직은 그대로 동작한다.

---

## 2. 서버 배포

### 2-1. 소스 배치

```bash
sudo mkdir -p /opt/earning-whisperer && sudo chown $USER /opt/earning-whisperer
git clone <repo> ~/Earning-Whisperer
cd ~/Earning-Whisperer
```

### 2-2. 인프라 컨테이너

```bash
cd infra
cat > .env <<'EOF'
MYSQL_ROOT_PASSWORD=<랜덤>
MYSQL_USER=user
MYSQL_PASSWORD=<랜덤>
TUNNEL_TOKEN=<1-2에서 받은 토큰>
EOF
chmod 600 .env

docker compose -f docker-compose.prod.yml up -d
docker compose -f docker-compose.prod.yml ps
```

`docker-compose.prod.yml`은 개발용 `docker-compose.yml`의 override가 아니라 독립 파일이다.
compose의 override 병합은 `ports`를 합집합으로 처리해 개발용 포트 매핑을 제거할 수 없기
때문에, 처음부터 포트를 열지 않는 별도 파일로 분리했다.

`mysql-init`도 마운트하지 않는다. `001-data-pipeline-schema.sql`이 `stocks`를
`ticker VARCHAR(20)`으로 만드는데 백엔드 JPA `Stock` 엔티티는 `VARCHAR(10)`으로
`ddl-auto: update` 하므로 충돌한다. 웹 데모는 파이프라인 테이블을 쓰지 않는다.

### 2-3. 백엔드 환경변수

`backend/.env.example`을 복사해 실제 값을 채운다.

```bash
cp backend/.env.example /opt/earning-whisperer/backend.env
chmod 600 /opt/earning-whisperer/backend.env
```

배포에서 **반드시 바꿔야 하는 값**:

| 키 | 값 | 이유 |
|---|---|---|
| `JWT_SECRET` | `openssl rand -base64 48` | 기본값이 저장소에 공개돼 있어 토큰 위조 가능 |
| `JWT_COOKIE_SECURE` | `true` | HTTPS 배포. false면 인증 쿠키 평문 전송 |
| `CORS_ALLOWED_ORIGINS` | `<FRONT_BASE>` | 없으면 브라우저가 API 응답 차단 |
| `GOOGLE_REDIRECT_URIS` | `<FRONT_BASE>/auth/callback` | 1-4와 문자 단위 일치 |
| `KAKAO_REDIRECT_URIS` | `<FRONT_BASE>/auth/callback` | 동일 |
| `DB_URL` | `jdbc:mysql://127.0.0.1:3306/earning_whisperer?...` | 컨테이너 포트를 열었을 때. 열지 않았다면 컨테이너명 사용 |
| `DB_PASSWORD` | 2-2의 `MYSQL_PASSWORD` | |
| `INTERNAL_SECRET` | `openssl rand -hex 32` | 미설정 시 `/api/v1/internal/**` 전면 차단 |

`FINNHUB_API_KEY` / `FMP_API_KEY`는 웹 데모 경로에 필요 없다. 비워 두면 해당 기능만
비활성화된다.

> `DB_URL`의 호스트: `docker-compose.prod.yml`은 기본적으로 MySQL 포트를 열지 않는다.
> 백엔드를 호스트에서 jar로 돌린다면 파일 내 주석 처리된 `127.0.0.1:3306:3306` 매핑을
> 해제하거나, 백엔드도 같은 compose 네트워크에 넣어야 한다. **`0.0.0.0` 바인딩은 금지.**

### 2-4. 백엔드 빌드·기동

```bash
cd ~/Earning-Whisperer/backend
./gradlew bootJar
cp build/libs/*.jar /opt/earning-whisperer/backend.jar

sudo cp infra/systemd/earning-whisperer-backend.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now earning-whisperer-backend
journalctl -u earning-whisperer-backend -f
```

유닛 파일의 `User`와 경로는 환경에 맞게 수정한다.

기동 로그에 `[DemoReplay] 재생 시작 - 이벤트 수=...`가 보이면 데모 재생이 동작하는 것이다.

---

## 3. 검증

| 확인 | 방법 | 기대 |
|---|---|---|
| 백엔드 살아있음 | `curl <API_BASE>/actuator/health` 또는 임의 공개 엔드포인트 | 200 |
| 터널 연결 | Cloudflare 대시보드 터널 상태 | Healthy |
| 프론트 로드 | 브라우저로 `<FRONT_BASE>` | 랜딩 표시 |
| **데모 재생** | `<FRONT_BASE>/demo` | 10초 간격으로 시그널·STT가 갱신 |
| WebSocket | 브라우저 개발자도구 Network → WS | `wss://` 연결 유지 |
| Google 로그인 | 로그인 → 마이페이지 | 프로필 표시 |
| Kakao 로그인 | 동일 | 동일 |
| 로그인 후 화면 | 관심종목 / 어닝 캘린더 | 데이터 로드 |

`/demo`가 정지 화면이면 백엔드 재생이 안 돌거나 WebSocket이 안 붙은 것이다.
둘은 브라우저 콘솔에서 구분된다.

---

## 4. 자주 막히는 지점

| 증상 | 원인 | 조치 |
|---|---|---|
| 백엔드가 즉시 죽음 | DB 연결 실패 | `DB_URL`의 DB 이름이 `earning_whisperer`인지, 컨테이너가 healthy인지 확인 |
| 프론트에서 API 호출이 CORS 오류 | `CORS_ALLOWED_ORIGINS` 미설정 | Vercel URL을 정확히(스킴 포함, 끝 슬래시 없이) 등록 |
| WebSocket 연결 실패 | mixed content 또는 터널 미설정 | `NEXT_PUBLIC_API_URL`이 `https://`인지 확인 |
| OAuth `redirect_uri_mismatch` | 3곳 불일치 | 백엔드 env / Vercel env / 콘솔 세 값을 문자 단위로 대조. 끝 슬래시 주의 |
| 카카오 로그인만 실패 | 사이트 도메인 미등록 | 카카오 콘솔 플랫폼 설정 확인 |
| 환경변수를 바꿨는데 프론트가 그대로 | `NEXT_PUBLIC_*`는 빌드 시 주입 | Vercel 재배포 |
| 로그인은 되는데 새로고침 시 풀림 | `JWT_COOKIE_SECURE` 불일치 | HTTPS면 `true` |

---

## 5. 알려진 제약

- **`ddl-auto: update`가 그대로다.** 운영에서는 `validate` + 마이그레이션 도구가 맞지만
  시연 범위에서는 유지했다. 스키마가 자동 변경될 수 있다.
- **STOMP 구독에 인증이 없다.** `StompJwtChannelInterceptor`는 CONNECT만 검사하고
  실패해도 연결을 허용하며 SUBSCRIBE 검사가 없다. `/topic/**`은 사실상 공개다.
- **서버 STOMP heartbeat가 꺼져 있다.** `enableSimpleBroker`에 `TaskScheduler`가
  없어 죽은 커넥션 탐지가 TCP에 맡겨져 있다.
- **재시작하면 DemoReplay가 처음부터 시작한다.** 무한 반복이므로 시연에는 무해하다.

---

## 부록 · VM 없이 시연하기 (로컬 + Cloudflare quick tunnel)

VM 확보가 막히거나 웹 프론트가 필요 없을 때 쓰는 경로다. 백엔드를 개발 PC 에서
띄우고 Cloudflare quick tunnel 로 공개한다. **계정이 전혀 필요 없다** — quick
tunnel 은 가입 없이 임시 공개 URL 을 발급한다.

```bash
./infra/demo-up.sh     # 컨테이너 + 백엔드 + 터널 기동, 공개 URL 출력
./infra/demo-down.sh   # 종료 (컨테이너는 stop 만, DB 데이터 보존)
```

### 언제 터널이 필요한가

| 상황 | 설정 |
|---|---|
| 백엔드와 데스크탑 앱이 **같은 PC** | 터널 불필요. `BACKEND_URL` 을 비우고 기본값(`localhost:8082`) 사용 |
| 데스크탑 앱이 **다른 PC** | `trading-terminal/.env.local` 에 `BACKEND_URL=<터널 URL>` |

### 제약

- **quick tunnel URL 은 일회용이다.** cloudflared 를 재시작하면 주소가 바뀌고
  `BACKEND_URL` 을 다시 넣어야 한다. 고정 주소가 필요하면 Cloudflare 계정과
  도메인을 등록해 named tunnel 을 만들어야 한다.
- PC 가 켜져 있는 동안만 접속된다.
- 웹 프론트를 함께 공개하려면 터널을 하나 더 열고 `NEXT_PUBLIC_API_URL` 을
  백엔드 터널로 지정한다. 단 이때 프론트와 백엔드가 서로 다른 사이트가 되어
  **refresh 쿠키(`SameSite=Strict`)가 전송되지 않는다** — access token 만료 시
  세션이 끊긴다. 데모 길이가 짧으면 문제되지 않는다.

### 데스크탑 앱 시연 시 유의

- 어닝콜 시연 UI 4종(팩트체크·파급효과·발화자·종합평가)은
  `import.meta.env.DEV` 게이팅이라 **`npm run dev` 에서만 표시된다.**
  패키징한 인스톨러에서는 보이지 않는다.
- 백엔드의 `DemoReplayService` 는 웹 프론트용(`/topic/live/demo`)이며
  데스크탑 앱은 이 토픽을 구독하지 않는다. 앱에서 백엔드가 담당하는 것은
  로그인·포트폴리오·시세·거래내역이다.
- 앱의 OAuth 는 loopback(`http://localhost:9000/auth/callback`)을 쓰므로
  터널 주소와 무관하다. 백엔드 `GOOGLE_REDIRECT_URIS` / `KAKAO_REDIRECT_URIS`
  에 이 loopback 주소가 포함돼 있어야 한다.

### 트러블슈팅

| 증상 | 원인 |
|---|---|
| 백엔드 기동 직후 DB 연결 실패 | `.env` 값에 따옴표가 없으면 `DB_URL` 의 `&` 를 셸이 백그라운드 연산자로 해석해 URL 이 잘린다. 값을 `'...'` 로 감쌀 것 |
| 터널 URL 로 502 | 백엔드가 아직 기동 중이거나 죽음. `/tmp/ew-backend.log` 확인 |
| WebSocket 연결 실패 | `BACKEND_URL` 이 `https://` 여야 `wss://` 로 변환된다 (`StompService.ts` 가 `^http` → `ws` 치환) |
