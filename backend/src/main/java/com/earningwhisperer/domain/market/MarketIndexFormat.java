package com.earningwhisperer.domain.market;

import java.util.Map;

/**
 * 5종 글로벌 시장 지수의 표시 포맷 매핑.
 *
 * 클라이언트는 같은 숫자 필드(price)에 대해 지수형/퍼센트형을 구분 표시해야 하므로
 * 백엔드가 심볼별 format 상수를 함께 내려준다.
 *
 * - SPX, NDX, VIX, DXY → "index" (소수점 둘째 자리, 콤마 구분 등 지수형 표기)
 * - 10Y               → "percent" (%로 표시)
 *
 * 5종 외 심볼 수신 시에는 호출자 측에서 미리 드롭하므로 본 enum은 5종만 매핑한다.
 */
public final class MarketIndexFormat {

    public static final String INDEX = "index";
    public static final String PERCENT = "percent";

    private static final Map<String, String> FORMAT_BY_SYMBOL = Map.of(
            "SPX", INDEX,
            "NDX", INDEX,
            "VIX", INDEX,
            "DXY", INDEX,
            "10Y", PERCENT
    );

    private MarketIndexFormat() {
        // 상수 클래스 — 인스턴스화 금지
    }

    /**
     * 지원 심볼 여부.
     * @param symbol 대문자 심볼 (예: "SPX")
     */
    public static boolean isSupported(String symbol) {
        return FORMAT_BY_SYMBOL.containsKey(symbol);
    }

    /**
     * 심볼별 format 상수.
     * 미지원 심볼은 null 반환 — 호출자가 사전 검증해야 한다.
     */
    public static String of(String symbol) {
        return FORMAT_BY_SYMBOL.get(symbol);
    }
}
