package com.earningwhisperer.domain.stock;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.List;

/**
 * Phase 3: 종목 상세 REST 응답 스키마.
 *
 * <p>raw 수치 + 클라이언트 포맷 정책 — i18n + 정밀도 보존을 위해 BigDecimal/long(epoch) 그대로
 * 직렬화한다. 단위 변환·천 단위 구분자·통화 기호는 클라이언트(trading-terminal CompanyDrawer) 책임.
 *
 * <p>nullability:
 * <ul>
 *     <li>{@code basic} — StockMeta 미존재 시 null</li>
 *     <li>{@code currentPrice} — chart30d 비어있을 때 null</li>
 *     <li>{@code chart30d} / {@code earningsHistory} — 항상 List (빈 배열 가능)</li>
 *     <li>{@code nextEarning} — 미래 어닝 캘린더 row 없으면 null</li>
 *     <li>{@code ai} — 본 phase 에서는 항상 null (ai-engine 팀 후속)</li>
 * </ul>
 *
 * <p>{@code partial=true} 의 의미: 일부 데이터가 누락되어 클라이언트가 placeholder UI 를 표시해야 함.
 * 판정 기준은 {@code StockDetailService} 참고.
 */
public record StockDetailResponse(
        String ticker,
        String companyName,
        String sector,
        boolean active,

        BasicInfo basic,
        List<DailyBarPoint> chart30d,
        BigDecimal currentPrice,
        List<EarningsHistoryItem> earningsHistory,
        NextEarning nextEarning,

        boolean partial,
        Object ai
) {
    public record BasicInfo(
            BigDecimal marketCapUsd,
            BigDecimal high52w,
            BigDecimal low52w,
            BigDecimal dividendYield
    ) {}

    public record DailyBarPoint(
            LocalDate date,
            BigDecimal close,
            Long volume
    ) {}

    public record EarningsHistoryItem(
            String fiscalPeriodLabel,
            long announcedAt,
            BigDecimal epsEstimate,
            BigDecimal epsActual,
            BigDecimal surprisePercent,
            BigDecimal priceReactionPercent
    ) {}

    public record NextEarning(
            long scheduledAt,
            BigDecimal epsEstimate,
            BigDecimal revenueEstimate,
            boolean confirmed
    ) {}
}
