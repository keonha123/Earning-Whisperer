# 임박한 어닝콜 수집 준비도 점검 — 2026-09-29

점검 대상: `/home/dheorb/workspace/projects/school/Earning-Whisperer`의 운영 데이터파이프라인. 마지막 DB 조회 2026-09-29 17:16:54 KST, 컨테이너 상태 확인 17:15 KST. 코드·설정·운영 DB를 수정하거나 서버를 재시작하지 않았다. 최신 프로젝트는 이번 점검 대상이 아니다.

## 결론

**현재 서버가 모든 임박한 어닝콜에서 문제없이 텍스트를 추출할 준비가 끝났다고 판단할 수 없다.** CCL과 ACN은 정확한 일정과 공식 웹캐스트 주소를 확보했고, 올바른 플레이어에 도달하면 가상 오디오→STT→자체 DB 저장으로 연결되는 경로가 있다. 그러나 실제 CCL 사전 대기 화면 인식 결함과 MU의 잘못된 기존 행사 증명/재시도 시각 유지 문제를 재현했다. 등록·재생 UI가 아직 공개되지 않은 CCL의 입장 이후 과정도 미검증이다.

이 결론은 README 검토가 아니라 스케줄 조회·배차·브라우저 상태 판단·재생 수명·캡처 셸·모델 감독·STT·저장 코드를 읽고, 운영 DB SELECT 및 현재 공개 페이지 DOM을 대조한 결과다. 전체 저장소 모든 코드나 모든 제공자 경로를 검증했다는 뜻은 아니다.

## 현재 실행 상태와 일정

- 파이프라인과 MySQL 컨테이너는 running/healthy. 파이프라인 시작 17:04:55 KST.
- 17:16:54 조회 시 활성 캡처/탐색은 없음. 앞선 17:10 조회에는 NKE/JBL 탐색만 있었고 실제 STT 캡처는 없었다. 정상 감시 대기와 생방송 수집 성공은 구분해야 한다.
- 자동 탐색·캡처 enabled, 발견/캡처 동시성 각각 3. 시간 보강 작업 등록 간격 10분, 라이브 배차 1분. 개별 일정의 재시도 제한·최신성 조건 때문에 모든 종목을 매 10분 반드시 새로 확인하는 것은 아니다.
- 로컬 STT 모델과 FFmpeg/PulseAudio 실행 파일 존재. 실제 현재 설정은 CPU 2 threads/콜, 컨테이너 8 CPU/10 GiB. 파일 존재와 설치 확인만 했으며 이번 점검에서 모델을 로드하지 않았다.
- 자체 transcript archive 활성화. backend/AI 전송은 모두 false이므로 현재 성공 목표는 자체 DB 저장이다.

| 대상 | DB/공식 시각 (KST) | 현재 판단 |
|---|---|---|
| CCL 600 | 9/29 23:00 | 공식 상세·ChorusCall 주소와 시각 일치. 공개 페이지는 사전 대기 상태. 입장 이후는 미검증, 대기 분류 결함 확인 |
| MU 335 | DB 10/1 07:00 / 본 어닝콜 공식 10/1 05:30 | DB는 Post Earnings Analyst Call을 선택한 상태. 자동 보강이 고치지 못하면 본방송 시작을 놓침 |
| ACN 528 | 10/1 21:00 | 공식 시각·행사 주소 확보. 중복 1557은 528로 superseded. 실제 등록·재생·STT는 미검증 |
| JBL 779, FDS 194 | DB 정확한 시각·행사 주소 없음 | 보강 단계 issuer_browser_access_denied. 준비 완료로 판단할 수 없음 |
| NKE 343/4913 | DB 정확한 시각·행사 주소 없음 | 오래된 날짜 행과 새 일정이 공존. 모두 접근 차단 기록. 잘못된 옛 날짜로 잦은 탐색 발생 |
| MKC 835 | DB 정확한 시각·행사 주소 없음 | no_official_time. 행사/플레이어까지 확인된 상태 아님 |

CCL은 현재 retry 제한이 NULL인 상태이므로, 시각이 계속 유효하게 유지된다는 조건에서 22:40부터 탐색 대상이다. 미래 시작을 확인하면 22:55까지 대기한다. 이는 SQL상 가능한 최초 시각이며 실제 시작은 작업 시간과 1분 배차 주기에 따라 늦어진다.

## 발견 1 — MU 기존 오선정 증명이 새 코드에서도 재사용됨 (높은 우선순위)

현재 DB `schedule_evidence`에 `Micron's Post Earnings Analyst Call`이라고 명시되어 있다. 그런데 기존 `issuer-route-v2` 메타데이터가 event_type을 earnings_call로 표시했고, `_stored_target_proof`는 이 메타데이터를 신뢰해 현재도 유효한 증명으로 반환한다. 공식 본 어닝콜은 9/30 14:30 Mountain Time, 즉 10/1 05:30 KST이다. DB가 선택한 별도 행사는 07:00 KST이고 재시도 해제 시각은 06:55이다.

- `data_pipeline/stt_worker/manager.py:222`: 기존 증명의 시간·도메인·분기 등을 검사하지만 제목을 최신 행사 종류 규칙으로 다시 판정하지 않는다.
- `data_pipeline/storage/schedules.py:734`: 접근 실패 시 기존 검증 시각·주소를 유지한다. 정상 근거를 일시적인 네트워크 실패로 삭제하지 않으려는 동작이지만 이미 틀린 근거도 유지한다.
- `data_pipeline/storage/live_calls.py:75`: 시각이 120분 넘으면 오래된 것으로 표시한다.
- 같은 파일 `:126`, `:219`: 그래도 옛 scheduled_start_wait의 retry_not_before를 무조건 적용한다. 오래된 시간에서 날짜 기반 탐색으로 돌아가는 경로가 해당 대기 시각에 막힌다.

실제 후보 SELECT 함수를 읽기 전용으로 실행해, 현 행이 유지될 경우 본방송 시작 20:30 UTC에는 MU가 제외되고 21:55 UTC에야 대상이 되는 것을 재현했다. **잘못 저장된 시간은 90분 늦고, 실제 탐색 허용은 본방송 시작보다 85분 늦다.** 이후 정규 보강이 올바르게 수정하면 달라질 수 있으므로 실패가 확정되었다는 뜻은 아니다.

일반화된 개선 방향: 기존 저장 증명에도 현재 행사 종류 규칙을 적용하고, 잘못된 종류의 기존 증명·시각·대기 제한을 함께 무효화한다. 시각이 오래되거나 일정 revision이 바뀌면 그 시각에서 유도한 scheduled_start_wait도 재평가한다. 인증·403 경로 제한은 별개로 유지한다. 단순 MU 시각 SQL 수정보다 이 공통 경로를 고쳐야 한다.

공식 근거: [Micron 본 어닝콜 발표](https://investors.micron.com/news/press-release/2026/Micron-Technology-to-Report-Fiscal-Fourth-Quarter-Results-on-September-30-2026/default.aspx).

## 발견 2 — CCL의 실제 사전 대기 문구를 놓침 (오늘 방송 전 우선 처리)

현재 공식 상세 페이지의 View Webcast가 DB의 ChorusCall 주소와 일치한다. 실제 Chromium 렌더링 결과는 HTTP 200, 올바른 Q3 2026 제목·날짜, upcoming/eventStatus=0이고 입력폼·iframe·audio/video 요소는 없다. 화면은 시작 직전에 다시 방문하라는 안내다.

- `data_pipeline/collectors/streams/browser/session.py:480`: JavaScript 사전 필터에는 has-not-started/not-yet/will-begin 계열만 있다.
- `data_pipeline/collectors/streams/browser/rules.py:408`: Python 공통 패턴에는 실제 CCL의 return-to-this-page 문구까지 포함되어 있다.
- 앞의 JavaScript 필터에서 문구를 버리므로 Python 판정에 도달하지 못한다.

실제 공개 DOM·공식 링크에서 만든 메모리 내 증명·현재 경로 검증 함수를 사용한 재현 결과: 경로 검증 true, `_detect_not_live_event` null, 같은 본문을 공통 판정기에 주면 정상 대기 문구 반환. 운영 DB의 증명은 수정하지 않았다.

22:55 이후에도 사전 페이지라면 대기 대신 후보 없음/재생 실패로 처리될 수 있다. 다만 선택 행사 근거를 직접 전달하는 일부 경로는 공통 패턴을 사용하므로 모든 경로가 반드시 실패하지는 않는다. 외부 스케줄러도 영구 중단하지 않고 pending/재시도로 돌아간다. 문제는 최대 약 600초의 후보 탐색 예산과 이후 1분 재시도가 소모될 수 있어 방송 초반을 놓칠 위험이다. 정확한 전체 실패 출력은 실제 캡처를 실행하지 않아 재현하지 않았다.

일반화된 개선 방향: 브라우저에서는 크기가 제한된 해당 행사 문맥을 수집하고, 공통 대기 판정기로 한 번만 판단한다. 서로 다른 JS/Python 문구 목록을 유지하지 않는다. 현재 행사·날짜 검증은 유지하고 실제 CCL 페이지 fixture와 다른 행사 문구 대조를 회귀 검증한다.

## 발견 3 — 의미 없는 STT 결과도 첫 발화로 취급 (코드로 확인, 현재 장애 아님)

`data_pipeline/stt_worker/take.py:711` 이후는 비어 있지 않은 모델 결과를 저장하고 speech_seen=true로 바꾼다. 대기 음악에서 생성된 환각 문장도 이 경로에 들어갈 수 있다. 그러면 최초 발화 대기 3600초에서 발화 후 무문장 제한 600초로 바뀐다. 이후 10분간 결과가 없으면 실제 발언 전 종료·재접속이 발생할 수 있다. 반대로 환각 문장이 계속 나오면 문장 수는 증가해도 실제 발화 수집 증거가 아니다.

VAD는 적용되어 있지만 의미 있는 어닝콜 발화임을 보장하지 않는다. `live_end.py`의 non-speech 필터는 종료 판단용이며 저장/첫 발화 판단을 보호하지 않는다. 개선 시 음성 근거와 연속성으로 첫 발화를 확인하되 짧은 실제 발언까지 지우지 않도록 구분해야 한다.

## 발견 4 — 응답 없는 DB 쓰기가 STT까지 정지시킬 수 있음 (코드·실제 설정 확인, 현재 장애 아님)

- `data_pipeline/storage/connection.py:15`: DB read/write timeout 미설정. 실제 설치 드라이버에서 둘 다 None임을 확인했다. connect timeout/pool timeout과 다르다.
- `data_pipeline/stt_worker/delivery.py:324`: 공유 archive spool의 exclusive flock을 잡은 채 동기 MySQL 쓰기를 수행한다.
- DB가 연결 후 응답하지 않으면 한 STT 소비자가 멈추고 다른 콜 저장도 해당 잠금을 기다릴 수 있다. 모델 감독 timeout은 이 저장 단계까지 감싸지 않는다.

독립 PCM 기록은 계속될 수 있어 오디오는 남지만 실시간 텍스트 출력을 보장하지 못한다. 공통 개선 방향은 DB I/O 제한, 짧은 spool 잠금, durable spool과 DB 반영의 분리다. 이번 점검에서 실제 DB 장애 주입은 하지 않았다.

## 기존 개선으로 확보된 부분과 남은 한계

1. `manager.py:696`은 성공한 접속 주소·브라우저·오디오 환경을 실제 캡처에 이어 준다. 일반 IR 페이지를 다시 열어 다른 후보로 바뀌는 문제를 막는 구조다.
2. `run_webcast_audio_capture.sh:646` 이후는 플레이어/행사 확인 직후 PCM을 기록하고, STT 로딩 중에도 보존한다. 이후에 들어온 음성만 보호하며 브라우저 도착 전 발언은 복구하지 못한다.
3. `lifetime.py:302`의 supervised live는 1시간 sleep으로 브라우저를 무조건 닫지 않는다. 현재 셸/STT 경로의 최대 세션 안전 제한은 4시간이다. 첫 문장 대기 1시간, 발화 후 무문장 10분, PCM 없음 45초 등 별도 조건은 존재한다.
4. 모델 로드 120초·추론 90초 제한과 모델만 2회 재시도가 있다. 전체 STT 소비자가 죽으면 같은 오디오 위치에서 자동 재개하는 기능은 없다. 실패 PCM을 남겨 수동 복구할 수 있다.
5. 프레임은 20초/중첩 2초이며 첫 결과는 음성 축적과 추론 후 나온다. 단어 단위 즉시 전송은 아니다. 처리 지연이 없더라도 몇 초 무출력을 즉시 실패로 보면 안 된다.
6. 자체 파일 spool에 fsync 후 DB 저장, 30초 주기 재처리 경로가 있다. 종료 성공은 해당 세션 텍스트와 현재 행사에 연결된 종료 근거까지 요구한다. 모든 발언의 완전성·숫자/고유명사 정확도를 증명하지는 않는다.
7. 이전 DRI 단일 콜 수집/성능은 긍정적 근거지만 실제 3개 동시 STT 성능은 미검증이다. idle/probe CPU 사용량으로 동시 실시간 처리 성능을 계산할 수 없다.
8. NKE는 시간 보강 단계 403과 실제 탐색 단계 LIVE_TARGET_UNCONFIRMED가 다르게 기록된다. 실제 오류 분류를 유지하지 못해 잘못된 날짜의 차단 경로를 반복 탐색한다. 지난 배포 이전에도 있던 동작이다.
9. 캡처 도중 일반 transient 오류는 3→6→12→…60분 backoff다. live_capture_incomplete는 별도로 1분 재시도하지만 모든 오류가 빠르게 복구되는 것은 아니다. `storage/policies.py:236`.

## 생방송에서 판단할 관측 지점

`.runtime/live-runs/<call_id>/<attempt_id>/`의 단계별 snapshot/events와 해당 capture log를 동일 attempt/session 기준으로 연결한다.

| 관측 | 의미 / 먼저 볼 곳 |
|---|---|
| 대상 행사 증명 없음 | 현재 행사 종류·날짜·분기·공식 링크·최종 URL과 배차 대기 이유 확인 |
| 올바른 URL + 아직 예정 화면 | NOT_LIVE_YET, 다음 retry, 동일 경로 유지 확인. 후보를 함부로 과거 행사로 교체하지 않음 |
| 등록 단계 정체 | form 발견·제출 결과·validation·인증 또는 접근 차단 코드 확인 |
| 플레이어 시간 진행 없음 | pause/mute/readystate/오류·현재 frame URL 확인 |
| 플레이어 진행 + PCM 신호 없음 | 해당 세션 Pulse sink/monitor, RMS/peak 확인. 파일 크기 증가만으로 소리가 있다고 판단하지 않음 |
| PCM 증가 + STT 없음 | model ready/추론 경과·backlog·마지막 heartbeat 확인. 추론 지연인지 DB 쓰기 정체인지 분리 |
| 문장 생성 + DB 미증가 | generated→fsynced→db_committed sequence 중 멈춘 지점, 공유 잠금·DB I/O 확인 |
| 텍스트는 생기지만 음악뿐 | 실제 발언 원음과 비교. 문장 수나 speech_seen만으로 성공 처리하지 않음 |

성공 최소 조건은 **현재 올바른 생방송의 실제 발화가 해당 capture session의 DB 행으로 저장됨**이다. 전체 완주는 별도 종료 근거와 마지막 발언 확인이 필요하다.

## 점검 근거와 권장 순서

이번 점검은 운영 DB SELECT, 현재 DOM의 인식 함수 재현, 코드·설정·파일 확인이다. 방송 UI가 아직 없으므로 등록·재생·음성·실시간 STT 전체 실행은 하지 않았다. 지난 배포의 730개 통과/1개 skip은 일반 회귀 근거이며 이번 방송 성공 보장이 아니다. 기존 DB에 남은 오선정 근거와 실제 제공자 대기 문구가 왜 추가 현장 검증 대상인지 이번 재현이 보여 준다.

우선순위:
1. 오늘 CCL 대기 인식 통합 및 actual-DOM 회귀 검증.
2. MU에서 드러난 기존 행사 증명 재검증 + 오래된 시각 기반 대기 해제의 공통 수정.
3. NKE/JBL/FDS 등 403·시간/행사 주소 미확보의 정확한 분류와 공식 대체 경로 확인.
4. 음악/첫 발화 판단과 DB 쓰기 timeout·잠금 개선.
5. 실제 동시 STT 부하 및 전체 소비자 복구 검증.

증거 디렉터리: `data_pipeline/.runtime/readiness-audit-20260929/`. `final-state.json`, `schedule_sql_readonly.json`, `provider/provider-dom.json`, screenshot 및 세부 분석 포함. 이번 작업에서 수정한 것은 이 보고서와 감사 증거 파일뿐이다.
