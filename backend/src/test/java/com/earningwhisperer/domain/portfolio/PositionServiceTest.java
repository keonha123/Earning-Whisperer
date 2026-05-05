package com.earningwhisperer.domain.portfolio;

import com.earningwhisperer.domain.user.User;
import com.earningwhisperer.domain.user.UserRepository;
import com.earningwhisperer.presentation.portfolio.PortfolioSyncRequest;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.util.List;
import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.argThat;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.BDDMockito.given;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;

@ExtendWith(MockitoExtension.class)
@DisplayName("PositionService 단위 테스트")
class PositionServiceTest {

    @Mock private PositionRepository positionRepository;
    @Mock private UserRepository userRepository;

    @InjectMocks
    private PositionService positionService;

    private final ObjectMapper mapper = new ObjectMapper();
    private static final long BROKER = 100L;
    private static final long USER_ID = 1L;

    private List<PortfolioSyncRequest.PositionDto> dtos(String json) throws Exception {
        PortfolioSyncRequest req = mapper.readValue(json, PortfolioSyncRequest.class);
        return req.getPositions();
    }

    @Test
    @DisplayName("computeBookRatio - 보유 ticker 비중을 매수 기준으로 산출")
    void computeBookRatio_매수기준_비중() {
        User user = mock(User.class);
        Position nvda = Position.builder().user(user).brokerAccountId(BROKER)
                .ticker("NVDA").quantity(10).avgPrice(100.0).build(); // 1000
        Position tsla = Position.builder().user(user).brokerAccountId(BROKER)
                .ticker("TSLA").quantity(5).avgPrice(200.0).build(); // 1000
        given(positionRepository.findByBrokerAccountId(BROKER)).willReturn(List.of(nvda, tsla));

        // 총자산 = 8000(cash) + 1000(NVDA) + 1000(TSLA) = 10000. NVDA = 1000/10000 = 0.1
        double ratio = positionService.computeBookRatio(BROKER, "NVDA", 8000.0);

        assertThat(ratio).isEqualTo(0.1);
    }

    @Test
    @DisplayName("computeBookRatio - 미보유 ticker 는 0")
    void computeBookRatio_미보유_0() {
        given(positionRepository.findByBrokerAccountId(BROKER)).willReturn(List.of());

        assertThat(positionService.computeBookRatio(BROKER, "NVDA", 10000.0)).isZero();
    }

    @Test
    @DisplayName("computeBookRatio - cashBalance null 이면 0 (검증 우회)")
    void computeBookRatio_cashBalance_null_은_0() {
        assertThat(positionService.computeBookRatio(BROKER, "NVDA", null)).isZero();
    }

    @Test
    @DisplayName("computeBookRatio - cashBalance 0 이하면 0")
    void computeBookRatio_cashBalance_0_은_0() {
        assertThat(positionService.computeBookRatio(BROKER, "NVDA", 0.0)).isZero();
        assertThat(positionService.computeBookRatio(BROKER, "NVDA", -100.0)).isZero();
    }

    @Test
    @DisplayName("syncSnapshot - 빈/null positions 는 fail-safe no-op (Terminal 일시 장애 시 데이터 보존)")
    void syncSnapshot_빈_리스트_no_op() {
        int upsertedEmpty = positionService.syncSnapshot(USER_ID, BROKER, List.of());
        int upsertedNull = positionService.syncSnapshot(USER_ID, BROKER, null);

        assertThat(upsertedEmpty).isZero();
        assertThat(upsertedNull).isZero();
        verify(positionRepository, never()).deleteByBrokerAccountId(any());
        verify(positionRepository, never()).deleteByBrokerAccountIdAndTickerNotIn(any(), any());
    }

    @Test
    @DisplayName("syncSnapshot - 보낸 ticker 만 유지하고 누락은 삭제")
    void syncSnapshot_누락_삭제() throws Exception {
        List<PortfolioSyncRequest.PositionDto> incoming = dtos("""
                {"cash_balance":1000,"positions":[
                    {"ticker":"NVDA","quantity":10,"avg_price":125.0}
                ]}
                """);
        given(positionRepository.findByBrokerAccountId(BROKER)).willReturn(List.of());
        given(userRepository.findById(USER_ID)).willReturn(Optional.of(mock(User.class)));

        positionService.syncSnapshot(USER_ID, BROKER, incoming);

        verify(positionRepository).deleteByBrokerAccountIdAndTickerNotIn(eq(BROKER),
                argThat(set -> set != null && set.contains("NVDA") && set.size() == 1));
    }

    @Test
    @DisplayName("syncSnapshot - 기존 ticker 는 update, 신규는 save")
    void syncSnapshot_upsert() throws Exception {
        List<PortfolioSyncRequest.PositionDto> incoming = dtos("""
                {"cash_balance":1000,"positions":[
                    {"ticker":"NVDA","quantity":15,"avg_price":130.0},
                    {"ticker":"TSLA","quantity":5,"avg_price":200.0}
                ]}
                """);
        Position existingNvda = mock(Position.class);
        given(existingNvda.getTicker()).willReturn("NVDA");
        given(positionRepository.findByBrokerAccountId(BROKER)).willReturn(List.of(existingNvda));

        User userRef = mock(User.class);
        given(userRepository.findById(USER_ID)).willReturn(Optional.of(userRef));

        int upserted = positionService.syncSnapshot(USER_ID, BROKER, incoming);

        assertThat(upserted).isEqualTo(2);
        verify(existingNvda).update(15, 130.0);
        verify(positionRepository).save(any(Position.class));
    }

    @Test
    @DisplayName("syncSnapshot - 비정상 dto (quantity ≤ 0, avgPrice ≤ 0, ticker 누락) 는 skip")
    void syncSnapshot_비정상_dto_skip() throws Exception {
        List<PortfolioSyncRequest.PositionDto> incoming = dtos("""
                {"cash_balance":1000,"positions":[
                    {"ticker":"NVDA","quantity":0,"avg_price":125.0},
                    {"ticker":"TSLA","quantity":5,"avg_price":0},
                    {"ticker":"","quantity":3,"avg_price":100.0},
                    {"ticker":"AAPL","quantity":3,"avg_price":180.0}
                ]}
                """);
        given(positionRepository.findByBrokerAccountId(BROKER)).willReturn(List.of());
        User userRef = mock(User.class);
        given(userRepository.findById(USER_ID)).willReturn(Optional.of(userRef));

        int upserted = positionService.syncSnapshot(USER_ID, BROKER, incoming);

        assertThat(upserted).isEqualTo(1);
    }
}
