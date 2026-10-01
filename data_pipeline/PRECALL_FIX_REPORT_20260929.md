# 방송 전 데이터파이프라인 개선 — 2026-09-29

운영 대상: `/home/dheorb/workspace/projects/school/Earning-Whisperer`.
최신 프로젝트에는 변경하지 않았다. 첫 반영 UTC 2026-09-29T08:52:49.431551+00:00, 추가 반영 UTC 2026-09-29T09:14:24.460469+00:00.
운영 상태 확인 UTC 2026-09-29T09:14:45.342578+00:00. 변경 파일 25개의 최종 해시가 검증한 소스와 일치한다.

## 반영 결과

### 방송 전 대기

제공자 페이지의 대기 문구에 별도의 JavaScript 정규식을 쓰던 경로를 공통 Python 판정과 연결했다. 행사 URL·날짜·분기·표시 여부 검증은 유지했다. CCL 실제 공개 페이지에서 기존 null이던 대기 판정이 정확한 예정 시각으로 바뀌었다. 저장한 실제 DOM으로 22:55 조기 진입과 시작 후 대기 해제도 확인했다. 지금 열린 페이지에 폼 제출이나 재생을 실행해 성공을 가장하지 않았다.

### 다른 행사의 시간·주소 재사용 차단

기존 증명도 현재 행사 종류 규칙으로 재검증한다. 명시적인 Post Earnings Analyst Call 등은 본 어닝콜 증명으로 쓰지 않는다. 정규 시간 갱신 조회가 잘못된 저장 정보를 철회하면서 revision 및 변경 이력을 남긴다. 활성 캡처·완료·전사 이력·lease·동시 revision 변경은 보호한다. 잘못된 시간에서 유래한 scheduled_start_wait는 해제하고 인증·접근 차단 cooldown은 보존한다.

첫 배포 후 실제 MU 탐색에서 추가 경로가 드러났다. 저장 증명은 거부했지만 새 브라우저 후보는 후속 Analyst Call을 승인했고, 정상 Financial Call을 알아보지 못했다. 새 증명의 evidence에는 실제 제목 대신 일반적인 성공 문구만 들어갔다. 따라서 다음 공통 경로도 함께 수정했다.

- 본 행사와 후속 분석가 행사·Investor Day 등을 후보 단계에서 구분한다.
- 정상 Financial Call 표현을 인정하면서 종목·날짜·분기 조건을 유지한다.
- 증명에 선택한 후보의 실제 행사 문맥을 남긴다.
- 목적지 검사에서도 행사 종류를 검증한다.
- 이전 비대상 행사 증명은 연결된 원래 주소만 차단한다. 새 정상 주소와 공식 목록 재탐색에는 그 판정을 전이하지 않는다.

특정 종목이나 URL을 운영 코드에 예외로 넣지 않았다. 실제 MU 공개 목록의 정상 본행사와 후속 분석가 행사 두 카드를 근거로 회귀 검증했다. 폼 제출·방송 재생은 하지 않았다.

운영 MU335의 기존 잘못된 시각 및 주소는 정규 갱신으로 철회됐으며 revision은 2이다. schedule_change_history에 stored_non_earnings_event가 남았다. 종목별 시각/URL을 직접 SQL로 넣지 않았다. 현재 정확한 시작 시각은 미검증 상태이며, 공식 자료 재확인을 기다린다.

### 텍스트 발생과 발화 시작 구분

서로 다른 인접 두 오디오 창의 발화 근거가 확보되어야 긴 최초 대기를 끝내고 발화 후 무음 제한으로 전환한다. 명시적인 비음성·높은 모델 비음성 확률·지나친 압축률·동일 결과 반복은 첫 발화 확인 근거에서 제외한다. 모델 자식 프로세스에서 해당 메타데이터를 전달한다. 짧은 문장을 임의로 삭제하거나 첫 텍스트 저장을 보류하지 않는다.

speech_evidence_reason, last_speech_age_seconds, speech_continuity_confirmed, first_confirmed_speech_seconds를 남겨 텍스트 생성과 발화 확인을 구분한다. 이 기능은 음악 분류기가 아니다. 서로 다른 그럴듯한 환각은 연속해서 통과할 수 있으므로 실제 정확도는 원음과 대조해야 한다.

### DB 지연과 로컬 저장

현재 PyMySQL 경로의 connect/read/write/pool 제한을 각각 기본 5초로 설정했고 실제 실행 연결에서 {'connect': 5, 'read': 5, 'write': 5, 'pool': 5}를 확인했다. 개별 I/O 제한이며 여러 쿼리 전체의 5초 상한은 아니다.

Archive 재처리용 잠금을 파일 writer 잠금과 분리했다. DB 응답을 기다리는 동안 다른 콜의 로컬 fsync가 가능하다. 성공한 접두 항목만 ACK 처리하고 그 사이 추가된 텍스트를 보존한다. DB commit 후 ACK 실패는 멱등적인 재처리로 복구한다. 재처리 배치는 기본 100개이며 시간 예산도 둔다. 진행 중 DB 호출을 강제로 중단하는 2초 제한은 아니다.

## 검증 범위

- 최종 소스 67개 테스트 모듈: 1012개 통과, 1개 제외, 실패·오류 0.
- 제외 항목은 별도의 동시 스키마 migration 경쟁 검사다. 이번 작업은 스키마를 변경하지 않았다.
- 1차 수정의 실제 MySQL 8.0.46 격리 검증: 모순 행 2개 철회, 변경 이력 2개, 보호 대상 8개 유지, revision 경쟁·멱등성·cooldown·조회/claim 확인. 2차에서는 해당 storage 코드를 바꾸지 않았다.
- 실제 응답 없는 TCP 서버로 DB read timeout, DB 정체 중 다른 writer의 fsync, 중복 drainer 반환, append 보존 및 ACK 실패 복구를 확인했다.
- 가상 행사에서 링크 없음 → 여러 차례 대기 → 브라우저 재생 및 가상 오디오 → 캡처 배차를 재시작 없이 검증했다. 과거 행사 요청은 없었고, Whisper·운영 DB 경계는 대역을 썼다.
- 실제 Chromium/PulseAudio로 세 개 독립 오디오 경로와 일부 종료 후 나머지 경로 유지도 검사했다. 이는 세 개 실제 Whisper의 실시간 성능을 보장하지 않는다.

## 현재 운영 상태와 남은 확인

CCL600은 9월 29일 23:00 KST(14:00 UTC), 공식 ChorusCall 주소, revision 2을 유지한다. 정상 조건에서 22:40부터 탐색 대상이 되고 방송 전 대기를 거쳐 22:55 이후 재확인한다. 실제 배차 시각에는 1분 주기 및 실행 시간이 반영된다.

운영 서버의 자체 DB archive는 활성화되어 있고 backend/AI 전송은 비활성화되어 있다. 감독되는 live 세션의 기존 4시간 상한과 PCM 보존은 유지했다. 일부 공식 사이트의 403 및 아직 미확보된 본방송 시간은 남아 있다.

실전 성공 판정은 같은 attempt/session의 행사 확인 → 등록 → 플레이어 진행 → 해당 Pulse 오디오 → 실제 발화 → 저장 증가를 연결해 한다. 단순 텍스트 행 수나 대기 음악만으로 성공이라 하지 않는다. 종료 근거와 마지막 저장까지 확인해야 완주다. 전체 STT 소비자 자동 재개, 모든 발언의 정확도, 장기 DB 장애로 커진 spool, 현재 비활성 외부 outbox의 잠금 구조는 별도 과제다.

## 증거 위치

`.runtime/precall-fixes-20260929/`에 1차 백업, 배포·검증 기록과 CCL 실제 DOM이 있다.
`.runtime/precall-route-fix-20260929/`에 추가 백업, 최종 manifest/deployment/state-before/state-after 및 최종 회귀 결과가 있다.
실시간 단계 기록은 `.runtime/live-runs/<call_id>/<attempt_id>/`의 discovery, registration, playback, audio, stt, archive를 연결해 본다.

CCL 실전 조회(읽기 전용):

```bash
docker exec ew-pipeline-scheduler python -B -m data_pipeline.tools.debug.live_control status --call-id 600
docker logs --since 3m --timestamps ew-pipeline-scheduler
```

후보 문제는 선택 제목·날짜·URL과 탈락 이유, 폼 문제는 등록 단계와 차단 종류, 재생 문제는 player 진행, 오디오 문제는 해당 세션 Pulse/PCM 진행, STT 문제는 추론 age/backlog 및 확정 발화 age, 저장 문제는 generated/fsynced/db_committed 순번으로 구분한다.
