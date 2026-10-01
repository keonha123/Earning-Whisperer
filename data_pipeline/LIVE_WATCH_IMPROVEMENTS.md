# 실시간 수집 개선 사항 — 2026-09-17

대상은 과거 버전의 data_pipeline이다. 운영 `.env`, DB 일정/격리 상태는 코드 변경과 별도로 관리한다.

## 변경된 동작

1. **재시도:** 내부 `MEDIA_FALLBACK_BLOCKED`/`TARGET_IDENTITY_UNCONFIRMED`는 후보 미확인이다. 스케줄러·manager·캡처 정책이 공통 분류를 사용하며, 내부 가드만으로 6시간 차단하거나 1회 후 최종 실패하지 않는다. 실제 접근 차단·인증 증거는 유지한다.
2. **일정:** 발표·뉴스 게시·다시보기 만료와 콜 시작을 분리한다. 충돌/DST 모호 시각은 미확정으로 남긴다. 명시적인 콜 시각 충돌로 기존 검증이 무효가 되면 날짜 감시로 복귀한다(진행 중 작업 제외). 당일·익일 일정은 기본 30분 경과 후 재검증 대상이다. 실제 실행 빈도는 스케줄러 작업 주기에 따른다. 뉴욕 날짜/UTC 시각 경계, SQL LIMIT 전 종목 필터, 오래 기다린 종목 우선순위를 적용한다.
3. **탐색:** 날짜 없는 공식 IR 메뉴·탭은 제한된 횟수로 탐색한다. 최종 후보는 날짜·행사 근거로 따로 확인한다. 개최일과 다시보기 만료일을 분리하고, 정확한 href와 제공업체 이벤트 ID/연결 경로를 유지한다. 확인한 등록 경로의 폼 제출·리다이렉트·팝업은 추적하되 다른 행사 ID는 허용하지 않는다.
4. **자원:** 링크 발견 전용 브라우저는 폼 제출·재생 없이 종료된다. 캡처가 실행 중이어도 별도 탐색 예산으로 다른 콜을 확인한다. 무거운 준비 전에 캡처 자원을 예약하며, 준비·승격 대기·실제 캡처를 중복 집계하지 않는다. 취소·일정 변경·승격 파일 오류 시 예약과 브라우저를 정리한다. 발견한 링크는 짧은 프로세스 캐시로 보관하고 재시작 시 다시 발견한다. 최근 공식 IR에서 해당 날짜와 연결해 확인한 저장 URL은 재사용할 수 있다.
5. **등록/재생:** 클릭 성공 뒤 폼을 다시 제출하지 않는다. 타임아웃 시 실제 제출 흔적을 확인하고 정상 submit 컨트롤에만 native fallback을 적용한다. 제공업체 공통 recipe는 명시적 scope, 현재 행사 확인, 도메인/화면 조건과 완료 조건이 필요하다. 과거 URL과 개인 입력값은 재사용하지 않는다. 재생 시간의 두 시점 관측과 OS 오디오 확인을 구별한다.
6. **오디오:** playback-ready 뒤부터 하나의 PCM 생산자가 warmup·음성 검사·승격·모델 로딩 중 음성을 보관한다. 후속 STT는 처음 바이트부터 읽으며, 큐가 차도 저장된 앞부분을 버리지 않는다. 파일은 콜별 private temp, 기본 512MiB 한도이며 종료 시 제거한다. 한도 초과는 성공 종료가 아닌 오류다. playback-ready 이전 음성의 보존까지 보장하는 기능은 아니다.
7. **성능:** worker가 `STT_PERFORMANCE` JSON을 출력한다. 인식 계산/새 음성 시간(RTF), 모델 준비, 첫 텍스트 지연, 관측된 최대 대기 음성, 누락 바이트를 포함한다. 첫 텍스트 지연의 기준은 STT 입력 시작이며, PCM 인계 시작 기준 지연도 별도 기록한다.

## 설정과 운영

- `DATE_STREAM_DISCOVERY_ENABLED=true`, 탐색 동시성 기본 2, 1회 탐색 제한 45초.
- `DATE_STREAM_CAPTURE_CONCURRENCY`를 지정하지 않으면 기존 `DATE_STREAM_WATCH_CONCURRENCY`를 캡처 한도로 사용한다. 값을 늘리기 전에 실제 STT 동시 실행을 측정한다.
- `DATE_STREAM_DISCOVERY_HEADED`를 생략하면 `WEBCAST_HEADED`를 따른다(기본 true). 별도 Xvfb를 사용하므로 기존 재생 브라우저 방식과 맞출 수 있다.
- `STT_PCM_HANDOFF_ENABLED=false`는 기존 장치 직접 입력으로 되돌리는 호환 설정이다.
- 상주 Python 스케줄러는 파일 변경만으로 모듈을 다시 읽지 않는다. 운영 반영 시 진행 중 캡처를 확인하고 스케줄러를 재기동한다. 이전에 기록된 DB 재시도 대기 상태는 자동 삭제하지 않는다.
- 자원 예약은 단일 scheduler 프로세스 기준이다. 다중 scheduler 배포에는 전역 용량 lease가 필요하다.

## 검증

관련 회귀는 `tests/test_live_retry.py`, `test_live_schedule_timing.py`, `test_live_navigation.py`,
`test_live_watch_capacity.py`, `test_registration_live.py`, `test_playback_live.py`,
`test_provider_steps.py`, `test_pcm_handoff.py`, `test_stt_benchmark.py`에 있다.

실제 Chromium 검증은 `RUN_LOCAL_BROWSER_SMOKE=1`이 필요하다. 테스트에는 운영 DB/프로필을 연결하지 않는다.
STT 벤치마크는 [실행 안내](tools/debug/STT_BENCHMARK.md)를 따른다. 단위 테스트 통과와 실제 생방송 성공률은 구별한다.

이번 로컬 측정: distil-large-v3 CPU/int8, 8 threads, Docker CPU quota 4 / RAM 4GiB,
합성 발화 120초, 계산 45.792초(RTF 0.3816), 누락 0바이트, 첫 텍스트 26.206초,
관측 최대 대기 음성 12초. 단일 콜·2분 시험의 결과이며 AWS 등급/장시간/다중 콜 성능 보장은 아니다.
