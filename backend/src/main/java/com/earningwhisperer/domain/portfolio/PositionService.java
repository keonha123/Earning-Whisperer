package com.earningwhisperer.domain.portfolio;

import com.earningwhisperer.domain.signal.TradeAction;
import com.earningwhisperer.domain.stock.DailyBarRepository;
import com.earningwhisperer.domain.stock.TickerLatestClose;
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
import java.util.stream.Collectors;

/**
 * 사용자 보유종목(Position) 관리.
 *
 * Trading Terminal 의 잔고 sync 결과를 BrokerAccount 단위 snapshot 으로 보존한다.
 * 보낸 목록에 없는 ticker 는 삭제, 있는 ticker 는 upsert.
 * RuleEngine 의 maxPositionRatio 검증에 사용된다.
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class PositionService {

    private final PositionRepository positionRepository;
    private final UserRepository userRepository;
    private final DailyBarRepository dailyBarRepository;

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
     * RuleEngine 용 ticker 의 비중 계산. 활성 BrokerAccount 의 cashBalance 와 보유종목으로 산출.
     *
     * <p>시장 기준(daily_bar 의 가장 최근 close × quantity) 우선 + close 부재 시 매수 평균가 fallback.
     * positionRatio = (ticker marketValue) / (cashBalance + Σ all marketValues).
     * ticker 미보유면 0 반환.
     *
     * <p>cashBalance ≤ 0 시 0 반환 — 단 호출 측이 cashBalance 미동기화/0 을 별도 fail-safe HOLD 로
     * 처리한다는 가정. 본 메서드는 비중 분모가 0 이 되는 산술 오류 회피용으로만 0 을 반환하며,
     * "검증 우회" 의미가 아니다. SignalService 가 cashBalance ≤ 0 을 RuleEngine 호출 전에
     * HOLD 로 가로채는 정책 (SignalService.java) 으로 이 메서드의 0 반환이 BUY 가드 무력화로
     * 이어지지 않는다.
     *
     * <p>daily_bar 는 1일 지연 데이터 — 실시간 시세 인프라 도입 전까지는 D-1 close 가 정확도 한계.
     * fallback (avgPrice) 사용 시 운영 가시성을 위해 카운트 집계 후 비율에 따라 WARN/DEBUG 로깅한다.
     */
    @Transactional(readOnly = true)
    public double computePositionRatio(Long brokerAccountId, String ticker, Double cashBalance) {
        if (cashBalance == null || cashBalance <= 0) return 0.0;

        List<Position> positions = positionRepository.findByBrokerAccountId(brokerAccountId);
        if (positions.isEmpty()) return 0.0;

        // 모든 보유 ticker 의 lastClose 를 일괄 batch fetch — N+1 회피.
        Set<String> allTickers = positions.stream()
                .map(Position::getTicker)
                .collect(Collectors.toSet());
        Map<String, Double> latestCloses = dailyBarRepository
                .findLatestClosesByTickers(allTickers).stream()
                .filter(t -> t.close() != null && t.close() > 0)
                .collect(Collectors.toMap(TickerLatestClose::ticker, TickerLatestClose::close, (a, b) -> a));

        double totalMarketValue = 0.0;
        double tickerMarketValue = 0.0;
        int fallbackCount = 0;
        for (Position p : positions) {
            // lastClose 없으면 avgPrice fallback (= 매수 기준).
            Double close = latestCloses.get(p.getTicker());
            if (close == null || close <= 0) {
                fallbackCount++;
            }
            double price = (close != null && close > 0) ? close : p.getAvgPrice();
            double v = price * p.getQuantity();
            totalMarketValue += v;
            if (ticker.equals(p.getTicker())) {
                tickerMarketValue = v;
            }
        }

        // 운영 가시성 — fallback 비율 ≥ 50% 이면 sync 누락 의심으로 WARN, 1건이라도 있으면 DEBUG.
        int total = positions.size();
        if (total > 0) {
            double fallbackRatio = (double) fallbackCount / total;
            if (fallbackRatio >= 0.5) {
                log.warn("[PositionService] avgPrice fallback 비율 높음 - brokerAccountId={} fallback={}/{} (DailyBar sync 누락 의심)",
                        brokerAccountId, fallbackCount, total);
            } else if (fallbackCount > 0) {
                log.debug("[PositionService] avgPrice fallback 사용 - brokerAccountId={} fallback={}/{}",
                        brokerAccountId, fallbackCount, total);
            }
        }

        if (tickerMarketValue <= 0) return 0.0;

        double totalAssets = cashBalance + totalMarketValue;
        if (totalAssets <= 0) return 0.0;
        return tickerMarketValue / totalAssets;
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

    /**
     * 활성 BrokerAccount 의 ticker 보유 수량 조회. SignalService 의 SELL 미보유 가드용.
     *
     * <p>미보유면 0 반환 — RuleEngine 이 SELL 결정해도 SignalService 가 HOLD 로 강등하여
     * Trade PENDING/FAILED 라운드트립을 차단한다.
     */
    @Transactional(readOnly = true)
    public int getHoldingQuantity(Long brokerAccountId, String ticker) {
        return positionRepository.findByBrokerAccountIdAndTicker(brokerAccountId, ticker)
                .map(Position::getQuantity)
                .orElse(0);
    }
}
