package com.earningwhisperer.presentation.trade;

/**
 * 수동 주문 기록 응답.
 *
 * <p>{@code tradeId} 를 돌려주는 이유: 수동 주문은 자동 경로와 달리 백엔드가 명령을
 * 내리지 않으므로, 이 값이 없으면 터미널이 방금 만든 거래를 식별할 수단이 없다.
 * 지정가 주문이 {@code PENDING} 으로 기록된 뒤 나중에 체결되었을 때
 * {@code POST /trades/{tradeId}/callback} 으로 종결시키려면 반드시 필요하다.
 */
public record ManualTradeResponse(Long tradeId) {
}
