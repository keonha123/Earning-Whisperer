# CCL 생방송 수집 사후 분석 — 2026-09-30

대상은 과거 프로젝트 `/home/dheorb/workspace/projects/school/Earning-Whisperer`의 운영 서버와 CCL call 600이다. 모든 시각은 별도 표기가 없으면 한국 시각이다. 예정 시작은 9월 29일 23:00이었다. 9월 30일 01:15 이후 운영 DB·로그·전체 세션 산출물을 읽고, 저장된 DOM 및 현재 공식 페이지를 격리 환경에서 재현했다. 운영 코드·DB·서버 설정은 변경하거나 재시작하지 않았다.

## 결론

**CCL 생방송 수집은 실패했다. 실제 캡처가 시작되지 않았고 전사 저장은 0건이다.** 중간에 STT가 느려지거나 종료된 사례가 아니다. 후보를 확정하고 제공자 등록 화면으로 진입하기 전 단계에서 반복 실패했다.

서버는 9월 29일 18:14:24부터 계속 실행 중이고 healthy, RestartCount 0, OOMKilled false다. 어제 배포한 변경 파일 25개의 해시도 일치한다. 서버 프로세스 생존과 실제 수집 성공은 다른 결과였다.

01:17:21 기준 전체 CCL runtime 시도는 87개다. 이 중 이번 밤 22:25~01:15 탐색은 86개이며, 약 2분마다 재시도했다. 이 숫자는 사전 할당된 시도·세션 식별자 수이며 캡처 횟수가 아니다. 실제 calls.capture_attempts는 0이고 capture_started_at, capture_session_id는 NULL이다.

## 실제 진행 순서

| 시각 | 운영 기록 | 결과 |
|---|---|---|
| 22:04 | 공식 상세 페이지·IR 페이지 조회 성공, 23:00 시작 시각과 ChorusCall 주소 보유 | revision 2, 정확한 진입 경로 유지 |
| 22:14 | 상세 페이지 HTTP timeout. IR 목록에서 시각만 확보한 부분 성공을 verified로 저장 | revision 3. 정확한 시각은 남았지만 기존 webcast_url이 NULL로 덮임 |
| 22:24 | 두 공식 페이지를 다시 확인. has_webcast_route=true였지만 conflicted=true | revision 4. ambiguous_call_time으로 시작 시각 철회. 다시 찾은 주소도 저장되지 않음 |
| 22:25 이후 | 행사 상세 페이지와 IR 목록을 반복 탐색 | View Webcast 또는 AUDIO 링크를 발견해도 행사 근거 부족/잘못된 날짜 판정으로 제외 |
| 23:00 전후~01:15 | 같은 실패를 약 2분 간격으로 반복 | 등록·재생·오디오·STT 진입 및 전사 저장 없음 |

최신 상태는 upcoming/pending, 정확한 시작 시각과 webcast_url은 NULL, 마지막 오류는 `LIVE_TARGET_UNCONFIRMED no dated target candidate`다. 정상 완료로 처리된 상태가 아니다.

## 확인한 결함

### 1. 부분적인 최신 조회가 더 좋은 기존 주소를 지움 — 운영 이력으로 확정

시각은 찾았지만 제공자 주소를 못 찾은 조회 결과에 webcast_url=None이 들어간다. `enricher.py`가 이를 새 검증값에 그대로 넣고, storage가 None을 포함해 DB에 적용한다. 일시적인 상세 페이지 timeout을 기존 주소의 명시적 폐기와 구분하지 않는다.

- [enricher.py](/home/dheorb/workspace/projects/school/Earning-Whisperer/data_pipeline/collectors/schedules/enricher.py:379): 현재 조회의 best.webcast_url을 검증 결과에 덮어쓴다.
- [storage/schedules.py](/home/dheorb/workspace/projects/school/Earning-Whisperer/data_pipeline/storage/schedules.py:1132): None을 포함한 변경값을 적용한다.
- schedule_change_history 119: 정확한 ChorusCall 주소 → NULL, revision 2 → 3, reason=official_time.

이는 어제 추가한 비대상 행사 증명 철회(stored_non_earnings_event)가 발동한 사례가 아니다.

### 2. 회계기간 종료일을 어닝콜 날짜로 취급 — 당시 후보 기록과 현재 코드 재현

IR의 `Q3 2026 QUARTER ENDED AUG 31, 2026`는 분기 실적의 기준일이다. 그런데 그 옆 Earnings Webcast/AUDIO 문구와 결합하면서 8월 31일을 어닝콜 날짜로 취급했다.

22:25:48 당시 IR 후보 기록에서, 올바른 CCL 행사 상세 페이지로 가는 AUDIO 링크가 `candidate date 2026-08-31 != target 2026-09-29`로 제외된 것이 확인된다.

현재 공식 HTML을 DB·브라우저 접근 없이 파서에 재입력했을 때도 같은 문제를 재현했다. 정확한 시작 시각 후보는 9/29 14:00 UTC 하나뿐인데, discovery 날짜 집합에 9/29와 8/31이 들어가 conflicted=true가 된다. 기존의 회계분기 일치 기반 날짜 이동 허용이 회계기간 종료일까지 행사일로 승인한다.

- [enricher.py](/home/dheorb/workspace/projects/school/Earning-Whisperer/data_pipeline/collectors/schedules/enricher.py:365): 서로 다른 discovery 날짜를 충돌로 처리한다.
- [enricher.py](/home/dheorb/workspace/projects/school/Earning-Whisperer/data_pipeline/collectors/schedules/enricher.py:1392): 회계연도·분기가 같으면 날짜 이동을 허용하는 경로.
- [enricher.py](/home/dheorb/workspace/projects/school/Earning-Whisperer/data_pipeline/collectors/schedules/enricher.py:416): 시간 충돌이 있으면 발견한 경로의 저장도 건너뛴다.

22:24 운영 로그에는 충돌한 개별 날짜·문맥이 저장되지 않았다. 따라서 당시 파서의 내부 값을 직접 관측한 것은 아니다. 다만 바로 다음 실제 브라우저 기록의 잘못된 8/31 판정과 현재 파서 재현이 같은 원인을 뒷받침한다. 로그의 ambiguous_call_time은 실제 시각 충돌뿐 아니라 행사 날짜 충돌까지 합쳐 부르는 부정확한 진단이다.

### 3. 상세 페이지에 있는 정상 후보의 증거를 충분히 읽지 못함 — 당시 기록 및 이전/현재 코드로 재현

상세 페이지에는 올바른 View Webcast 링크가 있었다. 후보 추출 결과에는 다음 문맥만 들어갔다.

`Date: September 29 Time: 10:00 am - 11:00 am View Webcast`

같은 행사에 속한 `Third Quarter 2026 Earnings` 제목과 날짜 요소의 `title="2026-09-29"` 값은 증거에 포함되지 않았다. 그 결과 현재 행사로 확인할 수 없다며 event_identity_unconfirmed로 거절했다.

어제 17:15에 저장한 공식 상세 HTML을 네트워크 없는 Chromium에서 재현했다. MU 수정 이전의 백업 함수와 현재 함수 모두 같은 후보 문맥을 만들고 똑같이 거절했다. **어제 MU 카드 경계 변경이 새로 만든 회귀가 아니라, 기존 CCL 상세 페이지 처리에서 놓친 결함이다.** 같은 행사 제목과 구조화된 날짜를 메모리의 후보 문맥에 보완하자 기존의 엄격한 판정 조건을 유지해도 승인됐다. 이는 진단용 실험이며 운영 수정은 하지 않았다.

## 저장·오디오 확인

- transcript_segments 전체에서 ticker=CCL 또는 CCL 세션 접두어 또는 call_id=600을 조회: 0행, 0세션, 0종료 마커.
- 전체 87개 시도의 audio/stt/archive 단계 이벤트: 0.
- capture.json은 모두 탐색 시작 기록이며 실제 캡처 승격·실행 기록은 없음.
- CCL 복구 PCM/음성 manifest 및 미반영 archive spool: 없음.
- 등록 제출이나 CAPTCHA 실패, mute 또는 가상 오디오 실패가 이번 사건의 직접 실패 지점이라는 근거는 없다. 그 단계에 도달하지 않았다.

따라서 전사 정확도·숫자/고유명사 정확도·첫/마지막 발화 누락·STT 실시간 처리율을 평가할 실제 CCL 결과물이 없다. 검사 로그 속 CCL/speech-test는 어제 가짜 모델 회귀 검사이며 실전 수집으로 계산하지 않았다.

## 이번에 효과를 확인하지 못한 개선과 검증 공백

재시도 루프는 멈추지 않았다. 하지만 같은 잘못된 판정을 반복했고, 기존 정상 주소를 복원하거나 더 풍부한 행사 문맥을 확보하는 경로로 전환하지 못했다.

제공자 대기 문구 수정, 발화 시작 판단, DB 지연 보호는 이번 CCL에서 실행 단계에 도달하지 못했으므로 효과를 검증할 수 없다. 01:19 전후 기존 ChorusCall 주소를 읽기 전용으로 확인했을 때 HTTP 200과 정확한 CCL Q3 제목·9/29 10:00 EDT·등록폼이 보였다. 폼 제출이나 재생은 하지 않았으며 이 현재 관측을 방송 당시 입장 성공의 증거로 사용하지 않는다.

어제의 1,012개 통과 검증에는 **정상 일정 보유 → 부분 HTTP 실패 → 기존 주소 손실 → IR 내용 변경 → 날짜 충돌 → 실제 CCL 후보 재탐색** 연쇄가 빠져 있었다. 제공자 대기 화면을 직접 읽는 검사만으로 이 앞단 경로를 확인할 수 없었다.

## 다음 수정 우선순위

1. 시각·주소·행사 식별 근거를 독립적으로 갱신한다. 부분 조회에서 미확인인 값으로 마지막 유효 주소를 지우지 않고, 취소·다른 행사 등 명시적 반증과 구별한다. 시간 불확실 시에도 검증 가능한 공식 경로 재확인은 허용한다.
2. 분기/회계연도 종료일, 보도자료 게시일, 콜 시작일을 구분한다. 회계분기 일치만으로 임의의 날짜 이동을 승인하지 않는다. 일정 파서와 브라우저 후보 판정에 같은 의미 구분을 적용한다.
3. 같은 행사 상세 영역의 제목과 time/datetime/abbr title/해당 Event 구조화 정보를 클릭 대상에 결합한다. 주변의 다른 행사 근거를 섞거나 날짜 보호를 단순 해제하지 않는다.
4. 충돌한 값·출처·원문과 주소 유지/교체/철회 사유를 로그에 남긴다. 실제 CCL DOM 및 위 연쇄를 회귀 검사에 넣고, 예정 시각 이후에도 대상 확인·음성·첫 텍스트가 없는 상황을 별도로 드러내야 한다.

## 증거

`data_pipeline/.runtime/ccl-audit-20260930/`에 DB 이력, 운영 이벤트, 코드 해시 대조, 당시 후보 분석, 이전/현재 코드 비교, 현재 공식 HTML 재현과 전체 세션 저장 결과를 보존한다.

핵심 파일: `db-schedule.json`, `ccl-operations.json`, `provider/attempts.json`, `provider/first-ir-candidates.json`, `provider/candidate-reproduction.json`, `schedule/saved-pages-reproduction.json`, `stt/REPORT.md`, `stt/runtime.json`, `current-provider/provider-dom.json`.
