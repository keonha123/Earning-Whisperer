# 테스트

이 문서는 모듈별 테스트 실행 명령, CI 가 돌리는 검사, backend 를 중심으로 한 테스트 작성 관례를 다룹니다.
코드를 고치고 PR 을 올리기 전에 테스트를 돌려 보는 팀원과 기여자를 위한 문서입니다. 개발 환경 준비는
[setup.md](setup.md)를 참고합니다.

## 모듈별 실행

### backend

```bash
cd backend
./gradlew test
```

테스트는 H2 인메모리 DB 를 씁니다(`src/test/resources/application.yml`). Redis 는 Lettuce 가 지연 연결이라
실제로 붙지 않으므로 docker compose 를 띄우지 않아도 됩니다. 결과 보고서는 `build/reports/tests/test/` 에 생깁니다.

Gradle 은 입력이 바뀌지 않았다고 판단하면 `test` 태스크를 `UP-TO-DATE` 로 건너뛰고 종료 코드 0 을
돌려줍니다. 출력이 없어 통과한 것처럼 보이므로, 다시 돌려야 할 때는 `./gradlew test --rerun-tasks` 를 씁니다.

### trading-terminal

```bash
cd trading-terminal
npm test               # vitest run
npm run test:watch     # vitest 감시 모드
npm run test:coverage  # 커버리지 포함
npm run typecheck      # main·renderer tsconfig 타입 검사
```

`vitest.config.ts` 기준으로 `src/**/__tests__/**/*.test.ts` 를 Node 환경에서 실행합니다. `.test.tsx` 는 대상에
들어가지 않습니다. 공통 설정 `src/test/setup.ts` 가 axios, electron, keytar 를 전역으로 mock 합니다. 그래서 KIS 와 backend 로 실제
요청이 나가지 않고, `npm install --ignore-scripts` 로 설치한 환경에서도 테스트가 돕니다.

### ai-engine

```bash
cd ai-engine
python -m pytest -q
```

`.env` 와 API 키 없이 돕니다. `tests/conftest.py` 가 모듈을 불러오기 전에 임베딩을 해시 방식으로, 벡터
저장소를 메모리로 고정해 테스트가 Gemini 를 호출하지 않습니다. `pytest.ini` 는 임시 디렉터리를
`data/pytest_tmp` 로 지정합니다. `tests/manual_nvda_fact_check.py` 는 파일명이 `test_` 로 시작하지 않아
기본 수집 대상이 아닙니다.

### data_pipeline

`data_pipeline/tests/` 의 테스트는 대부분 `unittest` 로 작성되어 있고 `data_pipeline.*` 패키지 경로로 import 하므로
저장소 루트에서 실행합니다. `test_news_article_extractor.py`, `test_manual_transcript_import.py` 두 파일은 pytest
형식이라 `unittest` 로는 수집되지 않습니다. CI 에는 포함되어 있지 않습니다.

## CI

`.github/workflows/test.yml` 의 `test` 워크플로가 모든 PR 과 `main` 푸시에서 돕니다. 같은 브랜치에 연달아
푸시하면 앞선 실행을 취소합니다. 세 잡은 서로 독립이라 병렬로 돌고 한 잡이 실패해도 나머지 결과를 볼 수
있습니다.

| 잡 | 환경 | 실행 내용 |
|---|---|---|
| `backend` | ubuntu, JDK 17 (temurin) | `./gradlew test`. 실패해도 테스트 보고서를 artifact `backend-test-results` 로 7일 보관 |
| `terminal` | ubuntu, Node 20 | `npm install --ignore-scripts` → `npm run typecheck` → `npm test` |
| `ai-engine` | ubuntu, Python 3.12 | `pip install -r requirements.txt` → `python -m pytest -q` |

data_pipeline 과 frontend 는 CI 대상이 아닙니다. terminal 잡이 `npm ci` 대신 `npm install` 을 쓰는 이유는
`package.json` 과 `package-lock.json` 이 맞지 않아 `npm ci` 가 실패하기 때문입니다.

## backend 테스트 작성 관례

현재 테스트 코드에서 확인되는 관례입니다.

| 항목 | 관례 |
|---|---|
| 클래스 이름 | `{대상 클래스}Test`. 테스트 대상과 같은 패키지에 둡니다 |
| 메서드 이름 | 한글과 밑줄로 시나리오와 기대 결과를 적습니다. 예: `같은_종목_중복_시작은_거부된다`, `buildMessage_세션_종료_이벤트_isSessionEnd가_true`. 일부 영문 이름도 있습니다 |
| 설명 | 클래스와 메서드에 `@DisplayName` 을 붙여 문장으로 설명하는 경우가 많습니다. 묶음이 필요하면 `@Nested` 를 씁니다 |
| 검증 | AssertJ `assertThat` 을 씁니다 |
| 구조 | 일부 테스트는 `// Arrange`, `// Act`, `// Assert` 주석으로 단계를 나눕니다 |

테스트 종류별로 쓰는 어노테이션입니다.

| 종류 | 어노테이션 | 사용처 |
|---|---|---|
| 단위 테스트 | 없음, 또는 `@ExtendWith(MockitoExtension.class)` | 엔티티, 서비스, 발행기 등 대부분의 테스트 |
| JPA 슬라이스 | `@DataJpaTest` | `UserRepositoryTest`, `TradeRepositoryTest` 등 Repository 쿼리 |
| MVC 슬라이스 | `@WebMvcTest` + `@MockBean` | `AuthControllerTest`, `DemoEarningsCallControllerTest` 등 컨트롤러 |
| 통합 테스트 | `@SpringBootTest` | `infrastructure/sync` 의 트랜잭션 격리 테스트 |

MySQL, Redis, 외부 API 에는 연결하지 않습니다. DB 는 H2 로, 외부 클라이언트는 Mockito 로 대체합니다.
테스트용 데이터 파일은 `src/test/resources/` 아래에 둡니다.
