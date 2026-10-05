package com.earningwhisperer.domain.trade;

import com.earningwhisperer.domain.portfolio.AccountType;
import com.earningwhisperer.domain.portfolio.BrokerAccountRepository;
import com.earningwhisperer.domain.portfolio.PositionService;
import com.earningwhisperer.domain.signal.TradeAction;
import com.earningwhisperer.domain.user.User;
import com.earningwhisperer.domain.user.UserRepository;
import com.earningwhisperer.presentation.trade.ManualTradeRequest;
import com.earningwhisperer.presentation.trade.TradeCallbackRequest;
import com.earningwhisperer.presentation.trade.TradeResponse;
import jakarta.persistence.EntityNotFoundException;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;

/**
 * 거래 기록 서비스.
 *
 * 백엔드는 KIS 증권사 API를 직접 호출하지 않는다.
 * 주문은 Trading Terminal(데스크톱 앱)이 사용자 입력으로 실행하고 결과를 기록하며,
 * 미체결 주문의 체결 결과는 콜백 API(POST /api/v1/trades/{tradeId}/callback)로 수신한다.
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class TradeService {

    private final TradeRepository tradeRepository;
    private final UserRepository userRepository;
    private final BrokerAccountRepository brokerAccountRepository;
    private final PositionService positionService;

    /**
     * 수동 주문 PENDING 의 TTL. 증권사에 실제로 들어가 체결을 기다리는 지정가 주문이다.
     * KIS 당일 주문은 장 마감 시 취소되므로 하루가 지난 PENDING 은 죽은 주문으로 본다.
     */
    @Value("${app.trade.manual-pending-ttl-seconds:86400}")
    private long manualPendingTtlSeconds;

    @Transactional(readOnly = true)
    public Page<TradeResponse> getMyTrades(Long userId, Pageable pageable, LocalDateTime startDate) {
        if (startDate == null) {
            return tradeRepository.findByUserId(userId, pageable).map(TradeResponse::new);
        }
        return tradeRepository.findByUserIdAndCreatedAtGreaterThanEqual(userId, startDate, pageable)
                .map(TradeResponse::new);
    }

    /**
     * 사용자가 OrderBar 에서 직접 입력한 수동 주문을 기록한다.
     * 주문은 Terminal 에서 이미 실행된 상태이므로 결과에 따라 EXECUTED/FAILED 로 저장하고,
     * 접수만 되고 체결되지 않은 주문은 PENDING 으로 남긴다.
     */
    @Transactional
    public Long createManualTrade(Long userId, Long brokerAccountId, ManualTradeRequest req) {
        User user = userRepository.findById(userId)
                .orElseThrow(() -> new EntityNotFoundException("User not found: " + userId));

        Trade trade = Trade.builder()
                .user(user)
                .brokerAccountId(brokerAccountId)
                .ticker(req.getTicker())
                .side(req.getSide())
                .orderType(req.getOrderType())
                .orderQty(req.getOrderQty())
                .price(req.getPrice())
                .brokerOrderId(req.getBrokerOrderId())
                .build();

        // Trade 는 생성 시 PENDING 이다. 미체결 주문은 그 상태를 그대로 둔다 —
        // FAILED 로 적으면 살아 있는 주문을 실패로 기록하는 것이 된다.
        if ("EXECUTED".equals(req.getStatus())) {
            trade.executed(req.getExecutedQty(), req.getExecutedPrice(), req.getBrokerOrderId());
        } else if ("FAILED".equals(req.getStatus())) {
            trade.failed();
        }

        Trade saved = tradeRepository.save(trade);
        log.info("[TradeService] 수동 주문 기록 - userId={} ticker={} side={} status={} tradeId={}",
                userId, req.getTicker(), req.getSide(), req.getStatus(), saved.getId());
        // tradeId 를 돌려줘야 PENDING 으로 기록된 미체결 주문을 나중에 콜백으로 종결시킬 수
        // 있다. void 였던 동안에는 호출자가 id 를 알 수 없어 종결 경로 자체가 없었다.
        return saved.getId();
    }

    /**
     * Scheduler 진입점. TTL 초과한 PENDING Trade 를 EXPIRED 로 일괄 전환한다.
     *
     * 단일 @Modifying UPDATE 로 처리하므로 (1) 멀티 인스턴스 동시 실행 시 lost update 가 없고
     * (2) WHERE status = 'PENDING' 절이 동시에 commit 된 EXECUTED 콜백을 절대 덮어쓰지 않는다.
     *
     * @return 만료된 Trade 개수
     */
    @Transactional
    public int expireStalePending() {
        LocalDateTime threshold = LocalDateTime.now().minusSeconds(manualPendingTtlSeconds);
        int affected = tradeRepository.expirePendingBefore(threshold);
        if (affected > 0) {
            log.info("[TradeService] PENDING TTL 만료 전환 - count={} threshold={}", affected, threshold);
        }
        return affected;
    }

    /**
     * Contract 4 — Trading Terminal 체결 콜백 처리.
     * Trade 상태를 PENDING → EXECUTED / FAILED 로 전환한다.
     * 순수 DB 작업이므로 @Transactional 사용 (외부 HTTP 없음).
     *
     * <p>같은 tradeId 의 다른 brokerOrderId 를 가진 두 콜백이 거의 동시에 도착해도
     * {@link TradeRepository#findByIdForUpdate}(SELECT ... FOR UPDATE) 로 row 를 잠가
     * lost update 를 차단한다. 늦게 진입한 트랜잭션은 commit 후 EXECUTED/FAILED 를 읽고
     * {@link Trade#executed} / {@link Trade#failed} 의 멱등 분기로 200 OK 를 반환한다.
     *
     * @param callerId JWT에서 추출한 요청자 userId — 소유권 검증에 사용
     */
    @Transactional
    public void processCallback(Long tradeId, Long callerId, TradeCallbackRequest request) {
        Trade trade = tradeRepository.findByIdForUpdate(tradeId)
                .orElseThrow(() -> new EntityNotFoundException("Trade를 찾을 수 없습니다. tradeId=" + tradeId));

        if (!trade.getUser().getId().equals(callerId)) {
            throw new SecurityException("Trade 소유권 불일치 - tradeId=" + tradeId + " callerId=" + callerId);
        }

        TradeStatus before = trade.getStatus();
        if ("EXECUTED".equals(request.getStatus())) {
            int qty = request.getExecutedQty() != null ? request.getExecutedQty() : 0;
            double price = request.getExecutedPrice() != null ? request.getExecutedPrice() : 0.0;
            trade.executed(qty, price, request.getBrokerOrderId());
            if (before == TradeStatus.EXECUTED) {
                log.warn("[TradeService] 멱등 콜백 감지(EXECUTED 재수신) - tradeId={} brokerOrderId={}",
                        tradeId, request.getBrokerOrderId());
            } else if (before == TradeStatus.EXPIRED) {
                log.warn("[TradeService] late EXECUTED 정정 — 만료 후 KIS 체결 도착 tradeId={} brokerOrderId={} qty={}",
                        tradeId, request.getBrokerOrderId(), qty);
            } else {
                log.info("[TradeService] 체결 완료 - tradeId={} brokerOrderId={} qty={}",
                        tradeId, request.getBrokerOrderId(), qty);
            }

            // SELF_PAPER: 가상 체결 → Position + cashBalance 직접 반영
            if (qty > 0 && before != TradeStatus.EXECUTED) {
                brokerAccountRepository.findById(trade.getBrokerAccountId()).ifPresent(account -> {
                    if (account.getAccountType() == AccountType.SELF_PAPER) {
                        positionService.applyTrade(
                                trade.getUser().getId(), account.getId(),
                                trade.getTicker(), trade.getSide(), qty, price);
                        double delta = trade.getSide() == TradeAction.BUY
                                ? -(price * qty) : (price * qty);
                        account.adjustCashBalance(delta);
                        log.info("[TradeService] SELF_PAPER 가상 체결 반영 - tradeId={} side={} qty={} price={} cashDelta={}",
                                tradeId, trade.getSide(), qty, price, delta);
                    }
                });
            }
        } else {
            trade.failed();
            if (before == TradeStatus.FAILED) {
                log.warn("[TradeService] 멱등 콜백 감지(FAILED 재수신) - tradeId={}", tradeId);
            } else {
                log.warn("[TradeService] 체결 실패 - tradeId={} error={}", tradeId, request.getErrorMessage());
            }
        }
        tradeRepository.save(trade);
    }
}
