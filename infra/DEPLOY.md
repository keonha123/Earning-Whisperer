# 배포 운영 매뉴얼

시연용 서버의 구성과 운영 방법입니다. 2026년 9월 13일 기준입니다.

- 대상 독자: 팀원 전원
- 다루는 범위: AWS 시연 서버의 구성 · 연결 · 재배포 · 검증 · 비용
- 로컬 개발 환경은 [부록 A](#부록-a--로컬-개발-환경), 보류된 웹 배포 경로는 [부록 B](#부록-b--보류된-웹-배포-경로) 를 참고하세요

---

## 1. 무엇이 올라가 있나

| 서버에 있는 것 | 서버에 없는 것 |
|---|---|
| backend (Spring Boot jar, systemd) | data_pipeline (STT · 웹캐스트 수집 — [10장](#10-제약) 참고) |
| ai-engine (FastAPI/uvicorn, systemd) | frontend (보류 — [부록 B](#부록-b--보류된-웹-배포-경로)) |
| MySQL 8, Redis 7, PostgreSQL 16, Qdrant 1.19 (Docker) | trading-terminal (각자 노트북에서 실행) |

시연은 백엔드가 월마트 FY2027 Q2 어닝콜(2026-08-20) 트랜스크립트를 재생하는 방식입니다. 스크립트는 `backend/src/main/resources/data/demo-earnings-call.json` 이고 실제 원문 발췌 24세그먼트입니다. STT 는 돌지 않습니다.

**팩트체크와 종합 판단은 ai-engine 이 재생 중에 실시간으로 생성합니다.** 미리 만들어 둔 판정값이 아니어서, 그 화면을 보여주려면 ai-engine 과 PostgreSQL · Qdrant 가 함께 떠 있어야 합니다.

### 서버는 평소 꺼져 있습니다

AWS 는 서버가 존재하는 시간에 과금하기 때문에, **당분간 개발이나 리허설을 할 때만 켜 두고 그 외에는 중지해 둡니다.** 상시 운영이 아닙니다 (실행 중 월 약 $24, 중지 시 약 $5 — [8장](#8-비용과-메모리)).

그래서 앱을 띄웠는데 데이터가 들어오지 않는다면 서버가 꺼져 있을 가능성이 먼저입니다. 켜는 방법과 필요한 권한은 [4장](#4-일상-운영)에 있습니다. 인스턴스를 켜면 약 1분 뒤부터 붙을 수 있습니다 — 컨테이너와 서비스가 부팅과 함께 자동으로 올라옵니다.

---

## 2. 서버 정보

| 항목 | 값 |
|---|---|
| AWS 계정 | 885721133289 |
| 리전 | 아시아 태평양 (서울) `ap-northeast-2` |
| 인스턴스 | `ew-backend`, `i-0e932167662542771`, t3.small (2 vCPU / 2GB) |
| OS · 디스크 | Ubuntu 24.04, 16GB gp3 |
| 고정 IP | `43.200.26.70` (탄력적 IP) |
| 보안 그룹 | `launch-wizard-2` — 인바운드 22(SSH), 8082(백엔드) 전체 개방 |
| SSH | `ssh ubuntu@43.200.26.70` (키페어 `ew-mac`) |
| 백엔드 | `http://43.200.26.70:8082` · 상태 확인 `GET /actuator/health` |
| ai-engine | `127.0.0.1:8000` (외부 비공개, 백엔드만 호출) · 상태 확인 `GET /health` |
| IAM CLI 사용자 | `ew-cli` (Describe/Start/Stop/ModifyInstanceAttribute 권한만) |

서버 파일은 `/opt/earning-whisperer/` 에 모여 있습니다.

```
backend.jar           Spring Boot 실행 파일
backend.env           백엔드 환경변수 (권한 600)
ai-engine/            ai-engine 코드와 .venv
ai-engine.env         ai-engine 환경변수 (권한 600)
.env                  compose 가 읽는 MySQL · PostgreSQL 비밀번호 (권한 600)
docker-compose.yml    컨테이너 4개 정의 (저장소의 infra/aws/docker-compose.yml 과 동일)
```

systemd 유닛 두 개는 `/etc/systemd/system/` 에 있고, 저장소의 `infra/aws/` 아래 같은 이름 파일과 동일합니다.

- `earning-whisperer-backend.service`
- `earning-whisperer-ai-engine.service`

`*.env` 파일에는 시크릿이 들어 있어 저장소에 없습니다. 어떤 키가 필요한지는 `backend/.env.example` 과 `ai-engine/.env.example` 을 보시면 됩니다.

---

## 3. 연결 방법

서버에 붙어서 앱을 띄우는 절차입니다. DB · Redis · 백엔드는 각자 설치하지 않아도 됩니다.

### 3-1. 받아오기

Node 20 이상이 필요합니다. `node -v` 로 먼저 확인해 주세요.

```bash
git clone git@github.com:keonha123/Earning-Whisperer.git
cd Earning-Whisperer/trading-terminal
npm install
```

`npm install` 은 Electron 바이너리를 내려받느라 2~3분쯤 걸립니다.

Windows 를 쓰신다면 **WSL 터미널과 Windows 터미널을 섞어 쓰지 않는 편이 좋습니다.** `@rollup/rollup-linux-x64-gnu` 같은 네이티브 모듈이 깨집니다. clone 부터 실행까지 같은 환경에서 하시고, 이미 깨졌다면 `node_modules` 를 지우고 다시 설치하면 됩니다.

### 3-2. 환경변수

`trading-terminal/.env.example` 을 `.env.local` 로 복사하고 세 값을 채웁니다. `.env.local` 은 git ignored 라서 저장소를 받아도 들어 있지 않습니다.

```
BACKEND_URL=http://43.200.26.70:8082
OAUTH_GOOGLE_CLIENT_ID=<keonha 에게 요청>
OAUTH_KAKAO_CLIENT_ID=<keonha 에게 요청>
```

두 OAuth client ID 는 새로 발급받지 않고 팀이 쓰는 값을 그대로 쓰면 됩니다. client secret 은 서버만 가지고 있어서 앱에는 필요하지 않습니다. **client ID 값은 저장소에 두지 않기로 했습니다** — `keonha` 에게 요청하시면 됩니다.

앱의 OAuth 콜백은 `http://localhost:9000/auth/callback` 이라 서버 위치와 무관하고, 서버 `backend.env` 의 허용 목록에도 들어 있습니다. **9000 포트를 쓰는 다른 프로그램이 떠 있으면 미리 종료해 주세요.**

### 3-3. 실행

```bash
npm run dev
```

Electron 창이 뜨면 정상입니다. 로그인은 구글 또는 카카오로 하시면 기본 브라우저가 열렸다가 앱으로 돌아옵니다.

**서버가 켜져 있어야 로그인이 됩니다.** 평소에는 중지해 두므로, 브라우저에서 `http://43.200.26.70:8082/actuator/health` 를 열어 `{"status":"UP"}` 이 나오는지 먼저 확인하시면 됩니다. 응답이 없으면 인스턴스가 꺼져 있는 상태입니다 ([1장](#1-무엇이-올라가-있나)).

### 3-4. 각자 준비해야 하는 것 / 서버에 이미 있는 것

| 키 | 어디에 있나 | 별도 발급이 필요한가 |
|---|---|---|
| KIS 앱 키 · 시크릿 · 계좌번호 · HTS ID | **각자 노트북의 OS 키체인** | **네.** 각자 KIS 계정으로 발급하고 앱 설정 화면에서 등록합니다 |
| OAuth client ID (Google · Kakao) | 각자 `.env.local` | 아니요. `keonha` 에게 요청하면 됩니다 |
| `GEMINI_API_KEY` | 서버 `ai-engine.env` | 아니요 |
| `FINNHUB_API_KEY` · `FMP_API_KEY` | 서버 `backend.env` | 아니요 |
| OAuth client secret, `JWT_SECRET`, `INTERNAL_SECRET`, DB 비밀번호 | 서버 `backend.env` | 아니요. 클라이언트가 쓰지 않습니다 |

정리하면 **각자 발급해야 하는 것은 KIS 자격증명뿐입니다.** OAuth client ID 두 개는 `keonha` 에게 요청하시면 됩니다. 나머지 API 키는 서버에서만 쓰이고 터미널은 백엔드를 통해 결과만 받습니다. 터미널이 Finnhub · FMP · Gemini 를 직접 호출하는 경로는 없습니다.

KIS 자격증명이 각자인 이유는 주문이 각자 계좌로 나가기 때문입니다. 이 값들은 OS 키체인에 저장되고 백엔드 DB 에는 없어서, 붙는 서버를 바꿔도 다시 입력할 필요가 없습니다.

### 3-5. 알아두실 점

- **`.env.local` 은 앱 기동 시점에만 읽습니다.** 값을 바꾸면 앱을 다시 띄워야 합니다.
- **서버 DB 는 로컬과 별개입니다.** 처음 접속하면 거래 내역 · 보유종목이 비어 있습니다. 같은 소셜 계정으로 로그인하면 사용자 계정은 이어집니다.
- **로컬 백엔드를 함께 띄우지 마세요.** 같은 `FINNHUB_API_KEY` 로 웹소켓 두 개가 붙으면 무료 등급에서 서로 연결이 끊깁니다.

### 3-6. 안 될 때

먼저 서버가 살아있는지 봅니다. 브라우저에서 `http://43.200.26.70:8082/actuator/health` 를 열어 `{"status":"UP"}` 이 나오면 서버는 정상입니다.

| 증상 | 원인 |
|---|---|
| health 가 열리지 않는다 | **인스턴스가 중지 상태입니다.** 평소에는 꺼 두므로 가장 흔한 경우입니다 ([4장](#4-일상-운영)) |
| 창은 뜨는데 데이터가 안 들어온다 | 서버가 꺼져 있거나, `BACKEND_URL` 이 비어 있거나 오타입니다. 값을 바꾼 뒤 앱을 재시작하지 않은 경우도 많습니다 |
| 로그인 후 앱으로 돌아오지 않는다 | 9000 포트가 다른 프로그램에 점유되어 있습니다 |
| 모듈을 찾지 못한다는 오류 | WSL · Windows 터미널 혼용 문제입니다 ([3-1](#3-1-받아오기)) |

---

## 4. 일상 운영

### 상태 확인

```bash
systemctl status earning-whisperer-backend earning-whisperer-ai-engine
docker ps
curl -s localhost:8082/actuator/health     # {"status":"UP"}
curl -s localhost:8000/health              # {"status":"ok",...}
free -h
```

### 로그

```bash
journalctl -u earning-whisperer-backend -f
journalctl -u earning-whisperer-ai-engine -f
journalctl -u earning-whisperer-backend -u earning-whisperer-ai-engine -f   # 함께 보기
```

### 재시작

```bash
sudo systemctl restart earning-whisperer-backend
sudo systemctl restart earning-whisperer-ai-engine
cd /opt/earning-whisperer && docker compose restart     # DB · Redis · Qdrant
```

### 켜고 끄기

```bash
aws ec2 start-instances --region ap-northeast-2 --instance-ids i-0e932167662542771
aws ec2 stop-instances  --region ap-northeast-2 --instance-ids i-0e932167662542771
```

탄력적 IP 가 붙어 있어 다시 켜도 주소는 같습니다. 컨테이너 4개는 `restart: unless-stopped`, systemd 유닛 2개는 `enabled` 상태라 부팅과 함께 자동으로 올라옵니다. 부팅 후 약 1분이면 health 가 UP 이 됩니다.

콘솔에서 작업할 때는 우측 상단 리전이 서울인지 먼저 확인하세요. Billing 화면을 거치면 리전이 버지니아(us-east-1)로 바뀌어, 인스턴스가 사라진 것처럼 보입니다.

### 서버 접근이 필요할 때

인스턴스를 켜고 끄는 것과 SSH 접속은 서로 다른 권한입니다. 필요한 쪽을 저장소 관리자에게 요청하면 됩니다.

| 하려는 것 | 필요한 것 | 요청할 때 전달할 것 |
|---|---|---|
| 인스턴스 켜기 · 끄기 | AWS IAM 사용자 | 없음 (관리자가 계정을 발급합니다) |
| SSH 접속 (로그 확인 · 재배포) | 서버에 공개키 등록 | 본인 SSH **공개키** (`~/.ssh/id_ed25519.pub`, 없으면 `ssh-keygen -t ed25519` 로 생성) |

두 가지를 알아두시면 됩니다.

- **꺼진 인스턴스에는 SSH 로 접속할 수 없습니다.** 서버가 중지 상태면 먼저 켜야 하고, 켜는 것은 IAM 권한입니다.
- **개인키는 주고받지 않습니다.** 공개키만 전달하시면 관리자가 서버에 등록합니다. 회수도 그 한 줄을 지우는 것으로 끝납니다.

IAM 사용자를 받으면 아래 명령으로 켜고 끌 수 있습니다. 콘솔에서는 EC2 → 인스턴스 선택 → 인스턴스 상태 메뉴에서도 됩니다.

```bash
aws ec2 start-instances --region ap-northeast-2 --instance-ids i-0e932167662542771
aws ec2 stop-instances  --region ap-northeast-2 --instance-ids i-0e932167662542771
```

권한 범위는 해당 인스턴스의 조회 · 시작 · 정지로 제한되어 있습니다. 다른 AWS 리소스에는 접근할 수 없습니다.

접근 권한이 필요한 경우는 이렇습니다.

| 역할 | 필요한 것 |
|---|---|
| 앱만 쓰는 경우 | 없음. [3장](#3-연결-방법) 의 `.env.local` 설정만 하면 됩니다 |
| 개발 중 서버를 직접 켜야 하는 경우 | IAM |
| ai-engine 재배포 | IAM + 백엔드 인스턴스 SSH |
| data_pipeline 배포 | IAM + 파이프라인 인스턴스 SSH ([11장](#11-data_pipeline-배포-계획)) |

---|---|---|
| 인스턴스 켜기 · 끄기 | **IAM** (콘솔 로그인 또는 액세스 키) | 가능 — 이 방법뿐입니다 |
| SSH 접속 (로그 확인 · 재배포) | 서버의 `~/.ssh/authorized_keys` | 불가능 — 꺼진 서버에는 접속할 수 없습니다 |

SSH 공개키는 이미 켜져 있는 서버에 들어가는 열쇠일 뿐이라, 그것만으로는 인스턴스를 켤 수 없습니다.

#### SSH — 개인키를 나누지 않고 공개키를 등록합니다

키페어 `ew-mac` 의 개인키를 복사해 나누면 유출 시 회수할 방법이 없습니다. 각자 공개키를 받아 서버에 추가하는 방식을 씁니다.

```bash
# 팀원이 자기 공개키를 전달 (없으면 ssh-keygen -t ed25519 로 생성)
# 서버에서 한 줄 추가
echo "<받은 공개키>" >> ~/.ssh/authorized_keys
```

회수는 그 줄만 지우면 됩니다. 서버가 켜져 있을 때만 등록할 수 있습니다.

#### IAM — 인스턴스를 제한한 정책을 그룹에 붙입니다

현재 CLI 사용자 `ew-cli` 가 Describe · Start · Stop · ModifyInstanceAttribute 권한만 갖고 있습니다. 팀원에게도 같은 범위로 부여합니다.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "DescribeAll",
      "Effect": "Allow",
      "Action": ["ec2:DescribeInstances", "ec2:DescribeInstanceStatus"],
      "Resource": "*"
    },
    {
      "Sid": "StartStopOurInstances",
      "Effect": "Allow",
      "Action": ["ec2:StartInstances", "ec2:StopInstances"],
      "Resource": [
        "arn:aws:ec2:ap-northeast-2:885721133289:instance/i-0e932167662542771"
      ]
    }
  ]
}
```

`ec2:Describe*` 는 리소스 제한이 지원되지 않는 API 라 `"*"` 로 둡니다. 인스턴스 목록 조회뿐이라 문제되지 않습니다. data_pipeline 인스턴스를 만들면 그 ARN 을 `Resource` 에 추가하면 됩니다.

절차는 이렇습니다.

1. IAM 그룹 `ew-operators` 를 만들고 위 정책을 연결합니다
2. 팀원별 IAM 사용자를 만들어 그룹에 넣습니다 — 공유 사용자 하나를 돌려쓰면 누가 켰는지 추적되지 않고 한 명만 회수할 수도 없습니다
3. 콘솔만 쓸 사람에게는 액세스 키를 발급하지 않습니다. CLI 를 쓸 사람에게만 발급합니다
4. **MFA 를 켜 주세요.** 액세스 키가 유출되면 남이 인스턴스를 켜서 과금이 발생합니다

#### 누구에게 무엇이 필요한가

| 역할 | IAM (켜고 끄기) | SSH |
|---|---|---|
| 앱만 쓰는 팀원 | 개발 중 직접 켜야 한다면 부여 | 불필요 |
| ai-engine 담당 | 부여 | 백엔드 인스턴스 |
| data_pipeline 담당 | 부여 | 파이프라인 인스턴스 |

권한을 부여하면 MFA · 키 회전 · 회수 같은 관리가 따라옵니다. 실제로 필요해질 때 부여하는 편이 부담이 적습니다.

---

## 5. 재배포

### 5-1. backend

jar 는 로컬에서 빌드해 서버로 올립니다. `build.gradle` 이 **JDK 17 toolchain** 을 요구하므로 `JAVA_HOME` 이 JDK 17 을 가리켜야 합니다.

```bash
cd backend
./gradlew bootJar -x test
scp build/libs/earningwhisperer-backend-0.0.1-SNAPSHOT.jar ubuntu@43.200.26.70:/tmp/backend.jar
```

JDK 가 여러 개 설치되어 있으면 빌드 전에 `JAVA_HOME` 을 지정하세요.

```bash
export JAVA_HOME=$(/usr/libexec/java_home -v 17)   # macOS
export JAVA_HOME=$(dirname $(dirname $(readlink -f $(which javac))))   # Linux (JDK 17 이 기본일 때)
```

Windows 에서는 `gradlew.bat` 를 쓰고 `JAVA_HOME` 을 환경변수로 설정하면 됩니다.

서버에서 교체합니다.

```bash
sudo systemctl stop earning-whisperer-backend
mv /tmp/backend.jar /opt/earning-whisperer/backend.jar
sudo systemctl start earning-whisperer-backend
journalctl -u earning-whisperer-backend -f
```

로그에 `Started EarningWhispererApplication` 이 찍히면 정상입니다. 20~30초 걸립니다.

### 5-2. ai-engine

```bash
cd ai-engine
rsync -az --delete \
  --exclude '.venv/' --exclude '__pycache__/' --exclude '*.pyc' \
  --exclude '.env' --exclude '.env.example' --exclude 'tests/' --exclude 'docs/' \
  --exclude '.pytest_cache/' --exclude 'data/yfinance_cache/' \
  ./ ubuntu@43.200.26.70:/opt/earning-whisperer/ai-engine/
ssh ubuntu@43.200.26.70 'sudo systemctl restart earning-whisperer-ai-engine'
```

`.env` 를 제외하는 이유는 서버 값이 `/opt/earning-whisperer/ai-engine.env` 에 따로 있고 `DATABASE_URL` · `REDIS_URL` · `QDRANT_URL` 이 서버 기준(`127.0.0.1`)으로 다르기 때문입니다.

`requirements.txt` 를 고쳤다면 의존성도 갱신합니다.

```bash
ssh ubuntu@43.200.26.70 '/opt/earning-whisperer/ai-engine/.venv/bin/pip install -r /opt/earning-whisperer/ai-engine/requirements.txt'
```

### 5-3. 환경변수

```bash
nano /opt/earning-whisperer/backend.env      # 또는 ai-engine.env
sudo systemctl restart earning-whisperer-backend
```

값은 작은따옴표로 감싸 주세요 (`KEY='value'`). DB URL 의 `&` 를 셸이 백그라운드 연산자로 해석해 값이 잘리는 일이 있었습니다.

시연에 영향이 큰 키는 다음 세 개입니다.

| 키 | 비우면 |
|---|---|
| `GEMINI_API_KEY` (ai-engine) | 팩트체크와 종합 판단이 동작하지 않습니다 |
| `FINNHUB_API_KEY` (backend) | Market 화면 시세와 주문 기준가가 전일종가에 묶입니다. 시가총액 상위 50종목 실시간 시세를 이 키로 받습니다 |
| `FMP_API_KEY` (backend) | 전일종가가 갱신되지 않아 등락률이 틀어집니다. 무료 등급이 하루 250요청이라 여러 환경에서 같은 키를 쓰지 않는 편이 좋습니다 |

---

## 6. 근거 데이터 (Qdrant)

팩트체크가 참조하는 근거 뉴스 395건이 Qdrant 컬렉션 `earningwhisperer_evidence` 에 들어 있습니다.

**서버에서 다시 적재하지 마세요.** 395건을 새로 넣으면 Gemini 임베딩을 395요청 쓰는데, 무료 등급이 하루 1,000요청(한국시간 16:00 리셋)입니다. 중간에 실패하면 그날 리허설까지 막힙니다.

스냅샷으로 옮기면 임베딩 호출이 0회입니다.

```bash
# 로컬에서 스냅샷 생성 (약 4.4MB)
curl -X POST http://localhost:6333/collections/earningwhisperer_evidence/snapshots
# 응답의 name 을 받아 내려받기
curl -O http://localhost:6333/collections/earningwhisperer_evidence/snapshots/<name>

# 서버로 올린 뒤 복원
scp <name> ubuntu@43.200.26.70:/tmp/
ssh ubuntu@43.200.26.70 "curl -X POST 'http://localhost:6333/collections/earningwhisperer_evidence/snapshots/upload?priority=snapshot' \
  -H 'Content-Type:multipart/form-data' -F 'snapshot=@/tmp/<name>'"
```

compose 의 Qdrant 태그를 **로컬과 같은 버전으로 맞춰야 합니다** (현재 `v1.19.1`). 스냅샷은 하위 버전으로 복원되지 않습니다.

컬렉션 `earningwhisperer_transcripts` 는 비어 있습니다. ai-engine 이 필요할 때 직접 만듭니다.

---

## 7. 검증

배포 후 아래 순서로 확인합니다.

**1) 서비스 기동**

```bash
curl -s localhost:8082/actuator/health     # {"status":"UP"}
curl -s localhost:8000/health              # {"status":"ok",...}
docker ps                                   # 컨테이너 4개
```

**2) 근거 적재** — 임베딩을 쓰지 않는 조회입니다.

```bash
curl 'http://localhost:8000/v1/engine/evidence/readiness?ticker=WMT&as_of=1787227200'
# → {"ticker":"WMT","document_count":393,...,"ready":true}
```

**3) 팩트체크 동작** — 문장 3개 단위 배치입니다. **2개까지는 `BUFFERING` 이고 LLM 이 돌지 않습니다.** `is_session_end=true` 로 1~2문장만 보내면 `partial_batch_discarded` 로 버려집니다.

```bash
curl -s -X POST localhost:8000/v1/engine/live-fact-check/sentence \
  -H 'Content-Type: application/json' \
  -d '{"ticker":"WMT","sentence":"<어닝콜 문장>","sentence_sequence":101,
       "sentence_timestamp":1787227287,"is_session_end":false}'
```

세 번째 호출에서 `status: COMPLETED`, `extraction_llm_used: true`, `verification_llm_used: true` 가 나오면 정상입니다. 실측 5.2초이고 백엔드 읽기 타임아웃(50초) 안입니다.

**4) 시연 전체** — 터미널에서 로그인 후 Market → WMT → Trading Room → "시연 시작". 정상 회차의 로그는 다음과 같습니다.

```
[DemoCall] 재생 시작 — ticker=WMT segments=24 interval=6000ms factCheck=true
... live-fact-check/sentence 24회 (세그먼트 1개당 1회)
[DemoCall] 재생 완료                                    (138초)
POST /v1/engine/analyze               200 OK
POST /v1/engine/earnings/intelligence 200 OK
[WebSocket] 종합 판단 fan-out — ticker=WMT direction=...
```

전체 약 2분 30초입니다. 세그먼트 간격은 `DEMO_SEGMENT_INTERVAL_MS` 로 조정할 수 있습니다.

**5) 메모리** — `free -h` 로 확인합니다. 스왑 사용량이 계속 올라가면 [8장](#8-비용과-메모리)을 참고하세요.

---

## 8. 비용과 메모리

AWS 는 서버가 존재하는 시간에 과금합니다. 그래서 당분간 개발이나 리허설을 할 때만 켜 두고 그 외에는 중지해 둡니다.

| 상태 | 과금 대상 | 월 환산 |
|---|---|---|
| 실행 중 | 컴퓨팅 + 디스크 + IP | 약 $24 |
| 중지 | 디스크 + IP | 약 $5 |
| 종료 + IP 릴리스 | 없음 | $0 |

시연이 끝나고 더 쓸 일이 없으면 인스턴스를 종료(Terminate)하고, 탄력적 IP 메뉴에서 `43.200.26.70` 을 릴리스해야 $0 이 됩니다. 탄력적 IP 는 인스턴스와 별개로 남아 계속 과금됩니다.

### 실측 메모리

전체를 올린 상태의 측정값입니다.

| 서비스 | RSS |
|---|---|
| backend (JVM) | 378MB |
| ai-engine (uvicorn) | 186MB |
| MySQL | 66MB |
| Qdrant | 27MB |
| PostgreSQL | 20MB |
| Redis | 5MB |

`free -h` 기준 1.1GB 사용 / 811MB 여유이고, 스왑은 82MB 에서 늘지 않습니다(pip 설치 때 쓴 양입니다). **t3.small 로 충분합니다.**

스왑 사용량이 계속 증가하면 인스턴스를 중지한 뒤 콘솔에서 "인스턴스 유형 변경" 으로 t3.medium(4GB)으로 올리면 됩니다. 디스크 · IP · 설정은 유지됩니다.

### 메모리 제한 설정

t3.micro(1GB) 시절에 맞춘 값들이고, t3.small 로 올린 뒤에도 그대로 두었습니다. 지금 값으로 충분히 돌아갑니다.

| 대상 | 설정 |
|---|---|
| 스왑 | `/swapfile` 2GB, fstab 등록 |
| JVM | `-Xms128m -Xmx384m -XX:MaxMetaspaceSize=128m -XX:+UseSerialGC -Xss512k` |
| MySQL | buffer pool 64M, performance_schema OFF, max_connections 30, mem_limit 300m |
| Redis | maxmemory 48mb, allkeys-lru, RDB 저장 끔, mem_limit 64m |
| PostgreSQL | shared_buffers 32M, max_connections 20, mem_limit 200m |
| Qdrant | mem_limit 384m |

ai-engine 의 `requirements.txt` 에는 torch · transformers 가 없습니다. `.env` 의 `PHASE1_PROVIDER=finbert` 는 어디서도 읽지 않는 설정이고(`core/phase1_scorer.py` 가 항상 `provider="heuristic"` 을 반환합니다), FinBERT 모델이 내려오지 않습니다.

---

## 9. 처음부터 다시 만들기

서버를 새로 만들어야 할 때의 순서입니다.

**1) 인스턴스 생성** — EC2 콘솔(서울)에서 Ubuntu 24.04, t3.small, 키페어 `ew-mac`, 스토리지 16GB gp3.

**2) 보안 그룹** — 인바운드에 22, 8082 추가.

**3) 탄력적 IP** — `43.200.26.70` 을 새 인스턴스에 연결.

**4) 기본 도구와 스왑**

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y openjdk-21-jre-headless docker.io docker-compose-v2 python3-venv python3-dev
sudo usermod -aG docker ubuntu && exit     # docker 그룹 적용을 위해 재로그인
sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
sudo mkdir -p /opt/earning-whisperer && sudo chown ubuntu:ubuntu /opt/earning-whisperer
```

**5) 파일 배치** — 로컬에서 `/opt/earning-whisperer/` 로 올립니다.

- `infra/aws/docker-compose.yml`
- `infra/aws/earning-whisperer-backend.service`, `earning-whisperer-ai-engine.service`
- `backend.jar` ([5-1](#5-1-backend))
- `backend.env` — `backend/.env.example` 기준으로 채우되 `DB_URL` 을 `jdbc:mysql://127.0.0.1:3306/earning_whisperer?...&allowPublicKeyRetrieval=true` 로 잡습니다
- compose 용 `.env` — `MYSQL_ROOT_PASSWORD`, `MYSQL_USER=user`, `MYSQL_PASSWORD`, `POSTGRES_PASSWORD`. `MYSQL_PASSWORD` 는 `backend.env` 의 `DB_PASSWORD` 와, `POSTGRES_PASSWORD` 는 `ai-engine.env` 의 `DATABASE_URL` 비밀번호와 같아야 합니다

**6) 컨테이너와 백엔드 기동**

```bash
cd /opt/earning-whisperer && docker compose up -d
sudo cp earning-whisperer-backend.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now earning-whisperer-backend
```

**7) ai-engine** — 코드는 [5-2](#5-2-ai-engine) 의 rsync 로 올립니다. `ai-engine.env` 는 로컬 `.env` 를 올린 뒤 `DATABASE_URL` · `REDIS_URL` · `QDRANT_URL` 을 `127.0.0.1` 기준으로 고치고 권한을 600 으로 둡니다.

```bash
cd /opt/earning-whisperer/ai-engine && python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
sudo cp /opt/earning-whisperer/earning-whisperer-ai-engine.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now earning-whisperer-ai-engine
```

**8) 근거 데이터 복원** — [6장](#6-근거-데이터-qdrant) 의 스냅샷 절차. 재적재는 하지 않습니다.

**9) 검증** — [7장](#7-검증).

---

## 10. 제약

운영상 알고 있어야 하는 것들입니다.

- **HTTPS 가 없습니다.** Electron 은 브라우저와 달리 mixed content 제약이 없어 `ws://` 도 동작합니다. JWT 가 평문으로 오가지만 시연과 테스트 계정 범위에서는 감수하기로 했습니다. 웹 프론트를 외부에 공개하려면 TLS 가 필요합니다([부록 B](#부록-b--보류된-웹-배포-경로)).
- **STOMP 구독에 인증이 없습니다.** `StompJwtChannelInterceptor` 가 CONNECT 만 검사하고 실패해도 연결을 허용하며, SUBSCRIBE 검사가 없어 `/topic/**` 이 사실상 공개입니다.
- **서버 STOMP heartbeat 가 꺼져 있습니다.** `enableSimpleBroker` 에 `TaskScheduler` 가 없어 죽은 커넥션 탐지가 TCP 에 맡겨져 있습니다.
- **`ddl-auto: update` 를 쓰고 있습니다.** 운영이라면 `validate` + 마이그레이션 도구가 맞지만 시연 범위에서는 유지했습니다. 엔티티를 고치면 스키마가 자동 변경됩니다.
- **`DemoReplayService` 가 기동과 함께 `mock-nvda-replay.json` 을 무한 재생합니다.** `/topic/live/demo` 로 브로드캐스트되며 구독자는 미배포 상태인 `frontend` 뿐이라 터미널 시연에는 영향이 없습니다. 현재 시연 경로(`DemoEarningsCallService`)와는 별개입니다.
- **data_pipeline 은 이 서버에 올리지 않습니다.** 별도 인스턴스로 분리하는 방향으로 정해졌습니다 ([11장](#11-data_pipeline-배포-계획)). 현재 시연은 과거 콜 재생이라 STT 가 필요하지 않습니다.
- **Gemini 임베딩 무료 등급은 하루 1,000요청이고 한국시간 16:00 에 리셋됩니다.** 근거 적재가 이 한도를 쓰기 때문에 서버에서 재적재하지 않고 스냅샷으로 옮기는 것을 정책으로 두었습니다 ([6장](#6-근거-데이터-qdrant)).
- **팩트체크 지연 여유가 크지 않습니다.** 세그먼트 간격 6초, 팩트체크 1배치 실측 5.2초입니다. `[DemoCall] 팩트체크 큐 적체` 경고가 보이면 카드가 스크립트보다 뒤처지고 있다는 뜻입니다.

---

## 11. data_pipeline 배포 계획

아직 배포하지 않았습니다. 방향만 정해져 있고 사양은 측정 후 확정합니다 (#116).

### 구조

**DB 와 인스턴스를 모두 분리합니다.**

```
[인스턴스 1] ew-backend (t3.small)          [인스턴스 2] 미생성
  backend (systemd)                           data_pipeline (scheduler + STT 워커)
  ai-engine (systemd)                          MySQL (파이프라인 전용)
  MySQL · Redis · PostgreSQL · Qdrant
        ▲
        └──── POST /api/v1/internal/transcript-segment ────┘
```

각 인스턴스가 자기 MySQL 컨테이너를 갖고 `127.0.0.1` 바인딩을 유지합니다. 그래서 **DB 포트를 외부에 열지 않습니다.** 두 인스턴스 사이의 통신은 HTTP 하나뿐입니다.

### 왜 분리하나

**테이블이 이미 거의 완전히 분리되어 있습니다.**

| | 테이블 |
|---|---|
| 백엔드 전용 | `users`, `trades`, `positions`, `broker_accounts`, `portfolio_settings`, `watchlist_items`, `signal_history`, `earnings_calendar`, `earnings_result`, `daily_bar`, `stock_meta` |
| data_pipeline 전용 | `calls`, `prices`, `financial_statement_items`, `transcript_segments`, `webcast_recipes`, `webcast_replay_targets`, `webcast_learning_targets`, `webcast_replay_discovery` |
| 공유 | `stocks` |

data_pipeline 코드에서 백엔드 테이블 11개를 찾으면 참조가 0건이고, 백엔드 Java 에서 data_pipeline 테이블 8개도 0건입니다. DB 를 한 대로 유지하면 오히려 MySQL 을 VPC 사설 IP 로 열고 보안 그룹에 3306 규칙을 추가해야 합니다.

**비용도 분리가 낮습니다.** t3 는 유형이 한 단계 오를 때마다 시간당 단가가 2배라서, 작은 인스턴스 두 대가 큰 것 한 대보다 쌉니다.

| 방안 | 구성 | 월 비용 (근사) |
|---|---|---|
| 통합 | t3.large 8GB 1대 | 약 $83 |
| **분리 (상시)** | t3.small + t3.medium | **약 $69** |
| 분리 + 어닝콜 시간만 기동 | t3.small 상시 + t3.medium 온디맨드 | 약 $29 |

*ap-northeast-2 온디맨드 Linux 기준입니다. t3.small $0.026/h, t3.medium $0.052/h, t3.large $0.104/h. 실제 청구는 AWS 계산기로 확인하는 편이 정확합니다.*

**격리**도 얻습니다. STT 는 처리 중 CPU 와 메모리를 크게 쓰는 작업이라, 같은 인스턴스에 두면 OOM 이 났을 때 커널이 가장 큰 프로세스(JVM 378MB)를 종료할 수 있습니다. 분리하면 STT 실패가 백엔드로 번지지 않습니다.

### `stocks` 중복

DB 가 나뉘면 각자 자기 `stocks` 를 갖게 되어 쓰기 충돌은 사라집니다. 다만 **같은 S&P 500 목록을 서로 다른 출처에서 각자 긁는 중복**은 남습니다.

| | 출처 | 채우는 컬럼 |
|---|---|---|
| 백엔드 `Sp500SyncScheduler` | `raw.githubusercontent.com/datasets/s-and-p-500-companies` CSV | ticker, company_name, sector, active |
| data_pipeline `sync_stock_master` | 위키백과 `List_of_S&P_500_companies` | ticker, company_name, sector, **ir_url**, active |

`ir_url` 은 data_pipeline 만 쓰는 컬럼이고 웹캐스트 수집의 출발점입니다. 백엔드 `Stock` 엔티티에는 이 필드가 없어서, **같은 DB 를 쓰는 현재 상태에서는 백엔드의 `save()` 가 이 값에 영향을 주는지 확인이 필요합니다.** DB 를 분리하면 이 위험은 사라집니다.

### 확정 전에 필요한 것

인스턴스 유형은 **#116 측정 결과로 결정합니다.** 측정 없이 정하면 두 가지를 놓칩니다.

- **실시간 처리 가능 여부** — RTF(처리시간 ÷ 오디오 길이)가 1.0 미만이어야 합니다. 넘으면 인스턴스 크기 문제가 아니라 외부 STT API 로 갈지 결정해야 합니다
- **t3 버스트 크레딧** — t3 는 크레딧이 소진되면 기준 성능(t3.medium 은 2 vCPU 의 40% 수준)으로 제한됩니다. STT 처럼 CPU 를 계속 쓰는 작업에는 불리해서, 소진 이후에도 RTF 가 유지되는지 확인해야 합니다. 안 되면 t3 unlimited 모드나 비버스트 계열(c6i · c6g)로 가야 합니다

### 어닝콜 시간에만 기동하는 구조

비용이 가장 낮은 방안이지만 **별개 사안으로 추후 결정합니다.** 인스턴스가 분리되어 있으면 나중에 전환하기 쉽습니다.

전환한다면 **백엔드가 깨우는 구조**가 되어야 합니다. 현재 일정을 감시하는 주체는 data_pipeline 의 `monitor_and_trigger_stt`(1분 주기, `ENABLE_STT_MONITOR=true` 일 때만 활성)인데, 그 코드가 꺼진 인스턴스 안에 있어서 자기를 깨울 수 없습니다.

그 변경에는 부수 효과가 하나 있습니다 — 어닝콜 일정의 소유자가 정해집니다. 지금은 백엔드 `earnings_calendar`(FMP)와 data_pipeline `calls`(자체 수집)에 일정이 이중으로 있습니다.

---

## 부록 A · 로컬 개발 환경

`infra/docker-compose.yml` 이 로컬 개발용 컨테이너를 정의합니다.

```bash
docker compose -f infra/docker-compose.yml up -d
```

| 컨테이너 | 용도 |
|---|---|
| `ew-mysql` | 백엔드 DB. `infra/mysql-init/` 의 스키마가 초기 실행됩니다 |
| `ew-redis` | 세션 · 캐시 |
| `ew-postgres` | ai-engine 이벤트 스토어 |
| `ew-qdrant` | ai-engine 근거 벡터 저장소 |
| `ew-browser-webcast` | data_pipeline 웹캐스트 수집 |
| `ew-pipeline-scheduler` | data_pipeline 스케줄러 |

서버와 달리 포트가 전체 개방되어 있고 메모리 제한이 없습니다. 백엔드 · ai-engine · 터미널은 각자 로컬에서 직접 실행합니다.

로컬 백엔드로 터미널을 붙일 때는 `trading-terminal/.env.local` 을 바꿉니다.

```
BACKEND_URL=http://localhost:8082
```

**로컬 백엔드와 서버 백엔드를 동시에 띄우지 마세요.** 같은 `FINNHUB_API_KEY` 로 두 웹소켓이 붙으면 무료 등급에서 서로 연결이 끊깁니다.

---

## 부록 B · 보류된 웹 배포 경로

웹 프론트(랜딩 + `/demo`) 공개 배포는 **보류 상태**입니다. 랜딩 페이지를 개편할 계획이 있어 현재 우선순위가 아닙니다.

관련 파일은 지우지 않고 남겨 두었습니다.

| 파일 | 용도 |
|---|---|
| `infra/docker-compose.prod.yml` | MySQL · Redis · cloudflared 구성 |
| `infra/demo-up.sh` · `demo-down.sh` | 로컬 백엔드 + Cloudflare quick tunnel 기동 · 종료 |

`demo-up.sh` 는 개발 PC 의 백엔드를 quick tunnel 로 공개하고 임시 URL 을 출력합니다. 계정이 필요하지 않지만 **URL 이 매 실행마다 바뀌고 일회용입니다.**

웹으로 공개하려면 TLS 가 필요합니다. 브라우저의 mixed content 정책 때문에 HTTPS 페이지에서 `ws://` 를 쓸 수 없습니다. 재개할 때는 Cloudflare Tunnel 구성을 출발점으로 삼으면 됩니다.
