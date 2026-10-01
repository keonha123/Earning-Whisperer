# Data Pipeline

이 파이프라인은 기능별 부품을 `orchestrator.py`에서 조립한다. 상세한 책임, 실행 흐름,
수정 위치는 [ARCHITECTURE.md](ARCHITECTURE.md)를 먼저 참고한다. 라이브 웹 감시 문제만
추적할 때는 [LIVE_WATCH_GUIDE.md](LIVE_WATCH_GUIDE.md)를 사용한다.
실시간 수집의 최근 변경·설정·검증 범위는 [LIVE_WATCH_IMPROVEMENTS.md](LIVE_WATCH_IMPROVEMENTS.md)에 정리했다.

```text
data_pipeline/
├── application/             # 일정, 감시, 시장 데이터, 운영 업무 조합
├── collectors/              # 외부 데이터와 웹 페이지 증거 수집
│   └── streams/browser/     # 세션, 후보, 등록, 재생, 학습 단계
├── storage/                 # MySQL 연결, 스키마, 상태와 결과 저장
├── stt_worker/              # 캡처 프로세스, STT, durable delivery
├── tools/                   # 리플레이 학습, 진단, 관찰, 로컬 mock
├── scripts/                 # Docker/PulseAudio/FFmpeg 실행 경계
├── tests/                   # 단위, 조립, 실제 Chromium 회귀 테스트
├── scheduler.py             # 정기 작업과 1분 라이브 감시 진입점
├── orchestrator.py          # 부품 조립 및 스케줄러 공개 API
└── database.py              # 기존 import를 위한 storage 호환 API
```

## 웹캐스트 관찰 모드

브라우저 탐색, 버튼 선택, 등록 폼 처리, 재생 시도, 가상 오디오 검사를 한 화면에서
확인하려면 다음 명령을 실행합니다.

```bash
data_pipeline/scripts/run_visible_webcast.sh \
  --ticker ISRG \
  --url "https://edge.media-server.com/mmc/p/dekvotz4/"
```

자동 탐색이 막힌 지점에서 직접 조작하고, 같은 브라우저 세션에서 자동화를 재개하려면
`--human-loop`를 추가합니다.

```bash
data_pipeline/scripts/run_visible_webcast.sh \
  --ticker ISRG \
  --url "https://edge.media-server.com/mmc/p/dekvotz4/" \
  --human-loop \
  --allow-registration-submission \
  --with-stt
```

이 모드에서는 재생 후보·접근 차단·등록폼·플레이어 활성화·오디오 미검출 단계에서
`HUMAN_HANDOFF`로 대기합니다. 왼쪽 실제 브라우저에서 필요한 조작을 마친 뒤 오른쪽의
`바톤 반환`을 누르면 새로 열린 탭을 우선하고, 새 탭이 없다면 마지막 사람 클릭이 발생한
탭을 접근 차단·이벤트 목록·등록폼·플레이어 중 하나로 다시 분류해 해당 단계에서 자동
탐색을 이어갑니다. 클릭·입력·선택 이벤트는 값 자체를 제외한
페이지/프레임 URL, 텍스트, 선택자 힌트만
`data_pipeline/.runtime/operations/human-loop/`에 JSONL로 기록합니다. 여러 번의 클릭은
순서가 있는 `human_workflow`로 묶입니다. 과거 어닝콜 선택은 등록폼이나 플레이어 도달
시점에 독립적으로 검증되고, 재생 클릭은 실제 플레이어 활성화가 확인된 뒤 저장됩니다.
따라서 뒤 단계가 실패해도 이미 통과한 앞 단계의 경로는 다음 실행에서 재사용할 수 있습니다.

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
--human-loop         막힘마다 사람에게 바톤을 넘기고 조작 기록을 남김
--allow-registration-submission
                     현재 대상의 외부 등록 폼 제출을 명시적으로 허용
--no-open            관찰 화면을 자동으로 열지 않음
--keep-container     관찰 서버 종료 후에도 브라우저 컨테이너 유지
```

일반 수집기의 기본값은 설정된 참가자 정보로 등록폼을 자동 제출하는 것입니다.
운영 설정은 `WEBCAST_ALLOW_REGISTRATION_SUBMISSION=true`,
`WEBCAST_REGISTRATION_REQUIRE_APPROVAL=false`이며 종목별 승인 파일이 필요하지 않습니다.
위 관찰 도구와 훈련 배치처럼 명시적으로 제출을 끄는 진단 도구는
`--allow-registration-submission` 옵션으로 제출을 켤 수 있습니다.
`registration-preview-only`와 `discovery-only`는 전역 설정과 무관하게 제출하지 않습니다.
등록 제출을 허용한 실행은 새 탭과 공급자 측 지연 리다이렉트를 고려해 기본 120초까지
기다립니다. 필요하면 `WEBCAST_REGISTRATION_TIMEOUT_SECONDS`로 조정할 수 있습니다.

`--lifecycle replay`에서는 날짜가 확인되는 미래 이벤트를 제외하고 가장 최근의 과거
어닝콜을 선택합니다. 과거 이벤트가 별도 탭에 있는 사이트는 `Past Events`,
`Previous Events`, `Archived Events` 보기를 먼저 연 뒤 재생 후보를 다시 수집합니다.
실제 과거 어닝콜을 찾기 전에 사람이 비실적 webcast의 등록폼이나 플레이어까지 이동한
경우에는 이를 뒤쪽 등록·재생·오디오 단계를 검증하는 훈련용 대체 이벤트로 허용합니다.
이때 비실적 이벤트 선택 경로는 어닝콜 선택 레시피로 저장하지 않고, 검증된 등록·재생
단계만 학습합니다. `live`와 `pre_live`에서는 이 예외를 적용하지 않습니다.
Q4 인증 대상만 다시 확인할 때는 배치 명령에 `--auth-required-only
--retry-auth-required`를 함께 사용합니다.

전체적인 data_pipeline 흐름:
수집기는 종목·일정·시장 데이터를 가져오고, `application` 서비스가 결과를 DB에 저장하거나
웹캐스트 감시로 연결합니다. `scheduler.py`는 정기 수집과 임박한 어닝콜 감시를 실행합니다.
감시 대상에서 실제 소리가 확인되면 `stt_worker`가 Docker 브라우저의 PulseAudio 가상 장치에서
오디오를 읽고 Whisper STT 결과를 저장합니다.

collector 흐름:
collector는 수집할 정보 종류별 전략을 제공합니다. 현재 각 `CollectorChain`에 여러 fallback이
항상 등록되어 있는 것은 아니므로, 새 공급자를 추가할 때 기존 전략과 함께 체인에 조립해야 합니다.

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

일반 웹캐스트 등록 정보는 `data_pipeline/.env`의 `WEBCAST_EMAIL`, `WEBCAST_PASSWORD`, `WEBCAST_FIRST_NAME`, `WEBCAST_LAST_NAME`, `WEBCAST_COMPANY`에 넣습니다. 전화번호를 요구하는 폼은 `WEBCAST_PHONE`을 사용하며, 컨테이너는 저장소를 `/app`으로 마운트하므로 기존 `.env` 파일을 그대로 읽습니다. 단일 이름 필드는 이름과 성을 합쳐 사용하고, 직책 필드는 `WEBCAST_JOB_TITLE`을 사용하며 기본값은 `Investor`입니다. Q4 계정이 별도라면 `Q4_EMAIL`, `Q4_PASSWORD`, `Q4_FIRST_NAME`, `Q4_LAST_NAME`을 사용하며, Q4 인증 화면에서만 이 값을 우선 적용합니다.
기존에 `auth_required`로 분류된 대상을 자격정보 설정 후 다시 검증할 때는 과거 리플레이 배치에 `--retry-auth-required`를 추가합니다.
일부 등록 폼의 분류 선택은 `WEBCAST_INDUSTRY_AFFILIATION`으로 지정하며 기본값은 `Other`입니다. `Attendee Type`처럼 추가 필수 선택지가 있는 폼은 `WEBCAST_ATTENDEE_TYPE`을 사용하며 기본값은 `Other`이고, `Select One` 유형의 추가 선택지는 `WEBCAST_OTHER_OPTION`으로 지정하며 기본값은 `Other`입니다. 해당 값이 옵션에 없으면 빈 placeholder가 아닌 첫 유효 옵션을 선택합니다. 등록 제출 뒤 새 플레이어 탭이나 지연된 iframe을 기다리는 시간은 `WEBCAST_POST_REGISTRATION_PLAYBACK_WAIT_SECONDS`로 조정하며 기본값은 30초입니다. 같은 페이지에 플레이어가 늦게 마운트되는 경우 `WEBCAST_PLAYBACK_RETRY_INTERVAL_SECONDS` 간격으로 재생 활성화를 다시 시도하며 기본값은 5초입니다. 포털형 웹캐스트의 `View Now`와 HLS 직접 미디어 fallback도 이 단계에서 처리합니다.
등록 제출 응답이 늦게 반영되는 공급자는 `WEBCAST_REGISTRATION_POST_SUBMIT_WAIT_SECONDS`로 제출 후 같은 페이지의 상태를 재확인하는 시간을 조정할 수 있으며 기본값은 30초입니다.

IR 사이트가 미디어 URL을 숨기거나 세션/보안 정책 때문에 `.m3u8` 같은 스트림 주소를 안정적으로 잡기 어려운 경우에는 OS 오디오 캡처 방식으로 실행합니다. 이 모드는 컨테이너 안에서 어닝콜별 PulseAudio 런타임과 가상 출력 장치(`ew_webcast_<call>.monitor`)를 만들고, 브라우저가 재생하는 소리를 해당 monitor에서 ffmpeg/STT가 직접 읽습니다. 따라서 동시에 진행되는 어닝콜이 서로의 기본 sink를 바꾸지 않으며, 한 캡처의 PulseAudio 장애가 다른 캡처로 전파되지 않습니다.
브라우저가 영상은 재생하지만 Chromium 오디오가 PulseAudio sink-input을 만들지 않는 경우에는,
현재 세션에서 발견한 `.m3u8`/`.mpd`를 우선하고 probe에서 넘긴 후보를 보조로 사용합니다.
첫 URL이 만료되거나 차단되면 다음 후보를 시도하며, 브라우저의 Referer와 세션 쿠키도 함께 전달합니다.
이때도 최종 판정은 해당 `<call>.monitor`의 비무음 신호입니다.

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

라이브 감시는 스케줄러가 **고정 1분마다** 새 probe 슬롯을 배정합니다. 브라우저 probe 자체는
백그라운드 태스크로 실행되므로, 한 사이트의 로딩이나 등록폼 처리가 오래 걸려도 다음 1분 감시
주기가 APScheduler에서 건너뛰어지지 않습니다. `DATE_STREAM_WATCH_CONCURRENCY=1`이면 동시에
하나만 브라우저를 열고, 새 이벤트도 병렬로 빠르게 확인하려면 2 이상으로 올릴 수 있습니다.

라이브 감시의 후보 선택도 과거 리플레이 검증과 같은 브라우저 엔진을 사용합니다. 매 주기마다
DB에 미리 확보한 `webcast_url`, `event_url`을 먼저 열고, 주소가 없거나 오래됐을 때 `ir_url`로
되돌아갑니다. 페이지 안에서 찾은 이벤트가 예정된 날짜와 다르거나 아직 시작되지 않아
오디오가 나오지 않으면 해당 provider URL을 이번 시도의 제외 목록에 넣고 같은 IR 페이지를
다시 스캔합니다. 제한된 시도 횟수 안에서 오디오가 확인되면 해당 브라우저와 PulseAudio를
종료하지 않고 같은 프로세스를 장시간 STT 캡처로 승격합니다. 따라서 probe와 STT 사이에
등록 세션, 재생 위치, 서명된 미디어 URL이 사라지거나 다른 후보가 선택되지 않습니다.
후보는 날짜·정확한 시각·`data-live`/`data-status` 같은 라이브 상태·최근 갱신 메타데이터를
합산해 점수화합니다. 일반 IR 페이지에서는 단순히 날짜가 다르지 않은 정도로는 부족하고,
예정일과 어닝/컨퍼런스콜 문맥이 함께 확인된 후보만 플레이어로 넘깁니다. 공식 IR에서 미리
검증한 `event_url`/`webcast_url`만 이 확인을 생략할 수 있습니다. 회계 분기 표기는 달력 분기와
다를 수 있어 라이브 하드 거절 기준으로 사용하지 않습니다. 모든 시도가 실패해도 콜을
영구 실패로 끝내지 않고 다음 감시 주기의 재시도 대상으로 남깁니다. 캡처 프로세스가 비정상
종료돼도 `DATE_STREAM_CAPTURE_RETRY_MINUTES`부터 지수적으로 간격을 늘려 다시 probe하며,
`DATE_STREAM_CAPTURE_MAX_ATTEMPTS=0`은 일반적인 브라우저·오디오 오류에 한해 이벤트 감시 창이
끝날 때까지 재시도를 유지합니다. `AUTH_REQUIRED`, CAPTCHA, 이메일 로그인 링크, 명시적 차단처럼
동일 등록을 반복해도 해결되지 않는 오류는 per-capture 로그를 근거로 1회에서 멈추며, 다음 일정
갱신 또는 사람 확인 후에만 다시 시도합니다.

FFmpeg 입력은 별도 reader가 계속 비우고 Whisper는 bounded PCM 큐를 소비합니다. 모델 로딩이나
추론이 잠시 느려져도 시작 음성이 파이프에서 막히지 않으며, 큐가 넘쳐 오디오 구간을 잃은 실행은
성공으로 처리하지 않고 재시도합니다. 최종 `completed`는 기본적으로 최소 2개 STT 세그먼트,
80자 이상의 텍스트, 성공 종료 마커, 종목·일정 일치 증거가 모두 있을 때만 기록됩니다.

```bash
ENABLE_DATE_STREAM_WATCH=true \
DATE_STREAM_WATCH_DAYS_AHEAD=2 \
DATE_STREAM_AUDIO_WAIT_SECONDS=90 \
python -m data_pipeline.scheduler
```

정확한 공식 시작 시각이 저장된 종목은 이벤트 전후 감시 주기를 자동으로 줄입니다.
기본값은 시작 20분 전부터 종료 180분 후까지 1분 간격이며, 시간이 아직 확정되지
않은 종목은 `DATE_STREAM_WATCH_COOLDOWN_MINUTES` 주기를 사용합니다. 확정 시각이
종료 유예시간을 지난 콜은 새 브라우저 probe 대상에서 제외하여 오래된 이벤트가
임박한 콜의 감시 슬롯을 차지하지 않게 합니다.

```bash
DATE_STREAM_NEAR_START_MINUTES=20
DATE_STREAM_NEAR_END_MINUTES=180
DATE_STREAM_NEAR_INTERVAL_MINUTES=1
DATE_STREAM_MAINTENANCE_START=03:00
DATE_STREAM_MAINTENANCE_END=04:00
```

일정의 **날짜**는 Yahoo Finance에서 넓게 동기화하지만, 전 종목의 정확한 시작 시각을 보장하는
단일 무료 데이터 소스는 없습니다. 가까운 14일은 Nasdaq 공개 earnings calendar와 매일 대조합니다.
두 보조 소스의 날짜가 다르거나 Yahoo 응답에서 사라진 행은 `provisional_watch`로 표시하고
기준일 전후의 감시 범위를 넓힙니다. 보조 소스 불일치만으로 일정을 덮어쓰거나 브라우저 감시에서
제외하지 않으며, 발행사 공식 페이지와 명백히 충돌할 때만 `required`로 격리합니다. Nasdaq 요청
실패도 빈 일정으로 취급하지 않습니다. `earning_at`은 넓은 실적 발표일, `webcast_date`는 공식
콜 날짜로 별도 저장합니다. 파이프라인은 기존 공식 `event_url`/`ir_url`을 먼저 다시 읽고,
필요할 때만 Serper 검색으로 같은 발행사 도메인의 이벤트 페이지를 찾아 날짜 일치와 시간대를
검증합니다. `LIVE_SCHEDULE_REFRESH_ON_STARTUP=true`면 서버 재시작 직후 날짜와 가까운 일정의
시간을 갱신하고, MySQL이 아직 준비되지 않았으면 `SCHEDULE_STARTUP_REFRESH_MAX_ATTEMPTS`와
`SCHEDULE_STARTUP_REFRESH_RETRY_SECONDS` 설정으로 재시도합니다. 이후 `SCHEDULE_TIME_REFRESH_INTERVAL_MINUTES`
주기로 재검증합니다. 이 작업은 공식 페이지의 이벤트 상세 링크, iframe, `data-*`, JSON-LD와
렌더링된 API 결과에서 provider URL도 미리 저장합니다. 링크 지문이 바뀌면 다음 probe의 cooldown을
해제합니다. 시간이
끝내 공개되지 않은 종목은 날짜 기반 1분 감시 후보로 계속 남습니다.

정확한 시각 보강은 라이브 감시와 분리된 best-effort 작업입니다. 발행사 IR 페이지의 HTTP 또는
브라우저 조회가 실패하면 종목별 실패 종류와 재시도 시각을 MySQL에 저장해 같은 페이지를 반복
요청하지 않습니다. Serper가 크레딧 소진, API 키 거부, rate limit, 또는 요청 거부를 반환하면
응답 본문은 저장하지 않고 안전한 분류만 기록하며, 전역 circuit breaker가 설정된 cooldown 동안
모든 Serper 검색을 멈춥니다. 이 cooldown은 정확한 시각 보강만 늦출 뿐, 해당 종목의 날짜 기반
라이브 감시와 이미 확보된 IR URL 탐색은 계속됩니다.

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

기존 MySQL volume은 컨테이너 최초 생성 때만 `mysql-init` SQL을 실행합니다. 이미
존재하는 volume을 계속 사용하는 경우에는 배포 전에 다음 명령으로 lease, transcript
archive, outbox 컬럼/테이블을 적용하고 검사합니다.

```bash
python -m data_pipeline.scripts.ensure_runtime_schema
python -m data_pipeline.scripts.ensure_runtime_schema --check-only --json
```

스케줄러는 stale probe/capture, 전송 대기 outbox, 외부 사이트 차단이 임계치를 넘으면
`data_pipeline/.runtime/operations/alerts-state.json`에 상태를 저장하고 JSONL에
알림/복구 이벤트를 남깁니다. `OPERATIONS_ALERT_WEBHOOK_URL`을 설정하면 같은 내용을
JSON POST로 운영 webhook에도 보냅니다. cooldown 동안 같은 장애를 반복 전송하지 않습니다.

downstream 계약은 기본적으로 health만 확인하고, 실제 transcript 한 청크 전송은 명시적으로
`--send`를 붙여 실행합니다. `EWTEST` 식별자가 붙은 테스트 call만 사용합니다.

```bash
python -m data_pipeline.scripts.check_downstream_integrations
python -m data_pipeline.scripts.check_downstream_integrations --send
```

`--send`는 DB outbox에 한 건을 기록한 뒤 AI Engine의 `/api/v1/analyze`와 Backend의
`/api/v1/internal/transcript-segment`로 전송하고 결과를 출력합니다. Backend 전송에는
`INTERNAL_SECRET`이 필요합니다. 실제 서비스가 실행되지 않은 개발 환경에서는 health
또는 전송 실패가 outbox에 남는 것이 정상이며, 다음 retry 주기에 재시도됩니다.

운영 컨테이너는 `restart: unless-stopped`로 설정되어 있으며, 종료 전까지 실행 중인
worker를 유지합니다. 실제 운영에서는 `data_pipeline/.env`의 `AI_ENGINE_URL`,
`BACKEND_URL`, `INTERNAL_SECRET`을 실제 서비스 값으로 지정해야 합니다.

### 웹캐스트 레시피 학습

웹캐스트 버튼은 소스 코드에 사이트별로 하드코딩하지 않습니다. 레시피가 없는 IR 도메인은 브라우저가 화면 스냅샷과 클릭 가능 DOM 후보를 수집하고, 후보를 새 브라우저 컨텍스트에서 다시 실행합니다. 이후 PulseAudio에서 실제 음성이 감지된 경우에만 MySQL의 `webcast_recipes` 레코드를 `verified`로 승격합니다. 다음 실행부터는 검증된 레시피를 우선 사용하며, 오디오 실패가 세 번 누적되면 해당 레시피는 자동 비활성화됩니다.
오디오 검증이 끝난 레시피에 외부 플레이어 주소가 함께 기록된 경우에는 IR 페이지가 CDN 차단으로 열리지 않아도 해당 플레이어로 바로 진입할 수 있습니다. 등록폼 제출과 브라우저 재생을 먼저 확인한 뒤 오디오 판정을 수행합니다.

화면 AI 선택은 선택 기능입니다. 기본값은 DOM 텍스트/접근성 속성 기반 후보 점수화이고, AI를 켜려면 아래 값을 `.env`에 설정합니다. 스크린샷과 후보 메타데이터는 `WEBCAST_ARTIFACTS_DIR`에 저장합니다. 이 값을 지정하지 않으면 쓰기 가능한 레거시 경로 `data_pipeline/.artifacts/webcast/`를 우선 사용하고, Docker 실행 후 해당 경로가 다른 사용자 소유가 된 경우 `data_pipeline/.runtime/artifacts/`로 자동 전환합니다.

```bash
WEBCAST_VISION_ENABLED=true
OPENAI_API_KEY=...
WEBCAST_VISION_MODEL=gpt-5.6-luna
WEBCAST_VISION_MIN_CONFIDENCE=0.55
```

AI는 화면에서 후보를 고르는 데만 사용합니다. 실제 클릭은 모델이 만든 코드가 아니라 DOM에서 추출한 선택자로 수행하며, 최종 성공 판정은 여전히 가상 오디오 장치의 비무음 신호입니다. CDN 차단, CAPTCHA, 권한 거부 페이지는 자동으로 `page access blocked` 상태로 기록하고 레시피 후보로 저장하지 않습니다.

### 과거 리플레이 학습

예정된 라이브 화면과 과거 리플레이 화면은 다를 수 있으므로, 과거 콜은 별도 대상 테이블에서 검증합니다. 먼저 Serper로 회사 IR 도메인 또는 알려진 웹캐스트 제공사의 직접 재생 페이지, 웹캐스트 아카이브, 공식 실적 발표문 진입점을 찾고, 그 다음 브라우저와 PulseAudio 가상 장치로 실제 음성을 확인합니다. 이 경로는 OpenAI API를 사용하지 않습니다.

전체 활성 종목의 저장된 IR 주소가 등록·재생·오디오 단계의 훈련 표면을 제공하는지
감사하려면 다음 명령을 사용합니다. 이 배치는 실제 과거 어닝콜을 우선 찾되, 없으면
과거 webcast·발표 영상을 `proxy`로 사용합니다.

```bash
data_pipeline/scripts/run_training_surface_audit.sh \
  --concurrency 2 \
  --force
```

등록폼 제출은 전역 설정으로 자동화할 수 있습니다. `WEBCAST_ALLOW_REGISTRATION_SUBMISSION=true`
이면 기존 배치 실행처럼 감지된 일반 등록폼을 자동으로 채우고 제출합니다. 종목별·목적지별
검토가 필요한 환경에서는 `WEBCAST_REGISTRATION_REQUIRE_APPROVAL=true`를 추가해 승인
매니페스트 모드를 선택적으로 켤 수 있습니다. 템플릿에는 개인정보 값이 저장되지 않습니다.

```bash
# 제출 없이 등록폼을 분석
data_pipeline/scripts/run_training_surface_audit.sh \
  --tickers DOW --force --registration-preview-only --concurrency 1

# 저장된 미리보기에서 비활성 승인 템플릿 생성
data_pipeline/scripts/run_training_surface_audit.sh \
  --export-registration-approval-template \
  data_pipeline/.runtime/operations/training-surface-audit/registration-approvals.json

# 선택 사항: 사람이 확인한 종목만 제출 허용하는 엄격 모드
data_pipeline/scripts/run_training_surface_audit.sh \
  --tickers DOW --force --concurrency 1 \
  --allow-registration-submission \
  --registration-approval-file \
  data_pipeline/.runtime/operations/training-surface-audit/registration-approvals.json
```

엄격 모드에서는 `approved=true`, 동일한 등록 목적지, 동일한 준비 필드, 동일한 동의
상태가 모두 일치할 때만 수행됩니다. 기본 자동 모드에서는 전역 제출 허용 설정만 확인합니다.
`registration-preview-only`와 `discovery-only`는 외부 폼 제출을 막으며,
개인정보 동의 제출도 이 설정을 따릅니다. `WEBCAST_ALLOW_PRIVACY_CONSENT_SUBMISSION`을
비워 두면 일반 등록 허용 설정을 따릅니다. `false`를 명시하면 해당 동의 제출만 끕니다.
이 설정은 사이트의 CAPTCHA, 유효한 계정이나 이메일 인증 요구를 우회하지 않습니다.

결과는 `webcast_training_surface_audits`에 종목별로 저장되며
`data_pipeline/.runtime/operations/training-surface-audit/latest.json`에서 실행 중에도
확인할 수 있습니다.

브라우저를 다시 실행하지 않고 현재 503개 결과를 인간 검토 작업 큐로 분류하려면 다음을
실행합니다.

```bash
data_pipeline/scripts/run_training_surface_audit.sh \
  --classify-only \
  --report-dir data_pipeline/.runtime/operations/training-surface-audit
```

`classification-latest.json`은 `audio_proven`, `human_downstream`,
`entrypoint_review`, `automatic_retry`로 모든 활성 종목을 정확히 한 번씩 분류합니다.
학습 모드에서 후보를 찾지 못한 경우는 `candidate_discovery_retry` 상태로 저장되고
`automatic_retry` 큐로 들어갑니다. 즉 후보 없음은 최종 실패나 사람에게 후보 검색을
떠넘기는 분류가 아닙니다. 재시도 때 같은 도메인의 최근 이벤트·아카이브·뉴스 상세·웹캐스트
제공자 링크를 제한된 깊이 3, 최대 10페이지, 후보 5개 범위에서 넓혀 탐색한 뒤, 후보가
열리면 등록·재생·오디오 검증을 같은 후속 경로로 진행합니다. 접근 차단·실제 네트워크
오류처럼 링크 탐색 전에 막힌 경우만
`entrypoint_review`로 분리합니다.

503개를 약 50개씩 고정 배치로 섞어 실행하려면 먼저 매니페스트를 만들고 원하는 배치를
지정합니다. 매니페스트는 생성 시점의 종목 구성을 보존하므로 앞 배치의 결과가 바뀌어도
다음 배치 구성은 달라지지 않습니다.

```bash
data_pipeline/scripts/run_training_surface_audit.sh \
  --plan-batches --batch-size 50 \
  --report-dir data_pipeline/.runtime/operations/training-surface-audit/full

data_pipeline/scripts/run_training_surface_audit.sh \
  --batch-plan data_pipeline/.runtime/operations/training-surface-audit/full/batch-plan.json \
  --batch-index 1 --concurrency 1 --force \
  --allow-registration-submission
```

- `surface_kind=earnings`: 실제 실적발표 문맥의 이벤트를 선택함
- `surface_kind=proxy`: 비실적 webcast를 뒷단 훈련용으로 사용함
- `surface_kind=webcast`: 이벤트 정체는 불명확하지만 재생 가능한 webcast에 도달함
- `status=audible`: 등록·플레이어·가상 오디오까지 통과함
- `status=candidate_discovery_retry`: 현재 시도에서 후보가 열리지 않았지만, IR 주소가
  무효라고 판단하지 않고 유사 이벤트 링크 재탐색 대상으로 남김

`audible + proxy`는 뒷단 통과 증거일 뿐 실제 어닝콜 선택 노하우의 검증으로 세지
않습니다. `blocked`, `navigation_failed`, `not_found`처럼 접근 자체가 막힌 경우만 IR
진입점 검토 대상으로 별도 리포트됩니다. `live`와 `pre_live` 감시는 계속 실제 어닝콜이
아닌 이벤트를 거부합니다.

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

# Serper 없이 IR 내부 링크와 sitemap을 최대 2단계까지 탐색
python -m data_pipeline.tools.replay.internal_ir_discovery \
  --discovery-statuses no_candidate,error \
  --depth 2 --max-pages 8 --force

docker compose -f infra/docker-compose.yml --profile tools run --rm \
  -e WEBCAST_CAPTURE_RUNNER=container browser-webcast \
  python -m data_pipeline.tools.replay.historical_replay_learning_batch --concurrency 1
```

성공한 선택자는 `lifecycle=replay` 레시피로만 검증 완료 처리됩니다. 라이브 감시에서는 `live` 레시피를 우선 적용하고, 같은 도메인의 검증된 리플레이 레시피는 보조 후보로만 사용합니다. Cloudflare/CAPTCHA처럼 사람 검증이 필요한 URL은 자동으로 우회하지 않고 `access_blocked`로 기록합니다. 알려진 공식 도메인 별칭이나 제공사 경로가 있는 경우에만 제한된 대체 진입점을 한 번 시도하며, 대체 시도 간격은 `WEBCAST_ACCESS_RETRY_DELAY_SECONDS`로 조정할 수 있습니다.

브라우저가 IR 시작 페이지에서 이벤트/플레이어까지 이동하면 마지막으로 도달한 URL을 `browser_resolved` 후보로 별도 저장합니다. 오디오 감지까지 성공한 URL뿐 아니라, 오디오 판정 전에 타임아웃된 이벤트 페이지도 탐색 증거로 저장하되 PDF와 원본 IR 홈은 제외합니다. 원래 IR 주소는 보존하고, 다음 과거 리플레이 검증부터는 이 가까운 진입점을 먼저 사용하므로 매번 IR 홈에서 같은 탐색을 반복하지 않습니다.

`internal_ir_discovery`는 외부 검색 API를 사용하지 않습니다. 회사 IR 도메인의 내부 링크, `robots.txt`에 선언된 sitemap, 일반적인 sitemap 경로를 읽고 이벤트·웹캐스트·리플레이 링크를 후보로 저장합니다. IR 페이지에서 직접 연결된 신뢰할 수 있는 웹캐스트 제공사 링크도 저장하지만, 제공사 도메인 내부를 임의로 크롤링하지는 않습니다.

사람 확인이 허용된 운영 점검에서는 `WEBCAST_MANUAL_READY_FILE`을 지정한 visible 브라우저를 사용합니다. 브라우저에서 Cloudflare 등 사람 확인을 완료한 뒤 해당 파일을 만들면 같은 세션에서 페이지 분석을 재개합니다. CAPTCHA를 자동으로 해결하거나 우회하는 경로는 저장된 레시피로 승격하지 않습니다.

### Transcript 보관 및 용량 정책

실시간 STT 결과는 `TRANSCRIPT_ARCHIVE_ENABLED=true`일 때 텍스트 청크만
`transcript_segments` 테이블에 저장됩니다. 오디오 원본은 저장하지 않으며,
`call_id + sequence`를 유일키로 사용해 재전송에도 중복 행이 생기지 않습니다.

MySQL이 잠시 내려가도 청크와 종료 표식은 먼저
`data_pipeline/.runtime/transcript-archive-spool.jsonl`에 기록됩니다. DB가 복구되면 스케줄러의
30초 outbox 작업이 이를 idempotent하게 반영하고, 충분한 세그먼트와 종료 표식이 확인된 캡처만
완료 상태로 복구합니다. 다른 디스크를 써야 하면 `TRANSCRIPT_ARCHIVE_SPOOL_PATH`로 지정할 수
있습니다.

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
