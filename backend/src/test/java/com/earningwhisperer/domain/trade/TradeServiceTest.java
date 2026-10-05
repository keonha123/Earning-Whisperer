package com.earningwhisperer.domain.trade;

import com.earningwhisperer.domain.portfolio.BrokerAccountRepository;
import com.earningwhisperer.domain.portfolio.PositionService;
import com.earningwhisperer.domain.user.User;
import com.earningwhisperer.presentation.trade.TradeCallbackRequest;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.test.util.ReflectionTestUtils;

import java.time.LocalDateTime;
import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.BDDMockito.given;
import static org.mockito.Mockito.*;

@ExtendWith(MockitoExtension.class)
@DisplayName("TradeService 단위 테스트")
class TradeServiceTest {

    @Mock private TradeRepository tradeRepository;
    // processCallback 이 SELF_PAPER 가상 체결을 반영하려고 이 둘을 쓴다. mock 이 없으면
    // @InjectMocks 가 null 을 주입해 NPE 로 죽는다 (Optional 반환 mock 은 기본값이 empty
    // 라 SELF_PAPER 분기는 그대로 건너뛴다).
    @Mock private BrokerAccountRepository brokerAccountRepository;
    @Mock private PositionService positionService;

    @InjectMocks
    private TradeService tradeService;

    @BeforeEach
    void setUp() {
        ReflectionTestUtils.setField(tradeService, "manualPendingTtlSeconds", 86400L);
    }

    @Test
    @DisplayName("callback 시 Trade 소유자가 다르면 SecurityException이 발생한다")
    void callback_소유권_불일치시_예외발생() {
        // Arrange
        Trade trade = mock(Trade.class);
        User owner = mock(User.class);
        given(owner.getId()).willReturn(1L);
        given(trade.getUser()).willReturn(owner);
        given(tradeRepository.findByIdForUpdate(99L)).willReturn(Optional.of(trade));

        TradeCallbackRequest request = mock(TradeCallbackRequest.class);

        // Act & Assert — callerId=2L은 소유자(1L)와 다름
        assertThatThrownBy(() -> tradeService.processCallback(99L, 2L, request))
                .isInstanceOf(SecurityException.class);
    }

    @Test
    @DisplayName("callback EXECUTED 시 Trade 상태가 EXECUTED로 변경된다")
    void callback_EXECUTED_정상처리() {
        // Arrange
        Trade trade = mock(Trade.class);
        User owner = mock(User.class);
        given(owner.getId()).willReturn(1L);
        given(trade.getUser()).willReturn(owner);
        given(tradeRepository.findByIdForUpdate(99L)).willReturn(Optional.of(trade));

        TradeCallbackRequest request = mock(TradeCallbackRequest.class);
        given(request.getStatus()).willReturn("EXECUTED");
        given(request.getExecutedQty()).willReturn(10);
        given(request.getExecutedPrice()).willReturn(125.50);
        given(request.getBrokerOrderId()).willReturn("BROKER-001");

        // Act
        tradeService.processCallback(99L, 1L, request);

        // Assert
        verify(trade).executed(10, 125.50, "BROKER-001");
        verify(tradeRepository).save(trade);
    }

    @Test
    @DisplayName("callback EXPIRED 상태에서 EXECUTED 수신 시 정정 전이 — trade.executed 호출 + save")
    void callback_EXPIRED에서_EXECUTED_수신시_정정() {
        // Arrange — 이미 TTL 만료로 EXPIRED 된 Trade
        Trade trade = mock(Trade.class);
        User owner = mock(User.class);
        given(owner.getId()).willReturn(1L);
        given(trade.getUser()).willReturn(owner);
        given(trade.getStatus()).willReturn(TradeStatus.EXPIRED);
        given(tradeRepository.findByIdForUpdate(99L)).willReturn(Optional.of(trade));

        TradeCallbackRequest request = mock(TradeCallbackRequest.class);
        given(request.getStatus()).willReturn("EXECUTED");
        given(request.getExecutedQty()).willReturn(3);
        given(request.getExecutedPrice()).willReturn(125.50);
        given(request.getBrokerOrderId()).willReturn("BROKER-LATE-1");

        // Act — 만료 후 KIS 가 실제 체결 결과를 보냄
        tradeService.processCallback(99L, 1L, request);

        // Assert — 도메인 메서드 위임 + 저장. 정정 자체는 Trade.executed 단위 테스트에서 검증.
        verify(trade).executed(3, 125.50, "BROKER-LATE-1");
        verify(tradeRepository).save(trade);
    }

    @Test
    @DisplayName("callback FAILED 시 Trade 상태가 FAILED로 변경된다")
    void callback_FAILED_정상처리() {
        // Arrange
        Trade trade = mock(Trade.class);
        User owner = mock(User.class);
        given(owner.getId()).willReturn(1L);
        given(trade.getUser()).willReturn(owner);
        given(tradeRepository.findByIdForUpdate(99L)).willReturn(Optional.of(trade));

        TradeCallbackRequest request = mock(TradeCallbackRequest.class);
        given(request.getStatus()).willReturn("FAILED");

        // Act
        tradeService.processCallback(99L, 1L, request);

        // Assert
        verify(trade).failed();
        verify(tradeRepository).save(trade);
    }

    @Test
    @DisplayName("processCallback 은 비관적 락 메서드(findByIdForUpdate)로 Trade 를 조회한다 — 회귀 보호")
    void processCallback_비관적_락_메서드_사용_회귀_보호() {
        // Arrange
        Trade trade = mock(Trade.class);
        User owner = mock(User.class);
        given(owner.getId()).willReturn(1L);
        given(trade.getUser()).willReturn(owner);
        given(tradeRepository.findByIdForUpdate(99L)).willReturn(Optional.of(trade));

        TradeCallbackRequest request = mock(TradeCallbackRequest.class);
        given(request.getStatus()).willReturn("FAILED");

        // Act
        tradeService.processCallback(99L, 1L, request);

        // Assert — 동시 콜백 lost update 차단을 위해 반드시 락 메서드를 사용해야 한다.
        verify(tradeRepository).findByIdForUpdate(99L);
        verify(tradeRepository, never()).findById(99L);
    }

    @Test
    @DisplayName("expireStalePending - Repository 의 단일 UPDATE 결과를 그대로 반환")
    void expireStalePending_UPDATE_결과_반환() {
        given(tradeRepository.expirePendingBefore(any(LocalDateTime.class))).willReturn(3);

        int count = tradeService.expireStalePending();

        assertThat(count).isEqualTo(3);
        verify(tradeRepository).expirePendingBefore(any(LocalDateTime.class));
    }

    @Test
    @DisplayName("expireStalePending - threshold 는 현재 시각에서 수동 주문 TTL 을 뺀 값이다")
    void expireStalePending_threshold_는_수동_TTL_기준() {
        LocalDateTime before = LocalDateTime.now().minusSeconds(86400L);

        tradeService.expireStalePending();

        ArgumentCaptor<LocalDateTime> captor = ArgumentCaptor.forClass(LocalDateTime.class);
        verify(tradeRepository).expirePendingBefore(captor.capture());
        LocalDateTime after = LocalDateTime.now().minusSeconds(86400L);
        assertThat(captor.getValue()).isBetween(before, after);
    }

    @Test
    @DisplayName("expireStalePending - 대상이 없으면 0 반환")
    void expireStalePending_대상_없음() {
        given(tradeRepository.expirePendingBefore(any(LocalDateTime.class))).willReturn(0);

        int count = tradeService.expireStalePending();

        assertThat(count).isZero();
    }
}
