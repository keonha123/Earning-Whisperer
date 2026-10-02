package com.earningwhisperer.domain.market;

import java.util.Map;

/**
 * 5종 글로벌 시장 지수의 표시 포맷 매핑.
 *
 * 클라이언트는 같은 숫자 필드(price)에 대해 지수형/퍼센트형을 구분 표시해야 하므로
 * 백엔드가 심볼별 format 상수를 함께 내려준다.
 *
 * 표시 대상은 미국 시장 대표 ETF 5종이다. 원지수(SPX/NDX 등)는 유료 데이터라
 * 무료 등급으로 받을 수 없다. SPY 를 10배 해서 SPX 라고 표기하는 식의 환산은 하지
 * 않는다 — 실제 지수값과 다르고, 화면에 지수인 것처럼 뜨면 거짓이 된다.
 * ETF 심볼을 그대로 노출해 무엇을 보고 있는지 분명히 한다.
 *
 * - SPY, QQQ, DIA, IWM, VIXY → "index" (소수점 둘째 자리 가격 표기)
 *
 * 지원 외 심볼 수신 시에는 호출자 측에서 미리 드롭한다.
 */
public final class MarketIndexFormat {

    public static final String INDEX = "index";
    public static final String PERCENT = "percent";

    private static final Map<String, String> FORMAT_BY_SYMBOL = Map.of(
            "SPY", INDEX,
            "QQQ", INDEX,
            "DIA", INDEX,
            "IWM", INDEX,
            "VIXY", INDEX
    );

    private MarketIndexFormat() {
        // 상수 클래스 — 인스턴스화 금지
    }

    /**
     * 지원 심볼 여부.
     * @param symbol 대문자 심볼 (예: "SPY")
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
