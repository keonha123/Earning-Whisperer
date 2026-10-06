# 문서 안내

EarningWhisperer 저장소의 문서가 어디에 있고 어떤 규칙으로 관리하는지 정리한 문서입니다.
앱 사용자, 기여자, 설계를 보려는 사람 모두가 여기서 필요한 문서를 찾을 수 있도록 둡니다.

## 독자별 진입점

| 독자 | 먼저 읽을 문서 | 이어서 읽을 문서 |
|---|---|---|
| 앱 사용자 | [빠른 시작](overview/quick-start.md) | [요구사항](install/requirements.md), [데스크톱 앱 설치](install/desktop-app.md), [기능](features/), [FAQ](overview/faq.md) |
| 기여자 | [기여 안내](../CONTRIBUTING.md) | [로컬 실행](developer/setup.md), [폴더 구성](developer/directories.md), [테스트](developer/testing.md) |
| 설계를 보려는 사람 | [제품 정의](product.md) | [아키텍처](developer/architecture.md), [설계 결정 기록(ADR)](adr/), [모듈 간 계약](api-spec.md) |

## 문서 목록

### 사용자 문서

| 경로 | 내용 |
|---|---|
| [`overview/quick-start.md`](overview/quick-start.md) | 설치부터 로그인, 첫 어닝콜 재생까지 |
| [`overview/faq.md`](overview/faq.md) | 자주 묻는 질문 |
| [`install/requirements.md`](install/requirements.md) | OS·네트워크·계정 요구사항 |
| [`install/desktop-app.md`](install/desktop-app.md) | 데스크톱 앱 설치 |
| [`features/live-transcript.md`](features/live-transcript.md) | 어닝콜 자막 |
| [`features/fact-check.md`](features/fact-check.md) | 실시간 팩트체크 |
| [`features/earnings-summary.md`](features/earnings-summary.md) | 종합 판단(회피 탐지, 관련 종목 영향, 손절·익절 계획) |
| [`features/trading.md`](features/trading.md) | 사용자가 직접 내는 KIS 주문(모의·실전) |
| [`features/market.md`](features/market.md) | 대시보드와 마켓 |

### 제품·디자인 문서

| 경로 | 내용 |
|---|---|
| [`product.md`](product.md) | 제품 정의. 목표, 대상 사용자, 해결하려는 일, 기능 범위와 제외 범위 |

디자인 문서는 `design/` 에 둡니다. 정해 둔 이름은 아래와 같고, 파일이 생기면 이 표에 추가합니다.

| 경로 | 내용 |
|---|---|
| [`design/ux.md`](design/ux.md) | 설계 원칙, 정보 구조, 핵심 유저플로우, 인터랙션 규칙 |
| `design/design-system.md` | 토큰 체계, 의미 색, 컴포넌트 사용 규칙, 상태 패턴, 문구 규칙 |
| `design/brand.md` | 로고, 앱 아이콘, 이름 표기, 톤 |
| `design/screens/<화면>.md` | 화면마다 하나. 역할, 영역 구성, 표시 데이터, 상태, 동작. 픽셀 수치는 쓰지 않습니다 |

### 개발자 문서

| 경로 | 내용 |
|---|---|
| [`developer/architecture.md`](developer/architecture.md) | 시스템 구성, 모듈별 역할, 주요 흐름, 불변식 |
| [`developer/setup.md`](developer/setup.md) | 모듈별 로컬 실행 |
| [`developer/directories.md`](developer/directories.md) | 최상위·모듈 폴더 설명 |
| [`developer/testing.md`](developer/testing.md) | 모듈별 테스트 실행 |
| [`api-spec.md`](api-spec.md) | 모듈 사이의 REST·STOMP 계약 |
| [`adr/`](adr/) | 설계 결정 기록. 새로 쓸 때는 [`adr/0000-template.md`](adr/0000-template.md) 를 복사합니다 |
| [`adr/0001`](adr/0001-use-stomp-for-realtime-delivery.md) | 실시간 전달에 STOMP over WebSocket 사용 |
| [`adr/0002`](adr/0002-execute-kis-orders-in-desktop-terminal.md) | KIS 주문을 데스크톱 터미널에서 실행 |
| [`adr/0003`](adr/0003-fact-check-with-evidence-retrieval-and-llm.md) | 근거 검색과 LLM 판정으로 팩트체크 |
| [`adr/0004`](adr/0004-replay-past-earnings-call-for-demo.md) | 시연에 과거 어닝콜 재생 |
| [`adr/0005`](adr/0005-support-only-user-placed-orders.md) | 매매는 사용자 직접 주문만 지원 |
| [`demo/README.md`](demo/README.md) | 시연 데이터와 팩트체크 정확도 실측 기록 |
| [`../infra/DEPLOY.md`](../infra/DEPLOY.md) | 시연 서버 배포와 운영 |

### 저장소 루트와 모듈

| 경로 | 내용 |
|---|---|
| [`../README.md`](../README.md) | 프로젝트 소개 |
| [`../CONTRIBUTING.md`](../CONTRIBUTING.md) | 이슈·브랜치·커밋·PR 규칙 |
| [`../.github/CODEOWNERS`](../.github/CODEOWNERS) | 모듈별 리뷰 담당자 |
| [`../.github/pull_request_template.md`](../.github/pull_request_template.md) | PR 본문 양식 |
| [`../backend/`](../backend/), [`../trading-terminal/`](../trading-terminal/), [`../ai-engine/`](../ai-engine/), [`../data_pipeline/`](../data_pipeline/) | 각 모듈의 README |

날짜를 붙인 계획·작업 문서는 저장소에 넣지 않습니다. 설계 문서는 날짜 없이 주제 이름으로 두고 내용을 갱신해
관리합니다.

## 운영 규칙

### 코드와 함께 고칩니다

- 코드를 바꾸는 PR 에서 그 코드를 설명하는 문서도 함께 고칩니다. PR 템플릿의 "문서 갱신 여부" 항목에
  바꾼 문서를 적습니다.
- 이 규칙의 예외가 두 가지 있습니다. 디자인 문서(`design/`)는 코드 PR 마다 고치지 않고 디자인 작업 단위가
  끝날 때 몰아서 갱신합니다. 화면 재설계로 바뀌는 사용자 문서(`features/` 등)의 화면 설명은 릴리스 전까지
  맞춥니다.
- `api-spec.md` 의 각 절은 해당 계약을 바꾸는 사람이 같은 PR 에서 고칩니다.
- 새 문서는 필요가 생겼을 때만 만듭니다.
- 현행과 맞지 않는 문서는 고치거나 지웁니다. 보관용 `archive/` 폴더는 두지 않으며 지운 문서는 git 이력으로
  되살릴 수 있습니다.

### 쓰는 방식

- 문서 하나에 주제 하나를 다룹니다. 제목이 H4 까지 내려가면 문서를 나눕니다. 기존 `api-spec.md` 는 계약 단위로
  나누기 전까지 예외로 둡니다.
- 습니다체로 씁니다. 명령조는 쓰지 않습니다.
- 문서 사이 링크는 상대 경로로 겁니다. 코드 위치는 링크 대신 클래스·파일 이름을 백틱으로 적어 경로가
  바뀌어도 검색으로 찾을 수 있게 합니다.
- 문서 첫머리에 이 문서가 무엇을 다루고 누구를 위한 것인지 한두 문장으로 적습니다.

### 이미지

- 스크린샷은 PNG 로 `docs/assets/screenshots/` 에 두고 상대 경로로 참조합니다.
- 화면이 있는 trading-terminal 만 찍습니다. 시연용 월마트(WMT) 어닝콜을 재생한 상태에서 찍어, 다시 찍어도
  같은 화면이 나오게 합니다.
- 영상은 저장소에 넣지 않고 GitHub 첨부로 올립니다.

### 다이어그램

- Mermaid 로 그립니다. GitHub 가 별도 빌드 없이 렌더링하고 텍스트라서 변경 내역이 diff 로 남습니다.
- `flowchart` 와 `sequenceDiagram` 만 씁니다. `C4Context` 같은 C4 문법은 Mermaid 에서 실험 기능이고
  `architecture-beta` 같은 베타 문법은 GitHub 렌더러 버전에 따라 깨질 수 있어 쓰지 않습니다.
- 한글 라벨은 따옴표로 감쌉니다(`A["트레이딩 터미널"]`). 줄바꿈은 `<br/>` 로 넣습니다.

### ADR

- 되돌리기 어렵거나 여러 모듈에 걸친 설계 결정을 `adr/NNNN-<decision-in-english>.md` 로 기록합니다. 번호는 네 자리이며
  이전 ADR 다음 번호를 씁니다.
- 상태는 `채택`, `대체됨`, `폐기` 중 하나입니다.
- 채택한 ADR 은 결정 내용을 고치지 않습니다. 결과 절의 후속 조치만 덧붙일 수 있습니다. 결정이 바뀌면 새 ADR 을 쓰고 기존 ADR 은 상태를 `대체됨` 으로 바꾸고
  "대체된 ADR" 칸에 새 ADR 번호만 적습니다.
- ADR 은 지우지 않습니다. 더 이상 유효하지 않은 결정도 상태로 구분해 남겨 둡니다.
