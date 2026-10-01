# Live Webcast Watch Guide

이 문서는 라이브 웹 감시 문제를 직접 추적하기 위한 최소 안내서다. 전체 파이프라인을
읽을 필요 없이 아래 다섯 단계만 순서대로 확인하면 된다.

## 먼저 알아둘 점

현재 서버는 웹페이지 하나를 하루 종일 열어 두지 않는다. APScheduler가 1분마다 MySQL에서
감시할 call을 찾고, 선택된 종목에 대해 짧은 Chromium probe를 새로 실행한다. probe가
실제 플레이어와 가상 오디오 신호를 확인하면 같은 실행 증거를 넘겨 장시간 STT 캡처를 시작한다.

```text
1분 타이머
  -> DB 대상 선택
  -> 브라우저 probe
  -> 후보/등록/재생
  -> PulseAudio 소리 확인
  -> 장시간 STT 캡처
```

## 1. 1분 타이머

파일: `scheduler.py`

- `ENABLE_DATE_STREAM_WATCH=true`일 때 `dispatch_date_based_streams`를 등록한다.
- 호출 주기는 코드에서 1분으로 고정되어 있다.
- 한 probe가 오래 걸려도 다음 스케줄 호출을 막지 않도록 background task로 보낸다.

여기에 로그가 없다면 스케줄러 또는 환경 설정 문제다. 웹사이트 문제를 보기 전에 이 단계를
먼저 확인한다.

## 2. DB 대상 선택

파일: `application/live_watch.py`, `storage/live_calls.py`

기본 선택 조건은 다음과 같다.

- call 상태가 `upcoming` 또는 `live`
- `schedule_revalidation_status`가 `clear` 또는 `provisional_watch`
- 감시 날짜 범위 안에 있음
- probe/capture 재시도 시각이 지남
- 다른 작업이 유효한 lease를 가지고 있지 않음

정확한 시각이 있으면 시작 20분 전부터 종료 180분 후까지 우선한다. 시각이 없으면 날짜만으로
감시한다. 현재 설정의 동시성은 1이므로 한 종목이 probe 슬롯을 사용하는 동안 다른 종목은
다음 주기를 기다린다.

DB에서 먼저 볼 필드는 다음과 같다.

```sql
SELECT id, ticker, earning_at, webcast_date, scheduled_at_utc, status,
       schedule_revalidation_status,
       stream_probe_status, last_stream_probe_at,
       stream_probe_retry_not_before, last_stream_probe_error,
       capture_retry_not_before, capture_last_error
FROM calls
WHERE ticker = 'MSFT'
ORDER BY earning_at DESC;
```

행이 조회 대상에 들어오지 않으면 브라우저 코드를 고칠 문제가 아니다. 일정, 상태, 재검증,
cooldown 중 무엇이 막았는지 확인한다.

## 3. 브라우저 probe

파일: `stt_worker/manager.py`, `collectors/streams/browser/`

manager는 URL을 다음 순서로 시도한다.

1. `calls.webcast_url`
2. `calls.event_url`
3. `stocks.ir_url`

각 URL은 `run_webcast_audio_capture.sh --probe-only`로 실행된다. Docker 안에서 Playwright가
Chromium을 열고 브라우저 단계들을 조립해 사용한다.

| 파일 | 사람이 이해할 책임 |
|---|---|
| `session.py` | 페이지 열기, 탭/iframe, 쿠키와 접근 장벽 |
| `discovery.py` | 클릭 가능한 이벤트·웹캐스트 후보 수집 |
| `learning.py` | 날짜·종목·분기와 기존 학습 레시피로 후보 선택 |
| `registration.py` | 등록 입력, select/radio/동의, 제출 |
| `playback.py` | play 버튼과 media element 활성화 |
| `flow.py` | 위 단계를 어떤 순서로 호출하는지 결정 |

후보는 DOM의 텍스트, 링크, aria-label, title, 날짜, ticker, 라이브 상태와 DB에 저장된
일반화 레시피로 점수화한다. 일반 IR 페이지에서는 예정일과 어닝/컨퍼런스콜 문맥을 함께
확인해야 하며, 공식 IR에서 미리 검증한 이벤트/웹캐스트 주소만 이 확인을 생략한다. issuer의
회계 분기는 달력 분기와 다를 수 있으므로 라이브 후보의 하드 거절 기준으로 쓰지 않는다.
선택적 vision 기능도 있지만 기본 동작의 필수 요소는 아니다.
잘못 연 후보는 실행 로그에서 URL을 추출해 다음 시도에서 제외한다.

## 4. 오디오 확인

파일: `scripts/run_webcast_audio_capture.sh`

웹페이지에 영상이 보인다는 사실만으로 성공 처리하지 않는다.

- call마다 격리된 PulseAudio null sink를 만든다.
- Chromium의 출력 장치를 그 sink로 연결한다.
- `ffmpeg`의 `volumedetect`로 monitor에 임계값 이상의 신호가 들어오는지 확인한다.
- HLS/MP4 또는 YouTube 주소를 얻은 경우 직접 media fallback도 시도한다.
- `AUDIO_DETECTED`가 있어야 probe가 성공한다.

`PLAYBACK_READY`까지 보이고 `AUDIO_NOT_DETECTED`가 나오면 후보 탐색 문제가 아니라
브라우저 음성 출력, mute, PulseAudio routing 또는 미디어 fallback 문제다.

## 5. STT와 완료 판정

파일: `stt_worker/take.py`, `stt_worker/delivery.py`, `storage/transcripts.py`

probe 성공 후 manager는 목표 신원 확인 여부, 최종 player URL, 제외 URL, media 후보,
브라우저 storage state를 capture manifest에 저장한다. 장시간 캡처는 이 manifest를 사용해
같은 플레이어를 다시 연다.

`take.py`는 짧은 WAV 사전검사 뒤 PulseAudio monitor를 FFmpeg로 읽어 Whisper에 전달한다.
무청크, 장시간 무텍스트, 최대 세션 시간 watchdog이 있어 영원히 멈추지 않는다. 결과는
`transcript_segments`에 저장되며, 텍스트 세그먼트와 session-end 마커가 모두 있어야 call을
`completed`로 바꾼다. 단순한 프로세스 종료 코드 0은 성공 근거가 아니다.

## 실패 로그 읽는 법

| 마지막 신호 | 확인할 곳 | 의미 |
|---|---|---|
| `watch_cycle idle` | 일정/DB | 감시할 call이 선택되지 않음 |
| `probe_started` 뒤 DB 오류 | MySQL/lease | 사이트를 열기 전 실패 |
| `no candidate` | `discovery.py`, `learning.py` | 이벤트 링크를 선택하지 못함 |
| `REGISTRATION_*` | `registration.py` | 입력, 동의, 제출 또는 인증 장벽 |
| `PLAYBACK_READY_TIMED_OUT` | `playback.py` | 플레이어 또는 play 버튼 활성화 실패 |
| `AUDIO_NOT_DETECTED` | shell/PulseAudio | 재생 이후 가상 장치에 소리가 없음 |
| `SPEECH_PENDING` | STT preflight | 소리는 있으나 짧은 표본에서 발화를 못 찾음 |
| `STT_EXIT_NO_TEXT` | `take.py` | 장시간 캡처에서도 텍스트가 없음 |
| `retry_pending` | `storage/live_calls.py` | 실패했지만 다음 재시도 대상으로 복귀 |
| `completed` | transcript DB | 텍스트와 종료 마커 저장까지 확인됨 |

구조화된 감시 이벤트는 기본적으로
`data_pipeline/.runtime/operations/events-YYYY-MM-DD.jsonl`에 기록된다. 종목별 probe/capture
증거는 `data_pipeline/.runtime/operations/probe-artifacts/`에 남는다. 이 두 곳과 `calls` 행을
함께 보면 어느 단계에서 멈췄는지 판단할 수 있다.

## 수정 순서

문제를 발견했을 때는 마지막으로 성공한 신호 바로 다음 부품만 수정한다.

1. DB 후보에 없음: `storage/live_calls.py` 또는 일정 데이터
2. 후보를 못 찾음: `browser/discovery.py`, `browser/learning.py`
3. 폼을 못 넘음: `browser/registration.py`
4. 버튼을 못 누름: `browser/playback.py`
5. 소리가 안 들어옴: `run_webcast_audio_capture.sh`
6. 소리는 있는데 글이 없음: `stt_worker/take.py`
7. 글은 있는데 완료가 안 됨: `stt_worker/delivery.py`, `storage/transcripts.py`

이 경계를 지키면 한 문제를 해결하기 위해 전체 서버를 읽거나 수정할 필요가 없다.

## 실제 콜 없이 이벤트 전환 검증하기

`tests/fixtures/adbe_event_transitions.html`은 저장된 ADBE 후보 문맥을 바탕으로 만든
로컬 HTML이다. 링크는 테스트용 주소이며, 브라우저 테스트는 외부 페이지 요청을 차단한다.
`setEventState('scheduled' | 'live' | 'archived')`로 링크 등장과 영역 이동을 재현한다.

회귀 테스트는 다음을 확인한다.

- 같은 페이지의 다음 분기 일정·대기 문구가 현재 콜 탐색을 중단하지 않는다.
- live의 시작 전 판정은 선택한 대상 이벤트의 문맥에서만 한다. 정확한 시작 시각의
  조기 진입 대기는 유지한다. 페이지 전체 문구는 live 일정 변경의 근거로 쓰지 않는다.
- 다른 행사 날짜를 포함한 probe 오류만으로 일정을 격리하거나 URL을 지우지 않는다.
- 정확한 링크의 쿼리·이벤트 ID를 보존하고, 실제 요소의 날짜·문맥을 다시 확인한다.
- 선택 뒤 DOM 순서가 바뀌어도 같은 요소를 클릭한다. 대상이 사라지거나 옛 recipe의
  경로가 여러 행사와 일치하면 임의의 첫 링크를 선택하지 않는다.
- 실패한 행사 URL을 제외할 때 다른 event ID를 가진 링크까지 제외하지 않는다.

저장소 루트에서 순수 판정 테스트를 실행한다. pytest 설치는 필요하지 않다.

```sh
data_pipeline/.venv/bin/python -B -m unittest data_pipeline.tests.test_live_event_selection
```

Chromium이 설치된 환경에서는 실제 DOM 선택·클릭·전환 테스트도 실행한다.
Playwright 기본 브라우저를 사용하면 실행 파일 환경 변수는 생략할 수 있다.

```sh
RUN_LOCAL_BROWSER_SMOKE=1 \
WEBCAST_CHROMIUM_EXECUTABLE=/path/to/chrome \
data_pipeline/.venv/bin/python -B -m unittest data_pipeline.tests.test_live_event_selection
```

이 테스트는 실제 제공업체의 인증, 플레이어, 가상 오디오, STT 성능 검증을 대체하지 않는다.
이미 격리된 DB 행도 자동으로 되돌리지 않는다. 기존 행은 대상 콜의 공식 일정 근거를
확인한 뒤 재검증해야 한다.
