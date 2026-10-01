# Data Pipeline Architecture

이 문서는 데이터 파이프라인을 어디서 시작하고, 어떤 기능을 어느 파일에서 고쳐야 하는지
빠르게 파악하기 위한 지도다. 운영 진입점은 `scheduler.py`, 조립 지점은
`orchestrator.py`이며, 실제 구현은 기능별 패키지에 있다.

라이브 웹 감시만 직접 추적하려면 [LIVE_WATCH_GUIDE.md](LIVE_WATCH_GUIDE.md)를 참고한다.

## 전체 흐름

```text
scheduler.py
  -> orchestrator.py (부품 조립 및 공개 API)
     -> application/schedules.py     일정 수집, 교차 검증, 공식 IR 시각 보강
     -> application/live_watch.py    감시 후보 조회, probe lease, 캡처 시작
        -> stt_worker/manager.py      probe/capture 프로세스와 manifest 관리
           -> collectors/streams/browser/
              -> session.py          브라우저와 페이지 수명주기
              -> discovery.py        IR 페이지와 웹캐스트 후보 탐색
              -> registration.py     등록폼, 선택지, 동의 처리
              -> playback.py         플레이어 탐색과 재생 활성화
              -> learning.py         검증된 레시피와 증거 저장
              -> human.py            관찰/바톤 모드
              -> flow.py             위 단계를 순서대로 실행
           -> scripts/run_webcast_audio_capture.sh
              -> stt_worker/take.py  오디오 사전검사와 Whisper STT
                 -> stt_worker/delivery.py
                    -> storage/transcripts.py  STT 청크, 종료 마커, outbox
     -> application/market_data.py   종목, 가격, 재무, 지표 동기화
     -> application/housekeeping.py  stale 작업 복구, 재전송, 보관, 알림
```

## 폴더 책임

| 위치 | 책임 | 수정할 때의 기준 |
|---|---|---|
| `application/` | 여러 하위 부품을 하나의 업무로 조합 | 일정 감시 정책이나 서비스 흐름 변경 |
| `collectors/` | 외부 소스에서 원자료와 웹 페이지 증거 수집 | Yahoo/Nasdaq/IR/웹캐스트 해석 변경 |
| `collectors/streams/browser/` | 브라우저 안에서 후보 탐색부터 재생까지 수행 | 사이트 구조와 플레이어 대응 노하우 변경 |
| `stt_worker/` | 프로세스, 오디오 입력, STT, 결과 전달 관리 | 캡처/Whisper/watchdog/outbox 동작 변경 |
| `storage/` | MySQL 스키마와 쿼리 | 상태 전이, lease, 일정, 학습 기록, 텍스트 저장 변경 |
| `tools/` | 과거 리플레이 학습, 진단, 관찰, mock | 운영과 분리된 조사 도구 변경 |
| `scripts/` | Docker/PulseAudio/FFmpeg 실행 경계 | 컨테이너 오디오 장치와 실행 인자 변경 |
| `tests/` | 단위, 조립, 로컬 브라우저 회귀 검증 | 부품 계약과 실제 DOM 흐름 검증 |

`database.py`와 `collectors/streams/browser_webcast.py`는 기존 import와 CLI를 유지하는
호환 창구다. 새 기능은 각각 `storage/`와 `collectors/streams/browser/`에 구현한다.
`orchestrator.py`도 업무 구현을 담지 않고 아래 서비스들을 조립한다.

## 조립 방식

`EarningsOrchestrator`는 같은 repository와 health 객체를 서비스에 주입한다. 테스트에서는
가짜 repository와 worker를 넣어 MySQL이나 Docker 없이 일정 감시부터 캡처 인계까지 확인할
수 있다.

```python
pipeline = EarningsOrchestrator(
    repository=fake_repository,
    worker_manager=fake_worker,
)
await pipeline.dispatch_date_based_streams()
```

브라우저는 `BrowserStages`에 기능 모듈을 조립한다. 특정 공급자의 재생 로직을 시험할 때
agent 전체를 복사하지 않고 playback 부품만 교체할 수 있다.

```python
from dataclasses import replace

stages = replace(BrowserStages(), playback=custom_playback)
agent = BrowserWebcastAgent("EWTEST", ir_url, stages=stages)
```

## 라이브 상태 전이

1. 스케줄러가 일정 날짜와 공식 IR 검증 상태를 바탕으로 감시 대상을 조회한다.
2. `LiveWatchService`가 DB lease를 얻고 동일한 브라우저 엔진으로 짧은 probe를 실행한다.
3. 아직 후보나 음성이 없으면 오류 유형에 맞는 재시각을 저장하고 다음 감시 주기로 돌려보낸다.
4. 음성이 확인되면 최종 URL, 제외 URL, 미디어 후보, storage state를 capture manifest로 저장한다.
5. 장시간 캡처는 그 manifest에서 출발해 동일한 플레이어를 재현한다.
6. `take.py`는 무음/무청크 watchdog과 최대 실행시간을 적용하고 STT 청크를 저장한다.
7. STT 세그먼트와 종료 마커가 모두 DB에 있을 때만 call을 `completed`로 바꾼다.
8. 세그먼트가 없거나 프로세스가 실패하면 `retry_pending` 또는 실패 사유로 남겨 재감시한다.

## 일정 판단

- Yahoo 일정으로 넓은 종목 범위를 갱신한다.
- 가까운 일정은 Nasdaq 캘린더와 대조한다.
- 보조 소스 날짜가 사라지거나 충돌하면 `provisional_watch`로 넓게 감시한다.
- 공식 IR 페이지에서 콜 날짜, 공개 시각, 이벤트 및 provider URL을 보강한다.
- 발행사 공식 페이지와 명백히 충돌할 때만 `required`로 격리한다.
- 정확한 시간이 없더라도 해당 날짜에는 1분 주기의 probe 대상으로 둘 수 있다.
- 공식 페이지 조회 실패와 검색 API 오류에는 종목별 cooldown 및 circuit breaker를 적용한다.

## 저장과 복구

- probe와 capture는 별도 DB lease를 사용해 중복 실행을 막는다.
- 서버 재시작 후 stale lease와 죽은 로컬 프로세스 소유권을 회수한다.
- STT 결과는 `transcript_segments`에 청크 단위로 저장한다.
- DB 장애 중에는 로컬 spool에 먼저 기록하고 복구 후 MySQL로 옮긴다.
- 외부 서버 전달은 `transcript_outbox`에 보존되며 설정으로 끌 수 있다.

## 현재 경계

구조와 상태 전이는 구현되어 있지만 다음은 별도의 실전 검증 영역이다.

- 실제 라이브 어닝콜의 시작부터 종료까지 장시간 E2E
- CAPTCHA, 이메일 소유 인증, 2차 인증처럼 사람 검증이 필요한 장벽
- 등록폼과 플레이어 공급자별 긴 규칙 파일의 추가 세분화
- 500개 종목 각각의 성공 보장과 성공률 측정
- STT 모델 품질, 비용, 지연시간 튜닝

따라서 현재 코드는 “한 종목이라도 전체 자동 흐름을 실행할 수 있는 파이프라인”에는 도달했지만,
“모든 종목에서 검증된 운영 완성품”으로 보아서는 안 된다.

## 검증 명령

전체 회귀 테스트:

```bash
data_pipeline/.venv/bin/python -B -m unittest discover -s data_pipeline/tests
```

외부 네트워크 없이 실제 Chromium으로 후보 선택, 등록폼 제출, 재생을 검증:

```bash
docker run --rm --network none \
  --mount type=bind,src="$PWD",dst=/app,readonly \
  -w /app -e RUN_LOCAL_BROWSER_SMOKE=1 \
  infra-browser-webcast:latest \
  python -B -m unittest data_pipeline.tests.test_browser_components_local
```
