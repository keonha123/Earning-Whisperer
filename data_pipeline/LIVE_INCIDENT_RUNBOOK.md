# 생방송 수집 점검·복구 — 2026-09-22

대상: 과거 버전 `school/Earning-Whisperer/data_pipeline`, 운영 컨테이너 `ew-pipeline-scheduler`.
이번 변경은 캡처 동시성을 늘리지 않는다. 기존 캡처 한도 1과 링크 탐색 설정을 유지한다.

## 이번에 반영한 동작

| 문제 | 적용 내용 | 실전에서 확인할 증거 |
| --- | --- | --- |
| 후보 제외 후 같은 오답 반복 | 도메인·쿼리의 행사 ID를 포함한 전체 주소로 필터링하고, 무효 후보 다음 순위를 평가 | 후보 목록, 탈락 이유, 선택·이동 주소 |
| 올바른 행사를 폼/재생 오류 때문에 버림 | 행사 불일치와 후속 단계 실패 분리. 확인된 대기실과 같은 행사의 로그인 상태 유지 | `target_identity_verified`, `NOT_LIVE_YET`, 등록·재생 단계 |
| IR 목록 실패로 상세 행사 경로도 막힘 | 운영자 공식 상세 페이지 힌트 → 저장된 같은 발행사 상세 페이지 → IR 목록을 정상 재검증 | `route_started`, `target_verified` 또는 `route_failed` |
| 한 경로가 긴 시간 독점 | 경량 탐색 경로당 기본 45초, 합계 90초. 무거운 준비는 남은 경로에 예산 분배, 경로당 최대 240초 | 경로별 `timeout_seconds`, 부분 출력 |
| 실패 때 로그 덮어쓰기 | 콜·일정 버전·시도·캡처 세션 식별자를 모든 단계에 연결. 시도마다 별도 기록 | `.runtime/live-runs/<call_id>/<attempt_id>/` |
| 살아 있는 프로세스를 정상으로 오인 | 재생·PCM·STT 진행 관측. 재생 45초 정체, heartbeat 45초 정체, 오디오 적체 120초 이상 경고 | `playback.json`, `audio.json`, `stt.json` |
| Whisper 내부 호출이 멈춤 | 모델만 별도 프로세스에서 실행. 로딩 120초/추론 90초 제한, 최대 2회 모델 복구 | `model_phase`, `model_restarts`, `model_recovery_exhausted` |
| 고장 난 시점의 음성 유실 | 비정상 종료 PCM과 소비 위치·순번·세션 manifest 보존 | `.runtime/audio-rescue/*.manifest.json` |
| 저장 실패를 전사 실패와 혼동 | 문장 생성, 로컬 fsync, DB commit을 별도 기록 | `archive.json`의 생성·fsync·DB 순번 |
| 복구 대기가 방송 시간 대부분 차지 | 임박한 콜의 후보·폼·재생 오류와 복구 가능한 캡처 종료는 기본 1분 재시도 | DB의 retry reason/time과 운영 이벤트 |

진짜 CAPTCHA·이메일 확인·접근 차단은 자동으로 우회하지 않는다. 해당 경로를 보류하고 다른 공식 경로를 검증한다. 폼 선택자 오류는 이런 인증 장벽으로 분류하지 않는다.
공식 일정 재조회 자체의 기존 중복 방지와 주기적 일정 갱신은 유지한다. 1분 콜 재시도가 매번 외부 일정 API 호출을 뜻하지 않는다.

## 성공·대기·실패 판단

성공은 **원하는 행사 확인 → 플레이어 진행 → 해당 가상 오디오 유입 → 문장 생성 → fsync/DB 저장**을 현재 캡처 세션 기준으로 확인한다.
음악이나 무음, 텍스트가 아직 없음만으로 틀린 주소·행사 종료를 판정하지 않는다. PCM 측정은 음량 관측이며 음악/말소리의 정확한 자동 분류기가 아니다.

고정 60분 브라우저 hold로 생방송을 끊지 않는다. 기존의 검증된 행사 종료 신호와 마지막 오디오 배출을 유지한다. 4시간 세션 안전 제한과 자원 제한은 남는다.
Whisper 재시작은 부모 소비자의 PCM 위치와 문장 순번을 유지하고, 끝내지 못한 같은 오디오 구간을 재처리한다.
복구 소진 종료 코드 79를 완료로 처리하지 않는다. 녹음 파일을 보존하고 일반 재시도 절차로 돌아간다.

## 가장 먼저 실행할 조회

오늘 AZO의 DB 콜 ID는 568이다. 다음 명령은 조회만 한다.

```bash
docker exec ew-pipeline-scheduler python -B -m data_pipeline.tools.debug.live_control status --call-id 568
docker logs --since 3m --timestamps ew-pipeline-scheduler
```

`status`에서 `schedule_revision`, `capture_session_id`, `attempt`, 단계별 `progress`, 현재 세션의 `transcript.stored_rows/last_sequence/last_saved_at`를 확인한다.
과거의 같은 종목 전사 수나 컨테이너 healthy만으로 지금 방송 수집 여부를 판단하지 않는다.
활성 캡처 경고는 `.runtime/operations/events-YYYY-MM-DD.jsonl`에도 `live_progress_stalled`로 남는다. 콘솔의 `[LiveProgress]`에는 증거 디렉터리가 표시된다.
외부 메시지 알림은 별도 설정 없이 전송하지 않는다.

## 40분 방송 중 대응

| 관측 | 즉시 볼 것 | 복구 방향 |
| --- | --- | --- |
| 후보 0개 | `discovery` 후보 목록, 부분 로그, DOM/프레임 증거 | 페이지 접근 문제인지 아직 링크가 없는지 구분. 다른 공식 행사 페이지 정상 재검증 |
| 후보는 있지만 전부 탈락 | 날짜·분기·행사 종류별 탈락 이유 | 일정 또는 파서 확인. 날짜가 다른 콜을 강제 재생하지 않음 |
| 선택 뒤 이동 실패 | 선택 URL, 실제 URL, 팝업/iframe, 진단 JSON·화면 | 해당 요소/이동 코드 수정 후 다음 유효 후보 |
| 입력폼에서 정체 | `registration`, 필수/invalid 필드 이름, 제출 후 상태 | 입력값 노출 없이 필드/버튼 처리 수정. 인증 요청은 정상 인증 절차로 처리 |
| 재생 정체·음소거 | `playback`의 currentTime/paused/muted, 프레임 URL | 검증된 같은 행사 안에서 제한적으로 재생/음소거 복구. 커스텀 플레이어는 증거 확인 |
| PCM 바이트가 안 늘어남 | `audio`의 bytes/sec, sink/monitor 및 capture log | 가상 오디오 연결/생산자 문제 조사 |
| PCM은 늘지만 조용함 | RMS/peak와 플레이어 상태 | 실제 대기실 무음과 출력 문제 구분. 무음만으로 주소 제외 금지 |
| 음성은 있으나 STT 지연 | `model_phase`, inference age, 처리 바이트·backlog·RTF | 자동 모델 복구 확인 또는 현재 세션의 모델만 재시작 |
| 문장은 생성됐지만 DB 저장 지연 | `generated_sequence`, `fsynced_sequence`, `db_committed_sequence` | fsync spool을 유지하고 저장 재시도. 방송 재생을 중단하지 않음 |

목표: 이상 발생 후 1분 내 마지막 정상 단계를 찾고, 1~3분 내 해당 단계의 자동 복구 결과와 증거를 확인한다.
3~5분 안에도 후보를 못 찾으면 사람이 확인한 공식 상세 페이지를 재검증 경로로 넣는다. 이 시간은 운영 목표이며 사이트 접근 성공을 보장하지 않는다.
별도 개인 브라우저에서 소리가 들리는 것과 서버 가상 오디오에서 수집되는 것은 다르므로 세션·sink를 대조한다.

## 세션을 지정한 복구 명령

반드시 직전 `status`가 반환한 revision과 session 값을 넣는다. 아래 `<현재값>`은 예시 자리표시자다.

```bash
# STT 모델만 재시작 요청: 방송 브라우저·PCM 생산자 유지
docker exec ew-pipeline-scheduler python -B -m data_pipeline.tools.debug.live_control restart-stt --call-id 568 --expected-revision <현재revision> --expected-session <현재capture_session_id>

# 현재 캡처를 종료하고 일반 감시 재시도로 복귀: PCM은 비정상 종료 증거로 보존
docker exec ew-pipeline-scheduler python -B -m data_pipeline.tools.debug.live_control retry --call-id 568 --expected-revision <현재revision> --expected-session <현재capture_session_id>

# 발행사 공식 상세 페이지를 미검증 힌트로 추가; 시작 대기 시각은 그대로 둠
docker exec ew-pipeline-scheduler python -B -m data_pipeline.tools.debug.live_control route --call-id 568 --expected-revision <현재revision> --event-url https://about.autozone.com/events/event-details/q4-2026-autozone-inc-earnings-conference-call
```

실행 중인 캡처 복구 요청은 120초 안의 일치하는 콜·revision·시도·세션에만 적용된다. 접수 응답만으로 복구 성공을 판단하지 말고 다음 `status`에서 수락 및 진행 재개를 확인한다.
`route`는 현재 DB의 발행사 IR과 정확히 같은 호스트의 공식 페이지만 받는다. 날짜/회사/행사 검증을 우회하거나 제공사 주소를 검증 완료로 저장하지 않는다. 진행 중 세션은 바꾸지 않고 다음 탐색 때 사용한다.
비실행 상태 `retry`는 소유된 probe, 완료된 콜, 검증된 미래 시작 대기를 강제로 지우지 않는다. 대기 시각 전 강제 재시작 용도가 아니다.

## 증거·음성 보존 한도

- 단계별 현재 상태: `.runtime/live-runs/<call_id>/<attempt_id>/<stage>.json`.
- 같은 시도의 순차 사건: `events.jsonl`, 기본 2MiB에서 1개 이전 파일로 회전.
- 브라우저 JSON·화면: `.runtime/live-diagnostics/<TICKER>-...`; 종목 allowlist와 스크린샷 옵션 확인.
- 실제 캡처 출력/핸드셰이크: `.runtime/operations/probe-artifacts/ew-webcast-...-<attempt>-<route>-...`.
- 실패 오디오: `.runtime/audio-rescue/`, 기본 세션 512MiB, 전체 2GiB, 48시간. 실행 중인 녹음은 정리 대상에서 제외.
- 후보 실패 기억: `.runtime/live-candidates/`, 콜·revision·일정 증거별 분리, 기본 180초. 확인된 인증/차단 경로는 별도 긴 보류 유지.

전체 STT 소비자를 죽였다가 동일 순번으로 자동 재개하는 기능은 없다. 모델 프로세스 복구 범위를 넘은 장애는 보존 PCM과 manifest를 기준으로 중복 전사를 대조한 뒤 수동 복원한다.
PCM 보존은 playback-ready 이후부터다. 웹사이트에 들어가지 못했던 앞부분의 음성까지 복구하지는 못한다.
상시 상세 기록에는 개인정보·인증정보를 가리고, private runtime 경로와 파일 권한을 사용한다. 무제한 보관을 의미하지 않는다.

## 코드 반영과 종료 확인

상주 스케줄러의 Python 모듈 변경은 컨테이너 재기동이 필요하다. 브라우저/STT 코드 수정도 이미 실행 중인 프로세스에는 소급 적용되지 않는다.
수정 전 증거와 PCM을 보존하고, 가능하면 정상 재생 세션을 유지한 채 고장 난 단계만 복구한다. 전체 재기동은 활성 수집이 없거나 그 중단을 감수할 때 수행한다.
콜 종료 후에는 종료 증거, 마지막 오디오 소비량, fsync와 DB 순번, 세션 종료 마커를 대조한다. 프로세스 exit=0만으로 완주를 선언하지 않는다.
실제 외부 사이트의 폼·플레이어와 전 방송 완주는 생방송에서 최종 검증해야 한다.
