# 데이터파이프라인 현황 분석 — 2026-09-29 12:17 KST 기준

대상: 과거 버전 `/home/dheorb/workspace/projects/school/Earning-Whisperer`의 `ew-pipeline-scheduler`, `ew-mysql`. 실행 상태, DB SELECT, 운영/캡처 로그, 배포 해시, 정규 코드와 공식 기업 IR 정보를 읽기 전용으로 대조했다. 보고서 저장 외 코드·DB·서버 설정 변경은 없다.

## 결론

서버와 정규 감시는 동작한다. 9/27 수정본도 그대로 반영돼 있다. 그러나 그 이후 새로운 생방송 수집 실적은 없으며, 가까운 7개 기업 중 정확한 시작시각이 DB에 확보된 것은 CCL 한 개뿐이다. 공개 공식자료에는 7개 모두 시간이 있다. 현재 병목은 서버 프로세스 생존보다 올바른 행사·시간·웹캐스트 주소를 자동으로 확보하는 정확도다.

## 현재 운영

- pipeline/MySQL: running/healthy. 9/28 21:45:09 KST 재시작. 호스트 부팅 시각은 21:45:01.
- 조회 시점 활성 캡처/탐색 0개. 실제 감시 로그도 occupied capture slots=0, available=3.
- pipeline 약1.08GiB/10GiB, 조회 순간 CPU0.02%. 대기 상태의 수치이며 동시 STT 부하 평가가 아니다.
- 감시 1분 간격, 시간 보강 10분 간격. 재시작 후 로그에서 감시 작업866회·시간 보강86회 정상 완료를 확인했다. job exception/traceback/misfire/최대 중복실행 경고는 0회였다(03:10UTC 전후 수집 기준).
- 동시 탐색/캡처 설정 각각3. 실제3브라우저 오디오 분리 검증은 완료했지만 3개 실제 어닝콜의 동시 STT 속도·품질은 미검증이다.
- SEND_TO_BACKEND=false, SEND_TO_AI_ENGINE=false. 현재 전사는 파이프라인 DB에 보존하는 검증 모드다. 백엔드까지 전달되는 운영 상태는 아니다.
- 9/28 13:07:29~21:45:11 KST 약8시간38분 감시 로그 공백이 있다. 앞서07:40~08:29 약48분,00:20~00:32 약12분 공백도 있다. 로그 공백과 부팅을 확인했으며 각 공백의 전체 원인은 단정하지 않는다. 현재 healthy를 24시간 무중단 운영의 증거로 해석하면 안 된다.

## 개선 진행도

9/27 배포 manifest의18개 파일이 현재 컨테이너 파일과 전부 일치한다. URL에 datetime이 들어간 현재 DB 행은0개다.

완료된 작업:
1. 일반 텍스트 입력을 메뉴로 오인한 COST 등록폼 처리 수정.
2. 후속 IR 실패 때문에 확보한 시작시각이 삭제되는 문제 수정.
3. 시작시각이 webcast_url로 저장되는 변수 오류와 DB URL 타입 검증 수정.
4. 검증된 같은 행사 직접 주소를 IR 차단 대기와 분리해 재시도. 원 검증시각·6시간 유효기간·행사/일자/revision/인증 제한 유지.
5. 숨은 CAPTCHA 및 관련 없는 위젯에 의한 전역 장벽 오탐 수정.
6. 행사 동일성, live/replay 관측 근거, 텍스트 저장 여부를 분리해 진단 기록.

463개 관련 검증은9/27 반영 당시 결과다. 이번 점검에서 재실행한 숫자가 아니다. 9/27 이후 새 실제 생방송 성공으로 이 변경을 검증한 결과는 아직 없다. 전체 파이프라인 완성도를 단일 백분율로 산정할 근거도 없다. 구현/회귀검증 완료와 실전 검증 대기를 구분해야 한다.

## 최근 어닝콜에 대한 반응

9/25 이후 새 전사가 없고 마지막 저장은 DRI의9/24 22:39:08 KST다. DB의9/25~9/28 행사 항목도0건이다. 이는 우리 DB 관측 범위이며 전체 시장에 콜이 없었다는 증거는 아니다.

| 종목 | 현재 확인되는 결과 | 해석 |
|---|---|---|
| DRI | 229개 청크,9/24 21:23:53 캡처~22:40:17 정상 종료 | 21:31 개회~22:39 폐회 발화를 확보. 앞선 두 대기 세션은 idle timeout 후 재시도했음 |
| COST | 전사0, 실제 캡처0 | 지나간 실패 이력. 수정 이후 성공한 것으로 바꾸지 않았음. DB에는 아직upcoming/pending으로 잔류 |
| GIS | 26개 청크 | 생방송 후반 일부 |
| PAYX | 생방송304개, 별도 다시보기71개 | 둘을 합산해 생방송 수집량으로 계산하면 안 됨 |
| CTAS | 216개 청크, DBcompleted | 같은 행사 종료 후 다시보기. completed는 생방송 성공 증거가 아님 |

DRI의 누적 처리 RTF는 약0.25로 그 한 세션은 실시간을 따라갔다. 관측 backlog 최대12.185초. 그러나 반복문구·연도·숫자·고유명사 오인식이 있으며, 원음/정답 속기록 대조 정확도와 전체 발화 커버리지는 아직 측정하지 않았다. 종료 표시 청크에도 실제 텍스트가 있어 DRI229개를228개로 줄여 표현하면 안 된다.

9/27 이후 새 탐색은 NKE42회와 ACN16회였다. 마지막11:59KST 시도는 모두 LIVE_TARGET_UNCONFIRMED/pending, 실제 캡처0회다. NKE는 공식10/1행사와 맞지 않는9/29구행을 찾고 있고, ACN은 후보가 하나 적격으로 나와도 최종 날짜가 확인된 목적지로 연결되지 않았다. 세션 ID가 미리 할당된 attempt 파일만으로 캡처 시작을 판단하면 안 된다.

## 다가오는 공식 일정과 준비 상태

한국시간 기준. 이번 공식페이지 확인 결과를 수동으로 DB에 입력하지 않았다. 7개 기업/8개 DB행 중 exact time verified는CCL1개다.

| 종목 | 공식 시작 KST | 우리 서버 준비 상태 |
|---|---|---|
| [CCL](https://www.carnivalcorp.com/event/third-quarter-2026-earnings/) | 9/29 23:00 | 시각verified, 다음 재탐색 하한22:55. DB주소는과거행사목록, 직접웹캐스트NULL |
| [JBL](https://investors.jabil.com/news/news-details/2026/Jabil-Announces-Date-for-Fourth-Quarter-and-Fiscal-Year-2026-Earnings-Release-and-Investor-Briefing/default.aspx) | 9/30 21:30 | 날짜만 확보, exact/event/webcast 미확보 |
| [FDS](https://investor.factset.com/news-releases/news-release-details/factset-schedules-fourth-quarter-2026-earnings-call) | 9/30 22:00 | 날짜만 확보, exact/event/webcast 미확보 |
| [MU](https://investors.micron.com/news/press-release/2026/Micron-Technology-to-Report-Fiscal-Fourth-Quarter-Results-on-September-30-2026/default.aspx) | 10/1 05:30 | 날짜만 확보. 본콜과별도Post Earnings Analyst Call 구분필요 |
| [ACN](https://investor.accenture.com/news-and-events/events-calendar) | 10/1 21:00 | 날짜10/1 확보, 다른행사시간혼입으로exact NULL. 최종후보연결도미완성 |
| [MKC](https://ir.mccormick.com/node/33971) | 10/1 21:00 | 날짜만 확보, 공식페이지timeout, exact/event/webcast 미확보 |
| [NKE](https://investors.nike.com/investors/news-events-and-reports/investor-news/investor-news-details/2026/NIKE-Inc--Announces-First-Quarter-Fiscal-2027-Earnings-and-Conference-Call/default.aspx) | 10/2 06:00 | 공식미국날짜10/1과잘못된9/29후보중복, 정확시간미확보 |

13:00KST(뉴욕9/29자정)부터9/30일자의JBL/FDS/MU가 일반 날짜 감시 범위에 들어온다. 그 전에는정확시각미검증상태라도감시쿼리범위밖일수있다. 시간보강은별도로수행된다. NKE구행과ACN은provisional_watch의날짜여유범위때문에먼저탐색중이다. 재시도not-before는실제실행시각보장이아니라하한이다.

JBL/FDS는30분간격으로실제방송이겹칠수있고ACN/MKC는동시시작이다. 현재3슬롯은준비돼있으나동시음성인식의실전검증은별개다.

## 현재 확인된 핵심 결함

**CCL — 정확한 시간과 정확한 진입 주소의 연결이 미완성.** 공식 상세 페이지와ChorusCall에9/29 10:00EDT가 공개되어 DB시각은맞다. 하지만 현재정규enricher의읽기전용재현은past list+webcastNULL을다시반환한다. 투자자페이지의넓은행사문맥을Past Events/Today내비게이션링크가물려받고첫행사형링크가채택된다. 올바른상세링크가HTML에있는데도그곳까지따라가지않는다. 마지막실제사전탐색9/26에는후보68개가모두행사미확인으로제외됐다. 오늘22:55까지대기중이라는사실을접속준비완료로해석하면안된다.

**ACN — 공식시간의모호함이아닌파서범위오류.** 현재공식페이지의10/1 08:00ET Q4 earnings와10/14 08:30ET Investor Day를기존파서가같이모아conflicted=true로판정하는것을재현했다. 날짜이동허용을전체페이지에적용하기전에대상행사컨테이너를분리해야한다.

**NKE — 구일자후보와유효하지않은시작주소.** 공식어닝콜은10/1 14:00PT(한국10/2 06시)다. 미국10/1 13:15PT는실적공개시간으로콜시각이아니다. DB9/29구행이미대체상태로남고,stock.ir_url이행사식별suffix없는event-details/로끝나후보탐색이실패한다.

**검색 크레딧 소진.** Serper는credits_exhausted로차단중이다. 다음요청허용하한은9/29 21:55:24KST이며크레딧복구시각이아니다. 공식IR직접HTTP/브라우저는계속동작하지만틀린저장주소를검색으로보완하기어렵다.

## 시간 자동 수집의 통합 여부

정규작업에통합되어실제동작한다. 매일04:30KST날짜수집/출처대조,04:50및10분간격공식시간검증. HTTP우선, 가까운일정의미해결경우브라우저읽기를수행하고성공하면같은DB에저장한다. 기본예산은종목당2페이지/60초,배치6페이지/120초다. 감시브라우저가읽은시각도검증후DB저장경로로연결된다.

9/27~9/29 12:10KST 집계에서시간검증57회성공은모두CCL재확인이었다. 다른종목은합계406회미확인. 반복횟수이므로종목성공률로바꾸면안된다. NKE76페이지,FDS/JBL/MU각13페이지의실제브라우저재확인기록도있다. 즉작업이연결되지않은문제는아니며,공식페이지선택/행사범위/시간추출정확도개선이필요하다.

## 우선 대응 순서

1. 오늘CCL의상세행사→ChorusCall경로를정규후보선정에서확보하고입장/대기까지점검. exact time은이미맞으므로시각재입력보다주소선정수정이우선.
2. ACN의행사별시간범위를분리하고NKE의잘못된날짜중복행·실제상세경로를정리.
3. JBL/FDS/MU/MKC의공개공식시간을가져오지못하는경로를출처/DOM/파서별로좁혀수정. 검색서비스가소진돼도공식경로로진행할수있게해야함.
4. 방송시간동안호스트연속실행확인,진행단계별로그로후보/폼/재생/오디오/STT/DB저장을분리관찰.
5. 새실방송에서개선효과검증후음성대조정확도/전체발화커버리지평가,백엔드전달검증을별도진행.

근거: `.runtime/status-audit-20260929/`의현재DB/설정스냅샷·운영집계·최근캡처/예정일정별조사. 변경배포증거는`.runtime/failure-fixes-20260927/`및`PAST_LIVE_FIX_REPORT_20260927.md`.
