# 🧪 EarningWhisperer 테스트 지침 (Testing Guidelines)

## 1. 테스트 철학

> **"테스트는 코드가 동작하는 증거이자, 미래의 변경을 두렵지 않게 만드는 안전망이다."**

본 프로젝트는 아래 두 가지 원칙을 기반으로 테스트를 작성합니다.

1. **빠른 피드백:** 테스트는 외부 인프라(MySQL, Redis 등)에 의존하지 않고 로컬에서 즉시 실행 가능해야 합니다.
2. **명확한 범위:** 각 테스트는 하나의 동작만 검증합니다. 여러 관심사를 하나의 테스트에 섞지 않습니다.

---

## 2. 테스트 피라미드

```
        /‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾\
       /   E2E / 통합 테스트   \   ← 적게, 느림, 비용 높음
      /‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾\
     /   슬라이스 테스트 (JPA, MVC) \   ← 중간
    /‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾\
   /         단위 테스트              \   ← 많이, 빠름, 비용 낮음
  /‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾\
```

| 레이어 | 목적 | 속도 | Spring 컨텍스트 |
|--------|------|------|----------------|
| 단위 테스트 | 클래스/메서드 단독 검증 | 매우 빠름 (~ms) | 불필요 |
| 슬라이스 테스트 | JPA, MVC, Redis 레이어 부분 검증 | 보통 (~초) | 부분 로딩 |
| 통합/E2E 테스트 | 전체 시스템 흐름 검증 | 느림 (~분) | 전체 로딩 |

---

## 3. Phase별 테스트 도입 방침

| Phase | 구현 내용 | 작성 테스트 | 사용 어노테이션 |
|-------|----------|------------|--------------|
| **Phase 0** | 프로젝트 초기화 | 없음 (코드 없음) | — |
| **Phase 1** | 도메인 엔티티 + Repository | 엔티티 단위 테스트, Repository 슬라이스 테스트 | `@DataJpaTest` |
| **Phase 2** | Redis Pub/Sub, EMA 연산 | EMA 서비스 단위 테스트 | 없음 (순수 JUnit) |
| **Phase 3** | WebSocket/STOMP | 메시지 브로드캐스트 단위 테스트 | `@WebMvcTest` (일부) |
| **Phase 4** | 룰 엔진 | 룰 판단 로직 단위 테스트 | 없음 (순수 JUnit) |
| **Phase 5** | 증권사 API 연동 | Mock 기반 API 클라이언트 테스트 | Mockito |

---

## 4. 테스트 종류별 어노테이션

### 4-1. 순수 단위 테스트 (어노테이션 없음)

Spring 컨텍스트 없이 순수 Java 객체를 테스트합니다. 가장 빠릅니다.

```java
// 예: Trade 엔티티 상태 전환 테스트
class TradeTest {
    @Test
    void executed_호출시_상태가_EXECUTED로_변경된다() {
        // Arrange
        Trade trade = Trade.builder()...build();
        // Act
        trade.executed(10, "ORDER-001");
        // Assert
        assertThat(trade.getStatus()).isEqualTo(TradeStatus.EXECUTED);
    }
}
```

**사용 대상:** 엔티티 비즈니스 메서드, 순수 계산 로직 (EMA 연산 등)

---

### 4-2. `@DataJpaTest` — JPA 슬라이스 테스트

JPA 관련 Bean만 로딩하는 경량 테스트. H2 인메모리 DB를 사용합니다.

```java
@DataJpaTest
@Import(JpaConfig.class)   // @EnableJpaAuditing 활성화
class UserRepositoryTest {
    @Autowired
    private UserRepository userRepository;
    ...
}
```

**사용 대상:** Repository 커스텀 쿼리 메서드 검증
**특징:**
- MySQL 없이 H2로 자동 대체
- `@Transactional`이 기본 적용 — 각 테스트 후 DB 롤백
- `spring-boot-starter-web`, `spring-boot-starter-security` 등은 로딩하지 않음

---

### 4-3. `@WebMvcTest` — MVC 슬라이스 테스트 (Phase 3+ 사용 예정)

Controller 레이어만 로딩. 서비스/레포지토리는 Mock으로 대체합니다.

```java
@WebMvcTest(SomeController.class)
class SomeControllerTest {
    @Autowired
    private MockMvc mockMvc;

    @MockBean
    private SomeService someService;
    ...
}
```

---

### 4-4. `@SpringBootTest` — 통합 테스트 (Phase 5+ 사용 예정)

전체 애플리케이션 컨텍스트를 로딩. 실제 DB/외부 연동이 필요한 경우 사용.

```java
@SpringBootTest
@Transactional
class SomeIntegrationTest { ... }
```

**주의:** 느리므로 CI에서만 실행하거나 최소화합니다.

---

## 5. AAA 패턴 (Arrange-Act-Assert)

모든 테스트는 3개 블록으로 구성합니다.

```java
@Test
void 메서드명_시나리오_기대결과() {
    // Arrange (준비) — 테스트에 필요한 객체/데이터 준비
    User user = User.builder().email("test@test.com").password("pw").nickname("tester").build();

    // Act (실행) — 테스트 대상 메서드 호출
    Optional<User> result = userRepository.findByEmail("test@test.com");

    // Assert (검증) — 결과 검증
    assertThat(result).isPresent();
    assertThat(result.get().getEmail()).isEqualTo("test@test.com");
}
```

---

## 6. 테스트 명명 규칙

### 메서드명: `대상_시나리오_기대결과` (한글 허용)

```java
// 좋은 예
void findByEmail_존재하는_이메일로_조회시_사용자를_반환한다()
void executed_호출시_상태가_EXECUTED로_변경된다()
void findByEmail_존재하지_않는_이메일로_조회시_빈값을_반환한다()

// 나쁜 예
void test1()
void testFindByEmail()
```

### 클래스명: `{대상클래스명}Test`

```
UserRepositoryTest.java
TradeTest.java
PortfolioSettingsTest.java
```

---

## 7. 외부 의존성 격리 원칙

단위/슬라이스 테스트에서는 외부 시스템에 절대 연결하지 않습니다.

| 외부 의존성 | 대체 방법 |
|------------|---------|
| MySQL | H2 인메모리 DB (`@DataJpaTest` 자동 적용) |
| Redis | `@MockBean` 또는 Embedded Redis |
| 증권사 API | `@MockBean` (Mockito) |
| 시간(LocalDateTime.now()) | `Clock` 주입 또는 `@PrePersist` 활용 |

---

## 8. 현재 Phase 1 테스트 목록

### 단위 테스트

| 클래스 | 메서드 | 검증 내용 |
|--------|--------|---------|
| `TradeTest` | Builder 초기값 | `status=PENDING`, `executedQty=0` |
| `TradeTest` | `executed()` | `status=EXECUTED`, `executedQty`, `brokerOrderId` 설정 |
| `TradeTest` | `failed()` | `status=FAILED` |
| `PortfolioSettingsTest` | `update()` | 모든 설정 필드 변경 반영 |

### Repository 슬라이스 테스트 (`@DataJpaTest`)

| 클래스 | 메서드 | 검증 내용 |
|--------|--------|---------|
| `UserRepositoryTest` | `findByEmail` | 존재/미존재 케이스 |
| `UserRepositoryTest` | `existsByEmail` | true/false 케이스 |
| `PortfolioSettingsRepositoryTest` | `findByUserId` | User 저장 후 설정 조회 |
| `SignalHistoryRepositoryTest` | `findByUserIdAndTickerOrderByCreatedAtDesc` | ticker 필터링 + 정렬 |
| `SignalHistoryRepositoryTest` | `findByUserIdOrderByCreatedAtDesc` | 전체 조회 + 정렬 |
| `TradeRepositoryTest` | `findByUserIdOrderByCreatedAtDesc` | 정렬 검증 |
| `TradeRepositoryTest` | `findByUserIdAndTickerOrderByCreatedAtDesc` | ticker 필터링 |
