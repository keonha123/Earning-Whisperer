# 데이터파이프라인 운영 감사 — 2026-09-27

기준: 한국시간 2026-09-27 05:18~05:25. 대상은 과거 버전 `/home/dheorb/workspace/projects/school/Earning-Whisperer`와 `ew-pipeline-scheduler`, `ew-mysql`이다. 운영 프로세스, 최근 배포 이후 로그, DB와 캡처별 종료·저장 증거, 실제 코드 및 공식 IR 공지를 대조했다. 운영 코드·DB·프로세스를 변경하거나 재시작하지 않았다.

## 결론

서버와 정규 작업은 계속 실행 중이고 DRI 생방송의 시작부터 종료까지 수집한 증거가 있다. 종료 발언을 인식하고 잔여 오디오를 처리해 정상 종료하는 개선도 실제로 작동했다. 다만 COST는 미수집이며, 정확 시각 자동 확보·올바른 행사 경로 탐색·방송 전 대기·STT 정확도에는 결함이 남아 있다. 서버 healthy와 모든 어닝콜 수집 성공을 구분해야 한다.

## 현재 운영 상태

- 스케줄러 시작: 9/24 00:26:35 KST. 자동 재시작 0회, OOM 없음, healthy.
- MySQL healthy. 현재 캡처·탐색 0건, 준비 및 예약 0건, 사용 가능한 슬롯 3개. 최근 watch_cycle 9/27 05:22:36도 정상 idle.
- 스케줄러 메모리 약 940MiB / 상한 10GiB, 관측 CPU 13.71%. 디스크 여유 약 501GiB.
- transcript_outbox 비어 있음. DB 저장 재시도를 기다리는 임시 archive 파일도 0바이트/0건.
- `SEND_TO_BACKEND=false`, `SEND_TO_AI_ENGINE=false`: 현재 수집·DB 저장 검증 운영이며 최신 배포 백엔드/AI로 전달하는 상태는 아니다.
- Docker healthcheck는 DB ping이다. 업무 성공까지 판단하는 검사는 아니므로 캡처별 지표를 별도로 봐야 한다.

## 최근 수집 결과

| 종목 | 실제 결과 | 근거 |
|---|---|---|
| DRI | 생방송 완주 증거 있음 | 9/24 21:23:53~22:40:17, 229구간·82,924자, seq0~228 연속 |
| [COST](https://investor.costco.com/news/news-details/2026/Costco-Wholesale-Corporation-Reports-Fourth-Quarter-and-Fiscal-Year-2026-Operating-Results/default.aspx) | 가장 최근 공식 일정은 9/25 06:00 KST, 미수집 | DRI보다8시간30분 늦은 콜. 캡처 세션·전사 없음. 마지막 탐색은9/25 12:59 KST |
| CTAS | 재방송 완주 | 9/24 00:27:19~01:32:55, 216구간·59,228자. 당일 행사 녹음 재생으로 분리해야 함 |
| PAYX | 기존 생방송 원본 보존 | 304구간, ended 유지. 재방송 71구간은 별도 세션 |
| GIS | 기존 후반 일부 보존 | 26구간, ended 유지 |

DRI는 방송 전 연결했고 21:31:01 개회부터 22:39:08 종료·disconnect 안내까지 저장했다. live HLS 출처와 사전 대기→실제 개회 흐름도 일치한다. 종료 안내 후 처리된 음성 72초·조용한 구간 4회를 확인하여 `operator_closing_confirmed → event_ended → exit_code=0 → input_drained=true`로 마쳤다. CTAS도 동일 종료 흐름이 작동했다.

DRI 내부 오디오 큐의 dropped_bytes=0, 모델 재시작 0회. 생성·파일 저장·DB 저장 마지막 번호가 228로 일치한다. RTF=0.2757로 해당 실행에서는 STT가 실시간을 따라갔다. 이는 내부 유실 징후가 없다는 근거이며, 외부 스트림 패킷 손실이나 단어 오인식까지 없었다는 증거는 아니다.

DB의 CTAS status=completed는 수집 작업이 끝났다는 뜻이다. 재방송을 생방송 성공으로 계산하면 안 된다. 기존 `capture-source-review.json`과 재생목록 ENDLIST·64분39.888초 증거가 따로 보존되어 있다. live/replay가 DB의 대표 상태에 통합되지 않은 것은 남은 과제다.


COST의 차단 원인은 구체적으로 확인했다. 직접 Q4 웹캐스트는 필수 입력 1개가 남은 FORM_AUTOMATION_FAILED였고, 대체 공식 IR·행사 페이지는 CAPTCHA에 걸려 AUTH_REQUIRED로 12시간 대기했다. 마지막 공식 경로 차단은 9/25 01:05~13:05 KST이며 실제 콜 06:00이 이 사이에 있었다. 반복 검사로 대기 시간이 계속 연장된 것은 아니다.

`application/live_watch.py:308`은 discovery에서 행사 동일성을 확인하지 못하면 캡처 탐색 전에 반환한다. `stt_worker/manager.py:99`의 discovery는 같은 공식 issuer의 event/IR 경로를 우선하고 보호된 경로는 접속 없이 건너뛴다. 따라서 이미 알고 있던 Q4 주소에도 다시 도달하지 못했다. 저장된 공식 근거를 재사용하는 우회도 COST의 확인시각이 9/14로 오래되고 구조화 증거가 없어 통과하지 못했다. 직접 웹캐스트 자체의 12시간 차단이 아닌데 공식 IR의 차단이 직접 웹캐스트 재시도를 함께 막은 구조적 결합이다.

### 방송 전 대기와 텍스트 품질

DRI는 완주 세션 이전에 20:40~21:01, 21:03~21:20 두 차례 대기 중 재접속했다. 짧은 `Thank you.` 등의 텍스트 1~2개를 저장한 뒤 600초 무발화 제한으로 종료했다. `stt_worker/take.py:735`는 어떤 텍스트라도 speech_seen=True로 바꾸므로, 초기 대기 3,600초 대신 무발화 600초 조건이 적용되는 구조와 일치한다. 음악·잡음에 의한 오인식 가능성이 있으나 원음 대조 없이 확정하지 않는다. 이번에는 재시도가 이어져 개회를 확보했다.

DRI 첫 안내에서 FY2027이 `fiscal year 2007`로, CTAS에서는 FY2027/2017 혼동과 회사명 `Sintas` 오인식이 보인다. 후반 일부 구절 반복도 있다. 따라서 전사가 저장됐다는 사실과 텍스트 정확도를 구분한다. 원음·공식 정답 전문 대조 없이 정확도 백분율이나 WER을 제시하지 않는다.

## 시작 시각 수집의 정규 통합

사람이 따로 확인한 시간을 수동으로 DB에 넣어야만 동작하는 구조가 아니다. 실제 정규 작업은 다음과 같다.

1. 시작 시 및 매일 04:30 KST: 광범위 일정 수집·Yahoo/Nasdaq 대조·공식 재검증.
2. 매일 04:50 및 10분 간격: 향후 14일 중 최대 20건을 선택하여 정확한 시각 검증.
3. 공식 HTTP 페이지를 먼저 읽고, 시각이 불명확한 가까운 일정에 Chromium을 사용한다. 뉴욕 날짜 기준 -2~+2일, 종목당 2페이지·60초, 배치 전체 6페이지·120초 예산이다.
4. 공식 행사 동일성·날짜·시간대를 검증해 scheduled_at_utc, source_timezone, schedule_source, schedule_evidence, time_verified_at 및 revision을 저장한다. 감시 브라우저가 얻은 시간도 같은 DB 경로로 반영한다.
5. 일정이 바뀌면 revision과 관련 대기·캐시를 갱신하고 다음 감시가 새 DB 시각을 사용한다. 충돌하는 시각은 추측해서 확정하지 않는다.

9/24 UTC 정규 배치 144/144, 9/25 144/144, 9/26 20:16 UTC까지 122/122, 총410회 완료를 확인했다. 이 정규 작업의 예외·누락·중복 실행 제한 경고는 없었다. 마지막 확인 실행은 9/27 05:16:36 KST, 다음 예약은 05:26:36이다.

자동 DB 반영 사례: CCL이 9/27 04:36:37 KST에 `official_ir_page_http`로 재검증되어 9/29 23:00 KST가 저장됐다. 같은 기간 개별 검사545건 중 성공3건은 모두 CCL 재확인이고 미확인542건이었다. 검사 횟수는 반복을 포함하므로 종목별 성공률로 계산하지 않는다. 브라우저 사용126회·210페이지도 실제 로그에 존재한다.

9/27 새벽에는 미래 일정 대부분이 뉴욕 날짜 기준 +2일 밖이라 HTTP 검증만 수행했다. 비용 절약 범위는 의도대로 적용됐지만 공식 페이지에 공개된 시간을 아직 못 얻는 경우가 남아 있다. NKE/JBL/MU HTTP403, FDS/MKC timeout, ACN/STZ 시간 충돌 등이 기록됐다.

## 다가오는 일정과 DB 준비 상태

아래 한국시간은 공식 발표를 확인한 값이며 이번 감사에서 DB에 입력하지 않았다. 현재 7종목8개 후보 행 중 정확 시각 저장은 CCL 1개다.

| 종목 | 공식 시작 한국시간 | DB/감시 상태 |
|---|---|---|
| [CCL](https://www.carnivalcorp.com/event/third-quarter-2026-earnings/) | 9/29 23:00 | 시각 검증 완료. 단 event_url은 과거 행사 목록이고 webcast_url 없음 |
| [JBL](https://investors.jabil.com/news/news-details/2026/Jabil-Announces-Date-for-Fourth-Quarter-and-Fiscal-Year-2026-Earnings-Release-and-Investor-Briefing/default.aspx) | 9/30 21:30 | 날짜만 있음, 시각 미확인·HTTP403 |
| [FDS](https://investor.factset.com/news-and-events/events) | 9/30 22:00 | 날짜만 있음, 시각 미확인·HTTP timeout |
| [MU](https://investors.micron.com/events-and-presentations/event-details/2026/Microns-Fourth-Quarter-2026-Financial-Call/default.aspx) | 10/1 05:30 | 날짜만 있음, 시각 미확인·HTTP403 |
| [ACN](https://newsroom.accenture.com/news/2026/accenture-to-announce-fourth-quarter-and-full-year-fiscal-2026-results) | 10/1 21:00 | 날짜10/1 반영, 정확 시각은 충돌 판정으로 해제 |
| [MKC](https://ir.mccormick.com/node/33971) | 10/1 21:00 | 날짜만 있음, 시각 미확인·HTTP timeout |
| [NKE](https://investors.nike.com/investors/news-events-and-reports/investor-news/investor-news-details/2026/NIKE-Inc--Announces-First-Quarter-Fiscal-2027-Earnings-and-Conference-Call/default.aspx) | 10/2 06:00* | 9/29 잠정·불일치 후보와 10/1 후보 공존, 시각 미확인·HTTP403 |

* NKE 공식 보도자료의 10/1 14:00 PT를 날짜별 태평양 시간으로 환산했다. 행사 카드는 PST라고 적어 1시간 표기 충돌 위험이 있다. 확인 없이 고정 UTC-8로 저장하면 안 된다.

CCL 상세 페이지에는 Choruscall 행사 링크가 이미 공개돼 있지만 DB는 `events//list/?eventDisplay=past`를 가리킨다. 날짜·시각 추출과 재생할 정확한 경로 저장 사이에 빈틈이 있다. 실제 상세 링크는 https://www.carnivalcorp.com/event/third-quarter-2026-earnings/ 이다.

CCL의 확인된 시각과 유효한 후보가 유지되면 기본 5분 전인 22:55 전후 접속·대기를 준비하도록 설계돼 있다. 시각 미확정 일정은 날짜 기반 감시와 재검증을 계속한다. 현재 idle은 고장이 아니라 실행 시점·재시도 대기 조건에 맞는 후보가 없는 상태다. 다만 NKE의 잘못된 잠정 날짜를 계속 탐색하는 것은 불필요한 시도의 원인이 된다.

JBL과 FDS는 30분 간격, ACN과 MKC는 동시 시작이다. 현재 슬롯 설정은 3개이지만 실제 두 콜의 품질·부하는 각각 관찰해야 한다.

## 우선 개선할 사항

1. CCL을 포함한 가까운 일정에서 정확한 행사 상세→웹캐스트 경로를 함께 저장한다. 시간 검증만 성공하고 목록 페이지가 남는 상태를 해소해야 한다.
2. HTTP403/timeout 시 공식 보도자료·대체 공식 호스트와 제한된 브라우저 경로를 조합한다. 공개된 시각이 자동 수집에 반영되지 않는 원인을 종목별로 고친다. 브라우저 범위를 무조건 늘리기보다 예산 안에서 임박·불확실한 행사를 우선한다.
3. 방송 전 짧은 텍스트 하나로 본방송 시작을 판정하지 않도록 대기 상태와 유의미한 연속 발화 판정을 분리한다.
4. COST처럼 오래 반복되는 보호 경로 실패를 별도 원인으로 분류하고, 경로 대기 기한·재검증·알림을 명확히 한다. 1,433개 대기 실패 기록은 실제 HTTP 접속1,433회를 뜻하지 않는다.
5. live/replay와 수집 범위를 DB의 결과 상태에 반영하고, 시기가 지난 미수집 행사가 upcoming으로 남지 않도록 정리한다.
6. 종목명·회계연도·금액·반복 문장의 STT 품질을 실제 음성 표본과 대조한다. 데이터 저장 성공과 내용 정확도는 다른 검증이다.

부가 운영 문제: 최근 배포 이후 Yahoo401 InvalidCrumb91줄과 일부 종목 가격 미조회 로그가 있다. 현재 스케줄러 정지를 일으키지는 않았지만 공급원 상태를 따로 점검할 필요가 있다. 최근3일 운영 경보 이벤트는 없고 경보 active도 비어 있다. 현재 경보는 멈춘 작업·큐 적체·차단 종목 수 등에 집중되어 있어, 단일 종목의 장기 미수집이나 반복 NO_CANDIDATE를 충분히 드러내지 못한다.
