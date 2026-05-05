package com.earningwhisperer.domain.portfolio;

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
 * Trading Terminal 의 잔고 sync 결과를 snapshot 으로 보존한다 — 보낸 목록에 없는 ticker 는 삭제,
 * 있는 ticker 는 upsert. 이 데이터는 RuleEngine 의 maxPositionRatio 검증에 사용된다.
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class PositionService {

    private final PositionRepository positionRepository;
    private final UserRepository userRepository;

    @Transactional(readOnly = true)
    public List<Position> getPositions(Long userId) {
        return positionRepository.findByUserId(userId);
    }

    /**
     * Terminal snapshot 동기화 — 보낸 목록을 source of truth 로 받아 upsert + 누락 삭제.
     *
     * <p>fail-safe: 빈/null positions 는 no-op 으로 처리한다. Terminal 의 일시 장애(KIS 타임아웃,
     * 빈 응답 처리 버그) 로 빈 리스트가 도달하면 모든 row 삭제 → currentPositionRatio = 0 →
     * BUY 가드 무력화 위험. 사용자가 진짜 전 종목 매도했다면 다음 신호에서 자동매매가
     * stale position 기준으로 보수적으로 동작 (BUY 차단) → 안전 측 fail.
     *
     * @param userId    대상 사용자 ID
     * @param positions Terminal 이 보낸 보유종목 목록
     * @return upsert 된 row 수 (빈/null 이면 0)
     */
    @Transactional
    public int syncSnapshot(Long userId, List<PortfolioSyncRequest.PositionDto> positions) {
        if (positions == null || positions.isEmpty()) {
            log.info("[PositionService] 빈 snapshot — fail-safe no-op userId={}", userId);
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
            // 모든 dto 가 비정상 (ticker blank 등) — fail-safe 동일 적용 (delete 안 함)
            log.warn("[PositionService] 모든 dto 의 ticker 가 비어있음 — no-op userId={}", userId);
            return 0;
        }
        positionRepository.deleteByUserIdAndTickerNotIn(userId, incomingTickers);

        // 2. 사용자별 기존 row 일괄 조회 후 ticker → entity map
        List<Position> existing = positionRepository.findByUserId(userId);
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
     * RuleEngine 용 ticker 의 매수 기준 비중 계산.
     *
     * <p>currentPositionRatio = (ticker bookValue) / (cashBalance + Σ all bookValues).
     * cashBalance 가 null/0 이면 검증 의미가 약하므로 0 반환 (= BUY 통과).
     * ticker 미보유면 0 반환.
     *
     * <p>실시간 가격이 아닌 매수 평균가 기반이라 보수적 추정치. 가격이 크게 오르면 실제 비중은
     * 더 높을 수 있으며 이는 후속 PR 에서 stocks 의 last close 활용해 보완.
     */
    @Transactional(readOnly = true)
    public double computeBookRatio(Long userId, String ticker, Double cashBalance) {
        if (cashBalance == null || cashBalance <= 0) return 0.0;

        List<Position> positions = positionRepository.findByUserId(userId);
        double totalBookValue = 0.0;
        double tickerBookValue = 0.0;
        for (Position p : positions) {
            double v = p.bookValue();
            totalBookValue += v;
            if (ticker.equals(p.getTicker())) {
                tickerBookValue = v;
            }
        }
        if (tickerBookValue <= 0) return 0.0;

        double totalAssets = cashBalance + totalBookValue;
        if (totalAssets <= 0) return 0.0;
        return tickerBookValue / totalAssets;
    }
}
