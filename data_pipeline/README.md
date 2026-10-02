# Data Pipeline

data_pipeline/
├── __init__.py
├── collectors/              # [수집 레이어] 다양한 소스에서 데이터 및 URL 확보
│   ├── __init__.py
│   ├── base.py              # Collector 추상 클래스 및 Chain 로직
│   ├── stocks/              # 종목 리스트 확보 (Wikipedia 등)
│   ├── indicators/          # 정적 지표 연산 (52주 고점, 거래량 등)
│   ├── schedules/           # 어닝 일정 수집 (yfinance 등)
│   ├── prices/              # 주가 데이터 수집 (Ground Truth용)
│   └── streams/             # IR 페이지와 웹캐스트 재생 경로 탐색
│
├── stt_worker/              # [처리 레이어] 실시간 오디오-텍스트 변환 별동대
│   ├── __init__.py
│   ├── manager.py           # 브라우저·오디오 캡처 워커 생명주기 관리
│   └── take.py              # PulseAudio/FFmpeg 입력과 Whisper STT 처리
│
├── tools/                   # 운영 서버와 분리된 검증·학습·디버그 도구
│   ├── replay/               # 과거 웹캐스트 후보 탐색 및 재생 검증
│   ├── learning/             # 레시피 학습·진단·일반화 벤치마크
│   ├── debug/                # 관찰 가능한 브라우저 실행 도구
│   ├── mock/                 # 로컬 웹캐스트 E2E 테스트
│   └── legacy/               # 운영 경로에서 분리한 구형 수집기
│
├── database.py              # [저장 레이어] SQLAlchemy 기반 DB 매니저 및 모델 정의
├── orchestrator.py          # [지휘 레이어] 수집·감시·STT 실행 조합
├── scheduler.py             # [제어 레이어] 시간/이벤트 기반 트리거
├── maintenance.py           # 보관 기간과 탐색 산출물 정리
└── operations.py            # 운영 이벤트와 일일 리포트

## 웹캐스트 관찰 모드

브라우저 탐색, 버튼 선택, 등록 폼 처리, 재생 시도, 가상 오디오 검사를 한 화면에서
확인하려면 다음 명령을 실행합니다.

```bash
data_pipeline/scripts/run_visible_webcast.sh \
  --ticker ISRG \
  --url "https://edge.media-server.com/mmc/p/dekvotz4/"
```

기본 관찰 화면은 `http://127.0.0.1:8765`에서 열립니다. 왼쪽에는 실제 Docker
Chromium 화면이 표시되고 오른쪽에는 현재 단계와 실행 로그가 표시됩니다. 접근 확인이나
쿠키 동의처럼 사람의 확인이 필요한 경우 브라우저 화면에서 처리한 후 `탐색 계속`을
누릅니다. `중지`는 현재 관찰 대상 컨테이너만 종료합니다.

주요 옵션:

```text
--port 8765          관찰 화면 포트
--vnc-port 6080      실제 브라우저 화면 포트
--lifecycle replay   unknown, pre_live, live, replay
--auto-start         관찰 화면을 연 뒤 탐색을 자동으로 시작
--auto-start-delay 5 자동 탐색 전 관찰 대기 시간(초)
--failure-hold 60   실패·등록 필요 화면을 유지할 시간(초)
--success-hold 60   오디오 성공 후 브라우저를 유지할 시간(초)
--with-stt           오디오 검증 후 STT까지 계속 실행
--allow-registration-submission
                     현재 대상의 외부 등록 폼 제출을 명시적으로 허용
--no-open            관찰 화면을 자동으로 열지 않음
--keep-container     관찰 서버 종료 후에도 브라우저 컨테이너 유지
```

기본값에서는 개인정보가 포함된 등록 폼을 채우거나 제출하지 않습니다. 자동 관찰만
실행하려면 `--auto-start`를 사용하며, 등록 제출이 필요한 단일 대상을 충분히 확인한
경우에만 `--allow-registration-submission`을 함께 사용합니다.

`--lifecycle replay`에서는 날짜가 확인되는 미래 이벤트를 제외하고 가장 최근의 과거
어닝콜을 선택합니다. 과거 이벤트가 별도 탭에 있는 사이트는 `Past Events`,
`Previous Events`, `Archived Events` 보기를 먼저 연 뒤 재생 후보를 다시 수집합니다.
Q4 인증 대상만 다시 확인할 때는 배치 명령에 `--auth-required-only
--retry-auth-required`를 함께 사용합니다.

전체적인 data_pipeline 흐름:
수집기는 종목·일정·시장 데이터를 가져오고, `orchestrator.py`가 결과를 DB에 저장하거나 웹캐스트 감시로 연결합니다. `scheduler.py`는 정기 수집과 임박한 어닝콜 감시를 실행합니다. 감시 대상이 실제 재생 가능한 상태가 되면 `stt_worker`가 Docker 브라우저의 PulseAudio 가상 장치에서 오디오를 읽고 Whisper STT 결과를 저장합니다.

collector 흐름:
collector에는 수집할 여러가지 정보들을 기준으로 디렉토리가 존재하고 각각의 디렉토리는 해당 정보들을 어떻게 수집할지를 구현한 함수들이 있습니다. 이 함수들은 ex) self.price_chain = CollectorChain([YFinancePriceStrategy()])#orchestrator의 18 line에서 처럼 여러 방법들을 체인으로 엮어서 몃가지 수집방법이 api포화나 네트워크에러가 발생해서 작동하지 못해도 다른 방식이 체인으로 작동하기에 해당정보를 안정적으로 수집합니다.

stt_worker 흐름:
1. `manager.py`가 브라우저 캡처 프로세스의 생명주기를 관리합니다.
2. `run_webcast_audio_capture.sh`가 Docker 안에 PulseAudio 가상 출력 장치를 준비합니다.
3. `take.py`가 해당 monitor 입력을 FFmpeg로 읽고 Whisper로 변환합니다.
4. 변환된 청크는 중복 방지 키와 보관 정책을 적용해 DB에 저장합니다.

브라우저 기반 웹캐스트 탐색:
Ubuntu 26.04 호스트에서는 Playwright 기본 Chromium 설치가 지원되지 않을 수 있으므로, IR 사이트 탐색은 Docker의 `browser-webcast` 서비스에서 실행할 수 있습니다.

```bash
docker compose -f infra/docker-compose.yml --profile tools build browser-webcast

docker compose -f infra/docker-compose.yml --profile tools run --rm browser-webcast \
  python -m data_pipeline.collectors.streams.browser_webcast \
  --ticker MMM \
  --ir-url "https://investors.3m.com/news-events/events-presentations" \
  --json
```

일반 웹캐스트 등록 정보는 `data_pipeline/.env`의 `WEBCAST_EMAIL`, `WEBCAST_PASSWORD`, `WEBCAST_FIRST_NAME`, `WEBCAST_LAST_NAME`, `WEBCAST_COMPANY`에 넣습니다. Q4 계정이 별도라면 `Q4_EMAIL`, `Q4_PASSWORD`, `Q4_FIRST_NAME`, `Q4_LAST_NAME`을 사용하며, Q4 인증 화면에서만 이 값을 우선 적용합니다. 컨테이너는 저장소를 `/app`으로 마운트하므로 기존 `.env` 파일을 그대로 읽습니다.
기존에 `auth_required`로 분류된 대상을 자격정보 설정 후 다시 검증할 때는 과거 리플레이 배치에 `--retry-auth-required`를 추가합니다.
일부 등록 폼의 분류 선택은 `WEBCAST_INDUSTRY_AFFILIATION`으로 지정하며 기본값은 `Other`입니다.

IR 사이트가 미디어 URL을 숨기거나 세션/보안 정책 때문에 `.m3u8` 같은 스트림 주소를 안정적으로 잡기 어려운 경우에는 OS 오디오 캡처 방식으로 실행합니다. 이 모드는 컨테이너 안에서 PulseAudio 가상 출력 장치(`ew_webcast`)를 만들고, 브라우저가 재생하는 소리를 `ew_webcast.monitor`에서 ffmpeg/STT가 직접 읽습니다.
브라우저가 영상은 재생하지만 Chromium 오디오가 PulseAudio sink-input을 만들지 않는 경우에는, 재생 중 발견한 동일한 `.m3u8`/`.mpd`를 `ew_webcast`로 재생하는 보조 fallback이 자동으로 시도됩니다. 이때도 최종 판정은 `ew_webcast.monitor`의 비무음 신호입니다.

```bash
docker compose -f infra/docker-compose.yml --profile tools run --rm browser-webcast \
  data_pipeline/scripts/run_webcast_audio_capture.sh \
  MMM \
  "https://investors.3m.com/news-events/events-presentations" \
  --model-name tiny \
  --no-ai-engine \
  --no-backend
```

운영 환경에서는 `--model-name tiny`, `--no-ai-engine`, `--no-backend`를 제거하거나 `.env`의 `STT_MODEL_NAME`, `SEND_TO_AI_ENGINE`, `SEND_TO_BACKEND` 설정을 사용합니다. 브라우저 준비 시간을 늘려야 하면 `WEBCAST_AUDIO_WARMUP_SECONDS`, 재생 유지 시간을 늘려야 하면 `WEBCAST_HOLD_SECONDS`를 조정합니다.

날짜 기반 감시는 시작 시각을 추정해 바로 STT를 실행하지 않습니다. 어닝 날짜가 오늘 또는 다음 날인 종목만 Docker 브라우저로 열고, 실제 재생 소리가 `ew_webcast.monitor`에 들어왔을 때만 `AUDIO_DETECTED`로 판정합니다. 스케줄러는 **Docker를 실행할 수 있는 호스트**에서 실행해야 합니다.

```bash
ENABLE_DATE_STREAM_WATCH=true \
DATE_STREAM_WATCH_DAYS_AHEAD=2 \
DATE_STREAM_AUDIO_WAIT_SECONDS=90 \
python -m data_pipeline.scheduler
```

정확한 공식 시작 시각이 저장된 종목은 이벤트 전후 감시 주기를 자동으로 줄입니다.
기본값은 시작 20분 전부터 종료 180분 후까지 1분 간격이며, 시간이 아직 확정되지
않은 종목은 `DATE_STREAM_WATCH_COOLDOWN_MINUTES` 주기를 사용합니다.

```bash
DATE_STREAM_NEAR_START_MINUTES=20
DATE_STREAM_NEAR_END_MINUTES=180
DATE_STREAM_NEAR_INTERVAL_MINUTES=1
DATE_STREAM_MAINTENANCE_START=03:00
DATE_STREAM_MAINTENANCE_END=04:00
```

정비 시간 설정은 새 브라우저 probe만 잠시 멈추고 이미 실행 중인 STT worker는 계속
동작시킵니다. 감시 결과는 `data_pipeline/.runtime/operations/`에 날짜별 JSONL로
쌓이며, 매일 기본 UTC 23:55에 `report-YYYY-MM-DD.json`과 Markdown 요약을 생성합니다.
수동으로 리포트를 만들려면 다음 명령을 사용합니다.

```bash
data_pipeline/scripts/build_daily_report.sh
```

`DATE_STREAM_AUTO_CAPTURE_ENABLED=false`로 두면 실제 소리 감지까지만 하고 STT 컨테이너는 시작하지 않습니다. 수동 점검은 아래처럼 할 수 있습니다.

```bash
docker compose -f infra/docker-compose.yml --profile tools run --rm browser-webcast \
  data_pipeline/scripts/run_webcast_audio_capture.sh --probe-only \
  MMM "https://investors.3m.com/news-events/events-presentations"
```

상시 운영은 Docker Compose의 `ops` 프로필로 실행합니다. `data_pipeline/.env`에
감시 옵션을 넣은 뒤 스케줄러 컨테이너를 시작하면, 브라우저와 PulseAudio를 같은
운영 컨테이너에서 사용하면서 일정 감시와 STT worker를 계속 실행합니다.

```bash
ENABLE_DATE_STREAM_WATCH=true
DATE_STREAM_AUTO_CAPTURE_ENABLED=true
WEBCAST_CAPTURE_RUNNER=container
DATE_STREAM_WATCH_BATCH_SIZE=500

docker compose -f infra/docker-compose.yml --profile ops up -d --build pipeline-scheduler
docker compose -f infra/docker-compose.yml logs -f pipeline-scheduler
```

운영 컨테이너는 `restart: unless-stopped`로 설정되어 있으며, 종료 전까지 실행 중인
worker를 유지합니다. 실제 운영에서는 `data_pipeline/.env`의 `AI_ENGINE_URL`,
`BACKEND_URL`, `INTERNAL_SECRET`을 실제 서비스 값으로 지정해야 합니다.

### 웹캐스트 레시피 학습

웹캐스트 버튼은 소스 코드에 사이트별로 하드코딩하지 않습니다. 레시피가 없는 IR 도메인은 브라우저가 화면 스냅샷과 클릭 가능 DOM 후보를 수집하고, 후보를 새 브라우저 컨텍스트에서 다시 실행합니다. 이후 PulseAudio에서 실제 음성이 감지된 경우에만 MySQL의 `webcast_recipes` 레코드를 `verified`로 승격합니다. 다음 실행부터는 검증된 레시피를 우선 사용하며, 오디오 실패가 세 번 누적되면 해당 레시피는 자동 비활성화됩니다.
오디오 검증이 끝난 레시피에 외부 플레이어 주소가 함께 기록된 경우에는 IR 페이지가 CDN 차단으로 열리지 않아도 해당 플레이어로 바로 진입할 수 있습니다. 등록폼 제출과 브라우저 재생을 먼저 확인한 뒤 오디오 판정을 수행합니다.

화면 AI 선택은 선택 기능입니다. 기본값은 DOM 텍스트/접근성 속성 기반 후보 점수화이고, AI를 켜려면 아래 값을 `.env`에 설정합니다. 스크린샷과 후보 메타데이터는 `data_pipeline/.artifacts/webcast/`에 남으므로 해당 경로는 운영 환경에서 제한된 저장소로 관리해야 합니다.

```bash
WEBCAST_VISION_ENABLED=true
OPENAI_API_KEY=...
WEBCAST_VISION_MODEL=gpt-5.6-luna
WEBCAST_VISION_MIN_CONFIDENCE=0.55
```

AI는 화면에서 후보를 고르는 데만 사용합니다. 실제 클릭은 모델이 만든 코드가 아니라 DOM에서 추출한 선택자로 수행하며, 최종 성공 판정은 여전히 가상 오디오 장치의 비무음 신호입니다. CDN 차단, CAPTCHA, 권한 거부 페이지는 자동으로 `page access blocked` 상태로 기록하고 레시피 후보로 저장하지 않습니다.

### 과거 리플레이 학습

예정된 라이브 화면과 과거 리플레이 화면은 다를 수 있으므로, 과거 콜은 별도 대상 테이블에서 검증합니다. 먼저 Serper로 회사 IR 도메인 또는 알려진 웹캐스트 제공사의 직접 재생 페이지, 웹캐스트 아카이브, 공식 실적 발표문 진입점을 찾고, 그 다음 브라우저와 PulseAudio 가상 장치로 실제 음성을 확인합니다. 이 경로는 OpenAI API를 사용하지 않습니다.

```bash
docker compose -f infra/docker-compose.yml --profile tools run --rm browser-webcast \
  python -m data_pipeline.tools.replay.replay_discovery --limit 30

# Cloudflare 등으로 회사 IR 도메인이 막힌 특정 종목은 신뢰 제공사 URL도 별도 탐색
docker compose -f infra/docker-compose.yml --profile tools run --rm browser-webcast \
  python -m data_pipeline.tools.replay.replay_discovery \
  --tickers ISRG --provider-fallback

# 기본 검색에서 후보가 없던 종목만 외부 신뢰 공급자에서 한 번 더 탐색
docker compose -f infra/docker-compose.yml --profile tools run --rm browser-webcast \
  python -m data_pipeline.tools.replay.replay_discovery \
  --discovery-statuses no_candidate --provider-fallback-only --force

# 검색엔진에 플레이어 URL이 없으면 기존 IR 페이지를 브라우저 탐색 진입점으로 사용
python -m data_pipeline.tools.replay.replay_discovery \
  --discovery-statuses no_candidate --seed-ir-entrypoints

docker compose -f infra/docker-compose.yml --profile tools run --rm \
  -e WEBCAST_CAPTURE_RUNNER=container browser-webcast \
  python -m data_pipeline.tools.replay.historical_replay_learning_batch --concurrency 1
```

성공한 선택자는 `lifecycle=replay` 레시피로만 검증 완료 처리됩니다. 라이브 감시에서는 `live` 레시피를 우선 적용하고, 같은 도메인의 검증된 리플레이 레시피는 보조 후보로만 사용합니다. Cloudflare/CAPTCHA처럼 사람 검증이 필요한 URL은 `blocked`로 기록하되, 같은 도메인의 다른 후보 URL은 계속 검증합니다.

### Transcript 보관 및 용량 정책

실시간 STT 결과는 `TRANSCRIPT_ARCHIVE_ENABLED=true`일 때 텍스트 청크만
`transcript_segments` 테이블에 저장됩니다. 오디오 원본은 저장하지 않으며,
`call_id + sequence`를 유일키로 사용해 재전송에도 중복 행이 생기지 않습니다.

기본 보관 기간은 180일입니다. 스케줄러가 매일 오래된 청크를 최대 10,000건씩
정리하므로 한 번의 대량 삭제로 운영 DB를 오래 잠그지 않습니다.

```bash
TRANSCRIPT_RETENTION_DAYS=180
TRANSCRIPT_PURGE_BATCH_SIZE=10000
TRANSCRIPT_PURGE_MAX_BATCHES=10
```

브라우저 학습 중 생성되는 화면 캡처와 DOM 후보 JSON은 기본 14일 또는 최대
2,000개 그룹까지만 보관합니다. 필요하면 다음 값으로 조정할 수 있습니다.

```bash
WEBCAST_ARTIFACT_RETENTION_DAYS=14
WEBCAST_ARTIFACT_MAX_GROUPS=2000
```

DB가 일시적으로 unavailable인 경우에도 실시간 백엔드/AI 전송은 계속되고,
보관 실패만 로그로 남긴 뒤 다음 청크에서 재시도합니다.

### 로컬 웹캐스트 E2E 테스트

실제 어닝콜을 기다리지 않고 등록폼, 재생 버튼, 가상 오디오 감지까지 확인하려면
브라우저 컨테이너 안에서 로컬 테스트 페이지를 실행합니다. 이 테스트는 `EWTEST`
티커를 DB에 추가하고 날짜 기반 감시 로직으로 해당 페이지를 탐색합니다.

```bash
docker compose -f infra/docker-compose.yml --profile tools run --rm \
  -e WEBCAST_CAPTURE_RUNNER=container \
  browser-webcast \
  bash data_pipeline/scripts/run_mock_webcast_e2e.sh
```

성공하면 `MOCK_WEBCAST_E2E_PASS`가 출력됩니다. 테스트 레코드를 자동 삭제하려면
다음 환경변수를 추가합니다.

```bash
MOCK_WEBCAST_CLEANUP=true
```

기본 테스트는 브라우저 재생과 OS 오디오 감지만 확인합니다. 영어 음성 합성, Whisper,
transcript 보관, 분석/백엔드 전달까지 실행하려면 다음 옵션을 추가합니다.

```bash
docker compose -f infra/docker-compose.yml --profile tools run --rm \
  -e WEBCAST_CAPTURE_RUNNER=container \
  -e MOCK_WEBCAST_CLEANUP=true \
  browser-webcast \
  bash data_pipeline/scripts/run_mock_webcast_e2e.sh --with-stt
```

STT 모드는 컨테이너의 `espeak-ng`로 영어 음성을 만들고 `tiny` Whisper를 한 청크만
실행합니다. 분석/백엔드 URL은 테스트용 수신 endpoint를 사용하며, 실제 서비스의
계약 검증은 별도의 백엔드 통합 테스트에서 수행합니다.

예정 시각 전의 페이지와 라이브 전환 후의 페이지를 같은 IR 주소에서 순서대로
확인하려면 다음처럼 실행합니다. 첫 번째 감시 주기는 `NOT_LIVE_YET`를 기록하고,
예정 시각이 지나면 다음 주기에 등록폼, 재생, PulseAudio, STT까지 진행합니다.

```bash
docker compose -f infra/docker-compose.yml --profile tools run --rm \
  -e WEBCAST_CAPTURE_RUNNER=container \
  -e MOCK_WEBCAST_CLEANUP=true \
  browser-webcast \
  bash data_pipeline/scripts/run_mock_webcast_e2e.sh \
  --with-stt --scheduled-delay-seconds 30 --poll-interval-seconds 5
```

이 모드는 실제 운영 스케줄러의 10분 주기를 기다리는 대신 테스트 전용으로 probe
재시도 간격을 짧게 조정합니다. `monitor_attempts >= 2`, 첫 시도의
`NOT_LIVE_YET`, 최종 `stream_ready`, transcript 저장을 모두 성공 조건으로 검사합니다.

database.py 흐름:
collector의 각각의 하위 디렉토리에서 수집하는 정보에 대응하는 함수들로 구성되어있고 각각의 mysql에 접근해서 테이블에 저장합니다.

ㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡ



# 🎧 Data Pipeline (데이터 수집 서버) 요구사항 정의서

데이터 서버가 가지는 데이터
1. S&P500기업 리스트
2. 각 기업의 어닝콜 일정
3. 각 기업의 주가정보
4. 각 기업의 어닝콜 동영상

데이터 서버의 흐름
1. 각 데이터별 수집 단계
-1 정보원, 이 정보원들을 4~5가지를 체인룰로 엮어서 안정성과 신뢰성을 확보
-2 검증툴, 신뢰성 확보
-3 자동화툴

-1 정보원의 종류
-1-1 크롤링 위키피디아,각 공식 사이트 주소
-1-2 api활용 ,fmp,finnhub,alpha,polygon,lex
-1-3 라이브러리 야후

-2 검증툴
3개의 정보원의 정보가 모두 일치하면 통과
다르다면 다수결로 결정, 우선순위 체인으로 결정


-3 자동화툴
python APscheduler을 사용해서 정해진 시간과 주기로 정보툴을 호출


2. 저장 단계
데이터베이스에 수집한 정보를 저장

3. 전달 단계


ㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡ
## 1. 모듈의 역할 및 목표
이 모듈은 EarningWhisperer 프로젝트의 '귀' 역할을 담당합니다. 
유튜브 라이브나 오디오 스트림에서 실시간으로 기업의 어닝콜(실적 발표) 음성을 수집하고, 이를 초고속 STT(Speech-to-Text) 모델을 통해 텍스트로 변환한 뒤, 문맥이 유지되도록 가공하여 AI 추론 서버(AI Engine)로 전달하는 것이 핵심 목표입니다.

## 2. 핵심 기능 요구사항 (Core Features)

### [Feature 1] 실시간 오디오 스트리밍 캡처
- 대상 기업의 어닝콜 라이브 방송(주로 YouTube Live 또는 웹 캐스트) 오디오를 메모리 상에서 실시간으로 스트리밍하여 가져옵니다.
- **제약사항:** 영상(Video) 트래픽은 배제하고 오디오(Audio) 스트림만 추출하여 시스템 리소스를 최적화해야 합니다.

### [Feature 2] 초저지연 STT (Speech-to-Text) 변환
- 수집된 오디오 버퍼를 실시간으로 텍스트로 변환합니다.
- **추천 모델:** 일반 Whisper 대비 추론 속도가 압도적으로 빠른 **`faster-whisper`** (CTranslate2 엔진 기반)를 로컬 GPU 환경에서 구동합니다.
- **제약사항:** 금융/경제 영어 어휘의 인식률을 높여야 하며, 오디오 수신 후 텍스트 변환까지의 지연 시간(Latency)을 최소화해야 합니다.

### [Feature 3] 슬라이딩 윈도우(Sliding Window) 텍스트 청킹
- 끊임없이 이어지는 STT 텍스트를 단순히 시간 단위로 자를 경우 발생하는 **'문맥 단절(Context Fragmentation)'**을 방지해야 합니다.
- **슬라이딩 윈도우 적용:** 약 10~15초 단위의 Chunk를 생성하되, 직전 Chunk의 마지막 5~7초가량의 텍스트가 현재 Chunk의 앞부분에 **오버랩(Overlap)** 되도록 텍스트 조각을 묶어야 합니다.
- 가공된 텍스트 윈도우를 AI Engine의 REST API로 **비동기 전송(`POST`)**하여 데이터 수집 파이프라인이 블로킹(Blocking)되지 않도록 합니다.

## 3. 입출력 명세 (I/O Specification)
- **Input:** YouTube Live URL 또는 실시간 오디오 스트림 소스
- **Output:** AI 엔진으로 보내는 비동기 HTTP POST Request (`docs/api-spec.md`의 파이프라인 1번 규격 엄수)

## 4. 기술 스택 (Python)
- **Audio Capture:** `yt-dlp` (유튜브 스트림 추출), `ffmpeg-python` (오디오 포맷 및 버퍼 처리)
- **STT Engine:** `faster-whisper` (초저지연 음성 인식)
- **Network/Async:** `asyncio`, `httpx` 또는 `aiohttp` (비동기 HTTP API 통신용)

## 5. 완료 기준 (Definition of Done - DoD)
이 모듈의 개발이 완료되었다고 평가받으려면 다음 테스트를 통과해야 합니다.
1. [ ] **스트리밍 테스트:** 과거 테슬라나 엔비디아의 어닝콜 유튜브 라이브(또는 녹화본) URL을 입력했을 때, 메모리 누수 없이 오디오 스트림을 지속적으로 캡처하는가?
2. [ ] **STT 속도/정확도 테스트:** 영어 오디오가 `faster-whisper`를 거쳐 텍스트로 정상 변환되며, 금융 용어(EBITDA, Margin 등)가 비교적 정확히 인식되는가?
3. [ ] **슬라이딩 윈도우 및 비동기 전송 테스트:** 변환된 텍스트가 이전 문맥과 오버랩된 채로 10~15초 주기로 나뉘며, AI 서버로 전송 시 파이프라인 병목(Blocking) 없이 1초 이내에 비동기 전송되는가?
