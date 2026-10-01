# 동시 어닝콜 수집 — 2026-09-23

과거 버전 데이터파이프라인에서 한 스케줄러가 최대 3개 콜을 준비·수집한다.
실제 외부 사이트 3곳의 성공을 보장하는 설정은 아니다. 등록·후보 탐색·시각 검증은 그대로 수행한다.

## 운영 설정

현재 로컬 8코어/16스레드, 약 27GiB 메모리 호스트용 설정은
`infra/docker-compose.concurrent.yml`에 둔다. 컨테이너 CPU 상한 8, 메모리 상한 10GiB,
캡처·탐색 한도 각 3, STT 추론 스레드는 콜당 2다. BLAS의 추가 스레드 경쟁도 제한한다.
모델은 기존 distil-large-v3를 유지하며 백엔드 전송 설정은 변경하지 않는다.

```sh
cd infra
docker compose -f docker-compose.yml -f docker-compose.concurrent.yml --profile ops up -d --no-deps --no-build pipeline-scheduler
```

파일 변경이나 재시작은 진행 중인 캡처를 확인한 뒤 수행한다. 환경·리소스 제한 변경에는
컨테이너 재생성이 필요하다. 이후에도 위 두 Compose 파일을 함께 사용해야 설정이 유지된다.
전체 슬롯 예약은 단일 스케줄러 프로세스 내부에서 관리하므로 스케줄러 복제본을 늘리지 않는다.
다른 서버/AWS 인스턴스에는 이 사양을 그대로 적용하지 말고 해당 환경에서 측정한다.

## 콜 사이 격리

- 각 콜은 별도 Chromium, Xvfb, PulseAudio 서버·소켓, PCM 파일, STT 프로세스를 사용한다.
- 오디오 서버 식별자에는 콜뿐 아니라 시도·탐색 경로·캡처 세션도 반영한다. 이전 시도의 정리가 새 시도의 오디오를 종료하지 않게 한다.
- 관리되는 캡처는 공유 Pulse 경로 및 고정 포트 noVNC/호스트 display 사용을 막는다.
- 로그인 상태는 같은 콜·일정 버전에서 재사용하되 오디오·종료 신호·진행 로그는 시도별로 분리한다.
- 준비 중, 오디오 확인 후 대기 중, 실제 캡처를 합쳐 3개까지 예약한다. 네 번째 콜은 여유 슬롯이 생길 때까지 대기한다.
- 한 콜 실패/종료 시 해당 예약과 프로세스만 정리한다. 다른 콜의 수집은 유지한다.

## 진단

`watch_cycle`, `capture_deferred`, 슬롯 예약·반납 이벤트에 다음 수치가 남는다.

- `capture_limit`, `discovery_limit`
- `active_captures`, `held_captures`, `preparing_captures`, `capture_reservations`
- `occupied_capture_slots`, `available_capture_slots`

준비→대기→수집 전환 중 같은 콜이 여러 집합에 있어도 점유 합계는 한 번만 센다.
각 콜의 `stt.json`에서 RTF, backlog, 마지막 텍스트 시각을 확인하고,
`archive.json`에서 생성·fsync·DB 저장 순번을 비교한다.
한 콜의 실패를 고치려고 정상 수집 중인 전체 컨테이너를 재시작하지 않는다.

## 검증 범위

1. 슬롯 회귀: 3개 예약·4번째 대기·실패 격리·완료 후 슬롯 재사용·동일 콜 중복 방지.
2. 실제 오디오 격리: 로컬 플레이어 3개에서 440/660/880Hz를 동시 재생하고 각 Pulse PCM의 주파수를 대조한다. 한 콜 종료 후 나머지 두 콜이 계속 수집되는지도 확인한다.
3. 실제 STT 부하: 로컬 음성을 3개 Chromium→Pulse→PCM→distil-large-v3→로컬 저장 경로로 동시 처리한다. 네트워크는 차단하고 운영 DB/백엔드는 사용하지 않는다.

오디오 격리 검증:

```sh
RUN_CONCURRENT_AUDIO_SMOKE=1 python -m unittest data_pipeline.tests.test_concurrent_audio_isolation -v
```

짧은 부하 시험은 외부 생방송의 40~60분 완주나 음성 인식 정확도 검증을 대신하지 않는다.
실전에서 각 콜의 시작·중간·종료 증거를 별도로 확인해야 한다.
