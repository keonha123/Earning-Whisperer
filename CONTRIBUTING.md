# 기여 안내

EarningWhisperer 에 코드나 문서를 보태려는 팀원과 기여자를 위한 문서입니다. 이슈를 열고 PR 이 머지되기까지의
규칙을 다룹니다. 로컬 실행 방법은 [`docs/developer/setup.md`](docs/developer/setup.md) 에 있습니다.

## 이슈

작업은 이슈에서 시작합니다. 빈 이슈는 막혀 있어서 아래 네 양식 중 하나를 골라 작성합니다.

| 양식 | 쓰는 경우 |
|---|---|
| 기능 · 개선 (`[feat]`) | 새로 만들 것, 이미 있는 것을 바꿀 것 |
| 버그 (`[bug]`) | 있어야 할 동작이 안 되는 것 |
| 조사 · 검증 (`[spike]`) | 무엇을 만들지 정하기 전에 측정·실험·조사가 필요한 것 |
| 정리 · 인프라 · 문서 (`[chore]`) | 동작을 바꾸지 않는 작업 |

여러 모듈에 걸치거나 계약(REST·STOMP·DB)을 바꾸는 큰 변경은 코드를 쓰기 전에 이슈에서 먼저 논의합니다.
아직 작업으로 정해지지 않은 질문이나 아이디어는 GitHub Discussions 에 올리고, 결론이 나면 이슈로 옮깁니다.

## 브랜치와 커밋

- `main` 에서 브랜치를 따서 작업하고 PR 로 머지합니다. 브랜치 이름은 앞으로 `<이름>/<종류>/<주제>` 형식을 씁니다
  (예: `keonha/fix/macos-drag-region`).
- 커밋 메시지는 `종류(범위): 요약` 형식입니다. 요약은 한국어 습니다체로 씁니다. 이 규칙은 이 문서를 만든 시점부터 적용하며 이전 커밋은 문체가 섞여 있습니다.
  - 종류: `feat`, `fix`, `refactor`, `test`, `docs`, `chore`
  - 범위: `backend`, `terminal`, `ai-engine`, `data-pipeline`, `infra`, `ci`, `repo`
  - 예: `fix(terminal): macOS 에서만 창 드래그 영역을 둡니다`

## PR

- PR 하나에는 한 가지 변경만 담습니다.
- 본문은 [PR 템플릿](.github/pull_request_template.md)의 항목을 채웁니다. 확인하지 못한 것은 "미확인" 으로 남깁니다.
- `.github/workflows/test.yml` 의 `test` 워크플로(backend·ai-engine 테스트, trading-terminal 타입 검사와 테스트)가 통과한 뒤 머지합니다.
  지금은 브랜치 보호로 강제하지 않습니다.
- 코드를 바꾸면 그 코드를 설명하는 문서도 같은 PR 에서 고칩니다. 계약이 바뀌면 `docs/api-spec.md` 도 고칩니다.
  문서 운영 규칙은 [`docs/README.md`](docs/README.md) 에 있습니다.
- AI 도구로 작성하거나 생성한 부분이 있으면 PR 본문의 "리뷰 포인트" 에 그 범위를 밝힙니다.

## 리뷰 담당

모듈마다 담당자가 있고 PR 을 열면 [`.github/CODEOWNERS`](.github/CODEOWNERS) 에 따라 리뷰어가 지정됩니다.
담당자가 아닌 모듈을 고칠 때는 해당 담당자의 리뷰를 받습니다.

| 모듈 | 담당 |
|---|---|
| backend, trading-terminal, infra, docs, .github | @keonha123 |
| ai-engine | @james10419, @yytss3 |
| data_pipeline | @dheorb |
