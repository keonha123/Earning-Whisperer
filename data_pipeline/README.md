발표할때 이부분을 참조해주세요.
ㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡ
data_pipeline/
├── __init__.py
├── collectors/              # [수집 레이어] 다양한 소스에서 데이터 및 URL 확보
│   ├── __init__.py
│   ├── base.py              # Collector 추상 클래스 및 Chain 로직
│   ├── stocks/              # 종목 리스트 확보 (Wikipedia 등)
│   ├── indicators/          # 정적 지표 연산 (52주 고점, 거래량 등)
│   ├── schedules/           # 어닝 일정 수집 (yfinance 등)
│   ├── prices/              # 주가 데이터 수집 (Ground Truth용)
│   └── streams/             # 실시간 입구 탐색 (IRWebsite, YouTubeLive)
│
├── stt_worker/              # [처리 레이어] 실시간 오디오-텍스트 변환 별동대
│   ├── __init__.py
│   ├── processor.py         # 오디오 스트림 추출 (yt-dlp, FFmpeg 제어)
│   ├── engine.py            # STT 엔진 인터페이스 (Whisper, Deepgram)
│   └── manager.py           # 워커 프로세스 생명주기 및 좀비 프로세스 관리
│
├── networking/              # [통신 레이어] 내부/외부 데이터 전송 전담
│   ├── __init__.py
│   ├── websockets.py        # 분석팀 대상 실시간 텍스트 푸시
│   └── stream_client.py     # 외부 오디오 소스와의 저수준 통신 관리
│
├── database.py              # [저장 레이어] SQLAlchemy 기반 DB 매니저 및 모델 정의
├── orchestrator.py          # [지휘 레이어] 수집 전략 조합 및 실행 로직 (공구함)
└── scheduler.py             # [제어 레이어] 시간/이벤트 기반 트리거 (중앙 통제실)

전체적인 data_pipeline흐름:
먼저 data_pipeline부분은 크게 collector부분과 database부분, orchestrator와 networking부분 그리고 stt_worker부분은 stt를 실시간으로 처리하는 별개의 디렉토리입니다. collector와 database부분 그리고 networking부분에서 각각의 함수들을 가져와서 orchestrator에서 조립해서 하나의 함수의 흐름으로 연결해서 그 함수를 scheduler의 에서 schedule모듈을 사용해서 데이터를 최신화시킵니다. 예를들어 orchestrator.sync_stock_master()함수는 500개의 기업정보를 찾아서 db에 저장하는 것까지의 흐름을 진행하는 함수인데 500개의 기업정보의 경우 변동이 크지 않기 때문에 하루에 장계시전에 1회정도 호출을 하는 식으로 스케줄을 관리합니다.

collector 흐름:
collector에는 수집할 여러가지 정보들을 기준으로 디렉토리가 존재하고 각각의 디렉토리는 해당 정보들을 어떻게 수집할지를 구현한 함수들이 있습니다. 이 함수들은 ex) self.price_chain = CollectorChain([YFinancePriceStrategy()])#orchestrator의 18 line에서 처럼 여러 방법들을 체인으로 엮어서 몃가지 수집방법이 api포화나 네트워크에러가 발생해서 작동하지 못해도 다른 방식이 체인으로 작동하기에 해당정보를 안정적으로 수집합니다.

stt_worker 흐름:
stt_worker 부분 다음과 같은 함수들로 흘러갑니다. 
1. processor.py에서 오디오 스트림 추출 및 관리 (FFmpeg 제어)
2. engine.py에서 STT 엔진 연동 (Whisper/Deepgram 인터페이스)
3. manager.py에서 워커의 생명주기 관리 (실행/종료/에러 복구)
processor.py부분은 아직 제한사항이 좀 많이 있습니디. 기존에는 어닝콜 url만을 획득하면 이 url입력을 바탕으로 .m3u8의 영상조각들을 자동으로 수집해주는 yt-dlp 라이브러리를 사용하려고 하였지만 ir사이트들이 자신들의 영상의 조각들을 쉽게 취득하도록 웹페이지를 구성하지 않아서 현재 당장에 실행가능하도록 웹에서 정보로 돌리는게 아니라 웹에서 운영체제로 넘겨받은 실제 소리데이터를 처리하는 장치에서 소리데이터를 가져와서 처리하는 방식으로 우회하였고 04-14일에 실행된 fastenal어닝콜에서 실제로 작동함을 확인하였습니다. 어차피 서버에서 돌릴 거지만 장치의존적인 문제는 추후에 처리해보도록 하겠습니다.

database.py 흐름:
collector의 각각의 하위 디렉토리에서 수집하는 정보에 대응하는 함수들로 구성되어있고 각각의 mysql에 접근해서 테이블에 저장합니다.

ㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡ



# 🎧 Data Pipeline (데이터 수집 서버) 요구사항 정의서

데이터 서버가 가지는 데이터
1. S&P500기업 리스트
2. 각 기업의 어닝콜 일정
3. 각 기업의 주가정보
4. 각 기업의 어닝콜 동영상

데이터 서버의 흐름
1. 각 데이터별 수집 단계
-1 정보원, 이 정보원들을 4~5가지를 체인룰로 엮어서 안정성과 신뢰성을 확보
-2 검증툴, 신뢰성 확보
-3 자동화툴

-1 정보원의 종류
-1-1 크롤링 위키피디아,각 공식 사이트 주소
-1-2 api활용 ,fmp,finnhub,alpha,polygon,lex
-1-3 라이브러리 야후

-2 검증툴
3개의 정보원의 정보가 모두 일치하면 통과
다르다면 다수결로 결정, 우선순위 체인으로 결정


-3 자동화툴
python APscheduler을 사용해서 정해진 시간과 주기로 정보툴을 호출


2. 저장 단계
데이터베이스에 수집한 정보를 저장

3. 전달 단계


ㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡ
## 1. 모듈의 역할 및 목표
이 모듈은 EarningWhisperer 프로젝트의 '귀' 역할을 담당합니다. 
유튜브 라이브나 오디오 스트림에서 실시간으로 기업의 어닝콜(실적 발표) 음성을 수집하고, 이를 초고속 STT(Speech-to-Text) 모델을 통해 텍스트로 변환한 뒤, 문맥이 유지되도록 가공하여 AI 추론 서버(AI Engine)로 전달하는 것이 핵심 목표입니다.

## 2. 핵심 기능 요구사항 (Core Features)

### [Feature 1] 실시간 오디오 스트리밍 캡처
- 대상 기업의 어닝콜 라이브 방송(주로 YouTube Live 또는 웹 캐스트) 오디오를 메모리 상에서 실시간으로 스트리밍하여 가져옵니다.
- **제약사항:** 영상(Video) 트래픽은 배제하고 오디오(Audio) 스트림만 추출하여 시스템 리소스를 최적화해야 합니다.

### [Feature 2] 초저지연 STT (Speech-to-Text) 변환
- 수집된 오디오 버퍼를 실시간으로 텍스트로 변환합니다.
- **추천 모델:** 일반 Whisper 대비 추론 속도가 압도적으로 빠른 **`faster-whisper`** (CTranslate2 엔진 기반)를 로컬 GPU 환경에서 구동합니다.
- **제약사항:** 금융/경제 영어 어휘의 인식률을 높여야 하며, 오디오 수신 후 텍스트 변환까지의 지연 시간(Latency)을 최소화해야 합니다.

### [Feature 3] 슬라이딩 윈도우(Sliding Window) 텍스트 청킹
- 끊임없이 이어지는 STT 텍스트를 단순히 시간 단위로 자를 경우 발생하는 **'문맥 단절(Context Fragmentation)'**을 방지해야 합니다.
- **슬라이딩 윈도우 적용:** 약 10~15초 단위의 Chunk를 생성하되, 직전 Chunk의 마지막 5~7초가량의 텍스트가 현재 Chunk의 앞부분에 **오버랩(Overlap)** 되도록 텍스트 조각을 묶어야 합니다.
- 가공된 텍스트 윈도우를 AI Engine의 REST API로 **비동기 전송(`POST`)**하여 데이터 수집 파이프라인이 블로킹(Blocking)되지 않도록 합니다.

## 3. 입출력 명세 (I/O Specification)
- **Input:** YouTube Live URL 또는 실시간 오디오 스트림 소스
- **Output:** AI 엔진으로 보내는 비동기 HTTP POST Request (`docs/api-spec.md`의 파이프라인 1번 규격 엄수)

## 4. 기술 스택 (Python)
- **Audio Capture:** `yt-dlp` (유튜브 스트림 추출), `ffmpeg-python` (오디오 포맷 및 버퍼 처리)
- **STT Engine:** `faster-whisper` (초저지연 음성 인식)
- **Network/Async:** `asyncio`, `httpx` 또는 `aiohttp` (비동기 HTTP API 통신용)

## 5. 완료 기준 (Definition of Done - DoD)
이 모듈의 개발이 완료되었다고 평가받으려면 다음 테스트를 통과해야 합니다.
1. [ ] **스트리밍 테스트:** 과거 테슬라나 엔비디아의 어닝콜 유튜브 라이브(또는 녹화본) URL을 입력했을 때, 메모리 누수 없이 오디오 스트림을 지속적으로 캡처하는가?
2. [ ] **STT 속도/정확도 테스트:** 영어 오디오가 `faster-whisper`를 거쳐 텍스트로 정상 변환되며, 금융 용어(EBITDA, Margin 등)가 비교적 정확히 인식되는가?
3. [ ] **슬라이딩 윈도우 및 비동기 전송 테스트:** 변환된 텍스트가 이전 문맥과 오버랩된 채로 10~15초 주기로 나뉘며, AI 서버로 전송 시 파이프라인 병목(Blocking) 없이 1초 이내에 비동기 전송되는가?