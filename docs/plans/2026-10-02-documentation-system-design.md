# 문서 체계 설계

- 작성일: 2026-10-02
- 상태: 검토 중
- 범위: 저장소 전체 문서(README, `docs/`, 모듈 README, `.github` 기여 문서)

## 1. 배경

현재 문서는 대부분 비어 있거나 실제 코드와 맞지 않습니다.

- 루트 `README.md` 는 21줄이고 "시작하기" 절이 비어 있습니다. `./data-pipeline/README.md` 링크는
  실제 폴더명(`data_pipeline`)과 달라 깨져 있습니다.
- `docs/architecture.md` 는 빈 파일입니다. `project-proposal.md`, `testing-guidelines.md`, `db-schema.md`
  는 2026년 3~4월 이후 갱신되지 않았습니다.
- `docs/api-spec.md`(745줄)에는 Redis Pub/Sub 신호, 매매 신호로 내리던 주문 명령처럼 현재 제거 중이거나 바뀐 흐름이
  남아 있습니다.
- 모듈 README(backend, trading-terminal, frontend)는 2026-04-06 이후 갱신되지 않았습니다.
  `data_pipeline/README.md` 는 운영 메모와 초기 요구사항 정의서가 한 파일에 섞여 있습니다.
- 모듈별 `docs/` 아래의 요구사항 정의서, PRD, UI/UX 스펙은 초기 기획 단계 문서로, 현재 화면·구조와 다릅니다.
- 아키텍처 그림, 설치 안내, 기여 가이드가 없습니다.

## 2. 목표와 독자

목표는 문서화가 잘 된 오픈소스 수준의 문서 체계를 갖추는 것입니다. 독자는 세 부류이며 비중을 같게 둡니다.

| 독자 | 필요한 것 | 진입점 |
|---|---|---|
| 외부 평가자·방문자 | 무엇을 만들었고 어떻게 설계했는지 10분 안에 파악 | 루트 README → `docs/developer/architecture.md` → `docs/adr/` |
| 팀원·신규 기여자 | 로컬 실행, 구조 이해, 기여 규칙 | `CONTRIBUTING.md` → `docs/developer/` |
| 앱 사용자 | 데스크톱 앱 설치와 사용법 | 루트 README → `docs/overview/quick-start.md` → `docs/install/` |

공개 형태는 GitHub 마크다운 렌더링입니다. 문서 사이트는 이번 범위에 넣지 않지만 나중에 Docusaurus 로
옮길 수 있도록 폴더 구조와 상대 링크를 맞춰 둡니다.

## 3. 참고한 사례

2026-10-02 에 아래 레포와 자료의 원문을 직접 확인했습니다.

- 기준 모델
  - **immich-app/immich**: server·web·mobile·ML 로 구성된 다중 스택 모노레포라 이 저장소와 구조가 가장 비슷합니다.
    `docs/docs/` 를 독자 여정 순서(overview → install → features → administration → developer → guides)로
    나눕니다. 루트 README 는 125줄이고 설치 절차 없이 링크 허브 역할만 합니다. 개발자 문서는 15~230줄의
    짧은 how-to 여러 개로 되어 있습니다.
  - **PostHog/posthog**: `docs/README.md` 에 문서 운영 규칙을 명문화했습니다("코드를 바꾸는 PR 에서 문서도
    갱신한다", "새 문서는 요청이 있을 때만 추가한다"). 팀 전용 문서는 `docs/internal/`, 설계 계획은
    `docs/plans/YYYY-MM-DD-*.md` 에 둡니다.
- 보조 사례: supabase, langfuse, backstage, cal.com, n8n, grafana, kubernetes(KEP), rust-lang(RFC), python(PEP)
- 원칙 문서: Diátaxis, matklad "ARCHITECTURE.md", Google `docguide/best_practices.md`, Write the Docs
  principles, 토스 technical-writing
- 국내 팀 프로젝트: 부스트캠프(OctoDocs, Denamu, GitChallenge), 우아한테크코스(hang-log, dallog)

조사에서 확인한 공통 패턴입니다.

1. README 는 짧은 쇼케이스이고 상세 내용은 `docs/` 로 넘깁니다. 확인한 8개 레포 중 5개가 50~130줄입니다.
2. 문서는 코드와 같은 레포에 둡니다(8개 중 6개). 국내 팀 프로젝트는 상세 문서를 GitHub 위키에 두는 경우가
   많은데, 위키는 PR 리뷰를 거치지 않아 코드와 어긋나기 쉬우므로 따르지 않습니다.
3. 사용자 문서와 개발자 문서를 폴더로 나눕니다(immich `developer/`, PostHog `internal/`).
4. 결정 기록은 지우지 않고 상태 필드로 관리합니다(KEP, BEP, RFC, PEP). 현행 가이드가 틀렸으면 고치거나
   지웁니다(Google docguide: "Default to delete … Stragglers can always be recovered").
5. 8개 레포 모두 CODEOWNERS 를 둡니다. immich·grafana 는 PR 템플릿에 문서 갱신 항목을 둡니다.

## 4. 문서 구조

```
README.md                    쇼케이스
CONTRIBUTING.md              기여 원칙(50줄 내외)
.github/
  CODEOWNERS                 모듈별 담당자
  pull_request_template.md   기존 템플릿에 문서 갱신 항목 추가
docs/
  README.md                  문서 지도와 운영 규칙
  api-spec.md                모듈 간 계약 (현 위치 유지)
  demo/                      시연 자료와 fixtures (현 위치 유지)
  overview/
    quick-start.md           설치 → 로그인 → 첫 어닝콜 재생
    faq.md
  install/
    requirements.md          OS·하드웨어·네트워크·계정(KIS 등) 요구사항
    desktop-app.md           Windows / macOS 설치
  features/                  기능마다 한 파일 (실시간 트랜스크립트, 팩트체크, 종합 판단, 주문 등)
  developer/
    architecture.md          시스템 구성도, 모듈별 역할, 주요 흐름 시퀀스, 불변식
    setup.md                 모듈별 로컬 실행
    directories.md           최상위·모듈 폴더 설명 표
    testing.md               모듈별 테스트 실행
  internal/                  팀 전용: 시연 준비 절차, 런북, 이미 시도한 것
  adr/
    0000-template.md
    NNNN-<제목>.md
  plans/                     날짜를 붙인 설계 문서 (이 문서 포함)
  assets/
    screenshots/
backend/README.md            스택, 실행 1~2줄, 내부 구조, docs/developer 링크
trading-terminal/README.md   〃
ai-engine/README.md          팀원 확인 후 정리 (6절)
data_pipeline/README.md      팀원 확인 후 정리 (6절)
```

항목별 근거입니다.

| 항목 | 근거 |
|---|---|
| `overview/`, `install/`, `features/`, `developer/` 분류 | immich `docs/docs/` |
| `developer/` 아래 setup·directories·testing 분리 | immich developer/ (setup 232줄, directories 22줄, testing 36줄) |
| `architecture.md` 구성 | immich architecture.mdx(상위 그림 → 구성요소별 절), matklad(조감도, 코드맵, 불변식, 코드 위치는 링크 대신 이름) |
| `docs/README.md` 운영 규칙 | PostHog docs/README.md |
| `internal/`, `plans/` | PostHog docs/internal, docs/plans |
| `api-spec.md` 를 `docs/` 최상위에 유지 | immich `docs/docs/api.md` 위치. 코드 주석·PR 템플릿·팀원 문서가 이 경로를 참조하고 있어 옮기면 참조가 깨집니다 |
| `demo/` 위치 유지 | terminal 타입 파일과 backend 시연 데이터 주석이 `docs/demo/fixtures` 경로를 참조합니다 |
| `adr/` | backstage `docs/architecture-decisions/`, n8n `docs/ADR_TEMPLATE.md`, 우아한형제들 기술블로그 사례 |
| 모듈 README 축약 | immich web(5줄)·mobile(76줄)·machine-learning(42줄) README |
| CONTRIBUTING 분량 | immich(55줄), PostHog(53줄) |

### 4.1 루트 README 구성

루트 README 는 세 독자가 모두 처음 여는 문서이므로 1단계에서 가장 먼저 작성합니다(8절).
분량은 참고 레포 대부분과 같은 100~150줄을 목표로 합니다(immich 125줄, PostHog 122줄, backstage 82줄).
절 순서는 immich·PostHog README 를 따르고, 시작하기 절은 PostHog·n8n·backstage 처럼 짧게 둡니다.

| 순서 | 절 | 내용 | 근거 |
|---|---|---|---|
| 1 | 머리 | 프로젝트 이름, 한 줄 소개, 배지(CI `test` 워크플로 상태, 최신 릴리스) | immich·backstage 배지 |
| 2 | 메인 스크린샷 | 어닝콜 재생 중 트랜스크립트와 팩트체크 판정이 함께 보이는 터미널 화면 1장 | immich·insomnia·bruno |
| 3 | 소개 | 어떤 문제를 푸는지 3~5문장. 기존 `project-proposal.md` 의 배경 중 현재 기능과 맞는 부분만 씁니다 | supabase·PostHog 소개 문단 |
| 4 | 데모 | 핵심 흐름(세그먼트 도착 → 주장 추출 → 판정 표시) mp4 1개, 10MB 이하 | d2 README, PostHog 데모 링크 |
| 5 | 주요 기능 | 기능별 한 줄 설명 표. 기능 문서가 생기면 각 행에서 링크 | immich Features 표 |
| 6 | 시스템 구성 | Mermaid `flowchart` 1장(terminal, backend, ai-engine, data_pipeline, MySQL, Redis, KIS, LLM)과 모듈별 한 줄 역할, `architecture.md` 링크 | supabase README 의 아키텍처 그림 |
| 7 | 시작하기 | 앱 사용자: 릴리스 페이지에서 설치 파일 받기. 개발자: `docs/developer/setup.md` 링크. 명령어는 최소로만 둡니다 | PostHog Getting started, n8n Quick Start |
| 8 | 문서 | 독자별 진입점 표(사용자 / 기여자 / 설계를 보려는 사람) | immich Links, backstage Documentation |
| 9 | 기여 | `CONTRIBUTING.md` 링크와 한 줄 안내 | PostHog·n8n Contributing |
| 10 | 팀 | 팀원과 담당 모듈 | 국내 팀 프로젝트(hang-log, Denamu) |

README 작성 원칙입니다.

- 아직 없는 문서로는 링크하지 않습니다. 이후 PR 에서 문서가 생길 때마다 README 의 해당 행에 링크를 추가합니다.
- 스크린샷은 현재 화면으로 먼저 찍고 화면 재디자인(`uiux` 세션)이 끝나면 같은 파일 경로에 덮어씁니다.
  README 본문은 바꾸지 않아도 됩니다.
- 이모지 머리표는 쓰지 않습니다. 현재 README 의 이모지 목록은 조사한 레포 어디에도 없는 형식입니다.
- 저장소에 LICENSE 파일이 없어 라이선스 절은 두지 않습니다. 라이선스를 정할지는 별도로 결정합니다.

### 4.2 ADR 형식

n8n `ADR_TEMPLATE.md` 를 바탕으로 합니다.

- 메타데이터: 날짜, 상태(`채택` / `대체됨` / `폐기`), 결정한 사람, 대체한 ADR / 대체된 ADR
- 본문: 배경(150단어 이내), 결정, 검토한 대안, 결과
- 파일명은 `NNNN-<결정 내용>.md` 이고, 한번 채택한 ADR 은 내용을 고치지 않습니다. 결정이 바뀌면 새 ADR 을
  쓰고 기존 ADR 의 상태만 `대체됨` 으로 바꿉니다.

아래는 소급 작성 후보입니다. 작성할 때 코드와 커밋 이력으로 사실을 확인하고 확인되지 않는 후보는 뺍니다.

- 실시간 전달에 STOMP over WebSocket 을 사용함
- KIS 주문을 서버가 아니라 데스크톱 터미널에서 실행하고 자격증명은 OS 키체인에 보관함
- 어닝콜 팩트체크를 ai-engine 의 근거 검색 + LLM 판정으로 처리함
- 시연에서 과거 어닝콜을 재생하는 방식을 채택함
- 매매 신호 경로 처리(#127): 이슈에서 결정이 난 뒤에만 작성합니다. 2026-10-05 PR #142 로 경로를 제거해
  [0005](../adr/0005-support-only-user-placed-orders.md)로 작성했습니다

## 5. 운영 규칙

`docs/README.md` 에 아래 규칙을 적고 PR 템플릿과 CONTRIBUTING 에서 이 문서를 가리킵니다.

| 규칙 | 근거 |
|---|---|
| 코드를 바꾸는 PR 에서 해당 문서도 함께 고칩니다. 새 문서는 필요가 생겼을 때만 만듭니다 | PostHog docs/README, Google docguide "Update Docs with Code" |
| 틀린 현행 문서는 고치거나 지웁니다. 보관용 `archive/` 폴더는 두지 않습니다 | Google docguide "Delete Dead Documentation" |
| ADR 은 지우지 않고 상태로 관리합니다 | KEP, BEP, RFC, PEP |
| 문서 하나에 주제 하나를 다룹니다. 제목이 H4 까지 내려가면 문서를 나눕니다 | 토스 technical-writing |
| 습니다체로 씁니다. 명령조는 쓰지 않습니다 | 저장소 공개 문서 규칙 |
| 문서 사이 링크는 상대 경로로 겁니다. 코드 위치는 링크 대신 클래스·파일 이름으로 적습니다 | PostHog 지침, matklad |
| PR 템플릿에 "문서 갱신 필요 / 불필요" 항목을 둡니다 | immich, grafana PR 템플릿 |
| CODEOWNERS: backend·trading-terminal 은 keonha123, ai-engine 은 james10419·yytss3, data_pipeline 은 dheorb | immich CODEOWNERS(최상위 폴더 단위) |

`docs/api-spec.md` 의 각 절은 해당 코드를 바꾸는 사람이 같은 PR 에서 고칩니다.
`infra/DEPLOY.md` 는 배포 스크립트와 함께 관리되므로 위치를 옮기지 않고 `docs/README.md` 에서 링크합니다.

## 6. 기존 문서 처리

| 문서 | 처리 | 시점 |
|---|---|---|
| `docs/architecture.md` (빈 파일) | 삭제, `docs/developer/architecture.md` 로 새로 작성 | 1단계 PR 2 |
| `docs/project-proposal.md` | 삭제. 배경 설명 중 현재도 맞는 부분은 README 소개에 반영 | PR 1 (README) |
| `docs/testing-guidelines.md` | 삭제, `docs/developer/testing.md` 로 새로 작성 | PR 3 |
| `docs/api-spec.md` | 위치 유지. 이미 제거된 흐름이 확실한 절에만 "현행과 다름" 표시 | PR 3 |
| `docs/db-schema.md` | 2단계에서 tbls 생성 문서로 대체할 때 삭제 | 2단계 |
| `docs/demo/README.md`, `docs/demo/fixtures/` | 위치 유지, `docs/README.md` 에서 링크 | - |
| `backend/docs/requirements.md` | 삭제 | PR 2 |
| 모듈 README 안의 `testing-guidelines.md`·`project-proposal.md` 링크 | 삭제와 같은 PR 에서 새 문서로 고침 | PR 1·3 |
| `trading-terminal/docs/` (requirements, prd, architecture, ui-spec, ux-spec) | 삭제. 현재도 맞는 구조 설명은 `architecture.md` 작성 때 참고 | PR 3 (architecture 작성과 함께) |
| `frontend/` 문서 | 모듈 존속 여부가 정해질 때까지 그대로 둡니다 | 보류 |
| `ai-engine/` 안의 문서(README, docs/ 27개, CHANGELOG 등), `data_pipeline/README.md` | 직접 고치지 않습니다. 삭제 후보 목록과 README 축약안을 담당 팀원에게 전달하고 확인을 받은 뒤 반영합니다 | 별도 |

삭제한 문서는 git 이력으로 되살릴 수 있습니다.

## 7. 시각 요소

### 7.1 다이어그램

Mermaid 로 통일합니다. GitHub 가 별도 빌드 없이 렌더링하고(2026-10-02 기준 Mermaid 11.17.2) 다크 모드에
자동으로 맞춰지며 텍스트라서 diff 가 남습니다. supabase/realtime, n8n, PostHog 의 ARCHITECTURE 문서가 같은
방식을 씁니다.

| 그림 | 문법 | 위치 |
|---|---|---|
| 시스템 구성(C4 Container 수준) | `flowchart` + `subgraph` | README, architecture.md |
| 어닝콜 세그먼트 → 팩트체크 → 화면 표시 흐름 | `sequenceDiagram` | architecture.md |
| 주문 실행 흐름(터미널 → KIS → backend 보고) | `sequenceDiagram` | architecture.md |
| 배포 구성(EC2, docker compose) | `flowchart` | architecture.md (상세는 `infra/DEPLOY.md`) |
| ERD | tbls 자동 생성 | 2단계 |

다이어그램 작성 규칙입니다.

- Mermaid 의 `C4Context` 등 C4 문법은 공식 문서에 실험 기능으로 표시되어 있으므로 쓰지 않습니다.
- 베타 문법(`architecture-beta` 등)은 GitHub 렌더러 버전에 따라 깨질 수 있으므로 쓰지 않습니다.
- 한글 라벨은 따옴표로 감쌉니다(`A["트레이딩 터미널"]`).

### 7.2 스크린샷

- 화면이 있는 trading-terminal 만 찍습니다. 데스크톱 앱 레포(insomnia, bruno, RedisInsight)도 README 에서 앱
  화면만 보여줍니다.
- README 에는 메인 화면 1장과 핵심 흐름 mp4 1개(10MB 이하)를 넣고 기능 문서마다 해당 화면을 1~2장 넣습니다.
- `docs/demo/fixtures`·backend 시연 데이터의 월마트 어닝콜을 재생한 상태에서 찍어, 다시 찍어도 같은 화면이 나오게 합니다.
- PNG 로 `docs/assets/screenshots/` 에 두고 상대 경로로 참조합니다. 영상만 GitHub 첨부(user-attachments)를 씁니다.
- 1단계에서는 직접 캡처합니다. 자동 캡처는 2단계에서 다룹니다.

## 8. 진행 단계

### 1단계: 문서 작성 (`docs` 세션)

PR 하나에 한 묶음씩 진행합니다.

1. **루트 README**: 4.1절 구성, 메인 스크린샷, 시스템 구성 Mermaid. 깨진 링크와 `project-proposal.md` 를 정리합니다.
2. **골격과 규칙**: 폴더 구조, `docs/README.md`, `CONTRIBUTING.md`, `CODEOWNERS`, PR 템플릿 항목, ADR 템플릿,
   6절의 PR 2 대상 삭제
3. **개발자 문서**: `architecture.md`, `setup.md`, `directories.md`, `testing.md`.
   `api-spec.md` 는 이미 제거된 흐름이 확실한 절에 "현행과 다름" 표시만 답니다.
   내용 현행화는 해당 코드를 바꾸는 세션이 맡습니다.
4. **ADR 소급 작성**: 4.2절 후보
5. **사용자 문서**: `overview/`, `install/`, `features/`, 기능 스크린샷, backend·trading-terminal README 축약.
   화면 재디자인(`uiux` 세션)과 겹치므로 마지막에 둡니다.

각 PR 이 머지될 때마다 루트 README 의 문서 표에 새 문서 링크를 추가합니다.

팀원 모듈(ai-engine, data_pipeline) 문서 정리 제안은 1단계와 별도로 전달합니다.

### 2단계: 문서 자동화

- 문서 CI: markdownlint-cli2(바뀐 파일만, MD013 끔), lychee `--offline`(내부 링크) PR 검사. 외부 링크는 월 1회.
  Vale·스펠체크는 한국어 지원이 약해 도입하지 않습니다.
- tbls 로 MySQL ERD 를 생성하고 `docs/db-schema.md` 를 대체합니다.
- Playwright `_electron` 으로 스크린샷을 캡처하는 스크립트를 둡니다.

### 3단계: API 레퍼런스 자동화

backend(Springdoc)와 ai-engine(FastAPI)의 OpenAPI 스펙을 생성해 커밋하고 CI 에서 차이를 검사합니다(immich,
langfuse 방식). 코드 변경이 필요하므로 `maint`·`ai` 세션과 조율해 진행합니다.

## 9. 범위 밖

- 문서 사이트 구축 (Docusaurus 등)
- GitHub 위키
- `api-spec.md` 의 내용 현행화
- `frontend/` 문서 정리 (모듈 존속 여부 결정 후)
- `infra/DEPLOY.md` 수정

## 10. 완료 기준 (1단계)

- 루트 README 와 `docs/README.md` 에서 모든 문서로 이어지는 상대 링크가 깨지지 않습니다.
- 처음 보는 팀원이 `docs/developer/setup.md` 만 따라 backend 와 trading-terminal 을 로컬에서 실행할 수 있습니다.
- `architecture.md` 의 구성도와 시퀀스가 현재 코드의 클래스·엔드포인트 이름과 일치합니다.
- 6절에서 삭제 대상으로 정한 문서가 저장소에 남아 있지 않습니다.
