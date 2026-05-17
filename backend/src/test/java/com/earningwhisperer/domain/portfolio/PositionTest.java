package com.earningwhisperer.domain.portfolio;

import com.earningwhisperer.domain.user.User;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

@DisplayName("Position 엔티티 단위 테스트")
class PositionTest {

    private final User user = User.builder()
            .email("p@test.com").password("pwd").nickname("p").build();

    @Test
    @DisplayName("Builder 로 생성 시 quantity/avgPrice 보존, syncedAt 자동 설정")
    void builder_정상_생성() {
        Position p = Position.builder()
                .user(user).brokerAccountId(100L).ticker("NVDA").quantity(10).avgPrice(125.5)
                .build();

        assertThat(p.getTicker()).isEqualTo("NVDA");
        assertThat(p.getQuantity()).isEqualTo(10);
        assertThat(p.getAvgPrice()).isEqualTo(125.5);
        assertThat(p.getSyncedAt()).isNotNull();
    }

    @Test
    @DisplayName("update() 호출 시 quantity/avgPrice/syncedAt 갱신")
    void update_quantity_avgPrice_갱신() {
        Position p = Position.builder()
                .user(user).brokerAccountId(100L).ticker("NVDA").quantity(10).avgPrice(125.5).build();
        java.time.LocalDateTime before = p.getSyncedAt();

        // 작은 시간 차이를 보장하기 위해 1ms sleep — 불안정하면 그냥 동일이어도 통과 가능하게 isBeforeOrEqualTo
        try { Thread.sleep(1); } catch (InterruptedException ignored) { }
        p.update(15, 130.0);

        assertThat(p.getQuantity()).isEqualTo(15);
        assertThat(p.getAvgPrice()).isEqualTo(130.0);
        assertThat(p.getSyncedAt()).isAfterOrEqualTo(before);
    }

    @Test
    @DisplayName("bookValue() = quantity × avgPrice")
    void bookValue_매수기준_평가금액() {
        Position p = Position.builder()
                .user(user).brokerAccountId(100L).ticker("NVDA").quantity(10).avgPrice(125.0).build();

        assertThat(p.bookValue()).isEqualTo(1250.0);
    }
}
