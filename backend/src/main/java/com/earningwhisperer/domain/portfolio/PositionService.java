package com.earningwhisperer.domain.portfolio;

import com.earningwhisperer.domain.signal.TradeAction;
import com.earningwhisperer.domain.user.User;
import com.earningwhisperer.domain.user.UserRepository;
import com.earningwhisperer.presentation.portfolio.PortfolioSyncRequest;
import jakarta.persistence.EntityNotFoundException;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * 사용자 보유종목(Position) 관리.
 *
 * Trading Terminal 의 잔고 sync 결과를 BrokerAccount 단위 snapshot 으로 보존한다.
 * 보낸 목록에 없는 ticker 는 삭제, 있는 ticker 는 upsert.
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class PositionService {

    private final PositionRepository positionRepository;
    private final UserRepository userRepository;

    @Transactional(readOnly = true)
    public List<Position> getPositions(Long brokerAccountId) {
        return positionRepository.findByBrokerAccountId(brokerAccountId);
    }

    /**
     * Terminal snapshot 동기화 — 해당 BrokerAccount 의 보유종목을 source of truth 로 받아 upsert + 누락 삭제.
     *
     * <p>fail-safe: 빈/null positions 는 no-op. Terminal 의 일시 장애로 빈 리스트가 도달하면 모든 row 삭제 →
     * currentPositionRatio = 0 → BUY 가드 무력화 위험. 사용자가 진짜 전 종목 매도했다면 다음 신호에서
     * stale position 기준으로 보수적으로 동작 (BUY 차단) → 안전 측 fail.
     *
     * @param userId           대상 사용자 ID (소유권 검증)
     * @param brokerAccountId  대상 BrokerAccount
     * @param positions        Terminal 이 보낸 보유종목 목록
     * @return upsert 된 row 수 (빈/null 이면 0)
     */
    @Transactional
    public int syncSnapshot(Long userId, Long brokerAccountId,
                             List<PortfolioSyncRequest.PositionDto> positions) {
        if (positions == null || positions.isEmpty()) {
            log.info("[PositionService] 빈 snapshot — fail-safe no-op userId={} brokerAccountId={}",
                    userId, brokerAccountId);
            return 0;
        }

        // 1. 보낸 목록에 없는 ticker 삭제
        Set<String> incomingTickers = new HashSet<>();
        for (PortfolioSyncRequest.PositionDto dto : positions) {
            if (dto.getTicker() != null && !dto.getTicker().isBlank()) {
                incomingTickers.add(dto.getTicker());
            }
        }
        if (incomingTickers.isEmpty()) {
            log.warn("[PositionService] 모든 dto 의 ticker 가 비어있음 — no-op brokerAccountId={}",
                    brokerAccountId);
            return 0;
        }
        positionRepository.deleteByBrokerAccountIdAndTickerNotIn(brokerAccountId, incomingTickers);

        // 2. 기존 row 일괄 조회 후 ticker → entity map
        List<Position> existing = positionRepository.findByBrokerAccountId(brokerAccountId);
        Map<String, Position> byTicker = new HashMap<>();
        for (Position p : existing) byTicker.put(p.getTicker(), p);

        // 3. upsert
        User userRef = null;
        int upserted = 0;
        for (PortfolioSyncRequest.PositionDto dto : positions) {
            if (dto.getTicker() == null || dto.getTicker().isBlank()) continue;
            if (dto.getQuantity() == null || dto.getQuantity() <= 0) continue;
            if (dto.getAvgPrice() == null || dto.getAvgPrice() <= 0) continue;

            Position found = byTicker.get(dto.getTicker());
            if (found != null) {
                found.update(dto.getQuantity(), dto.getAvgPrice());
            } else {
                if (userRef == null) {
                    userRef = userRepository.findById(userId)
                            .orElseThrow(() -> new EntityNotFoundException("User not found: " + userId));
                }
                positionRepository.save(Position.builder()
                        .user(userRef)
                        .brokerAccountId(brokerAccountId)
                        .ticker(dto.getTicker())
                        .quantity(dto.getQuantity())
                        .avgPrice(dto.getAvgPrice())
                        .build());
            }
            upserted++;
        }
        return upserted;
    }

    /**
     * SELF_PAPER 가상 체결 반영 — BUY 시 upsert(가중평균가), SELL 시 수량 차감(잔량 0이면 삭제).
     * TradeService.processCallback 이 SELF_PAPER 콜백 수신 시 호출한다.
     */
    @Transactional
    public void applyTrade(Long userId, Long brokerAccountId, String ticker,
                            TradeAction side, int qty, double price) {
        if (side == TradeAction.BUY) {
            positionRepository.findByBrokerAccountIdAndTicker(brokerAccountId, ticker)
                    .ifPresentOrElse(
                            p -> {
                                double newAvg = (p.getAvgPrice() * p.getQuantity() + price * qty)
                                        / (p.getQuantity() + qty);
                                p.update(p.getQuantity() + qty, newAvg);
                            },
                            () -> {
                                User user = userRepository.findById(userId)
                                        .orElseThrow(() -> new EntityNotFoundException(
                                                "User not found: " + userId));
                                positionRepository.save(Position.builder()
                                        .user(user)
                                        .brokerAccountId(brokerAccountId)
                                        .ticker(ticker)
                                        .quantity(qty)
                                        .avgPrice(price)
                                        .build());
                            });
        } else {
            positionRepository.findByBrokerAccountIdAndTicker(brokerAccountId, ticker)
                    .ifPresent(p -> {
                        int remaining = p.getQuantity() - qty;
                        if (remaining <= 0) {
                            positionRepository.delete(p);
                        } else {
                            p.update(remaining, p.getAvgPrice());
                        }
                    });
        }
    }
}
