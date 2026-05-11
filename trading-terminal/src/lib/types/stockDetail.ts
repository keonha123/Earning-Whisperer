/**
 * 종목 상세 응답 타입 — main + renderer 공용 단일 정의.
 *
 * 이전 위치: `src/main/services/BackendClient.ts` (Phase 4 까지).
 * Phase 5 에서 renderer 도 동일 타입을 IPC 응답으로 받기 시작 →
 * 양쪽이 같은 정의를 import 하도록 `src/lib/types/` 로 이동.
 *
 * 주의 — BigDecimal 직렬화 정밀도:
 *   marketCapUsd / revenueEstimate 는 백엔드에서 BigDecimal 으로 다뤄지지만 JSON 직렬화 시
 *   숫자 리터럴로 내려옴. 현재 데이터 범위 (4조달러 ≈ 4e12, Number.MAX_SAFE_INTEGER ≈ 9e15)
 *   에서는 안전. 시가총액이 9 quadrillion 을 넘는 종목이 등장하면 정밀도 손실 가능 →
 *   string 로 받도록 백엔드 + 클라이언트 동시 변경 필요. 본 PR 에서는 number 유지.
 *   dividendYield 는 소수 (예: 0.0049 = 0.49%) — 표시 시 *100 처리 책임은 renderer.
 *
 * ai 필드는 본 phase 시점 항상 null (별도 비동기 채널 — ai-engine 팀 후속).
 */
export interface StockDetailResponsePayload {
  ticker: string
  companyName: string
  sector: string | null
  /** S&P 500 편입 여부. false 면 어닝 분석 섹션 placeholder 처리. */
  active: boolean
  basic: {
    marketCapUsd: number | null
    high52w: number | null
    low52w: number | null
    /** 소수 (0.0049 = 0.49%). renderer 가 *100 후 표시. */
    dividendYield: number | null
  } | null
  chart30d: { date: string; close: number; volume: number | null }[]
  currentPrice: number | null
  earningsHistory: {
    fiscalPeriodLabel: string
    /** epoch second. */
    announcedAt: number
    epsEstimate: number | null
    epsActual: number | null
    /** 백엔드가 이미 % 단위로 보냄 (0.49 → 0.49%, *100 안 함). */
    surprisePercent: number | null
    /** 백엔드가 이미 % 단위로 보냄. */
    priceReactionPercent: number | null
  }[]
  nextEarning: {
    /** epoch second. */
    scheduledAt: number
    epsEstimate: number | null
    revenueEstimate: number | null
    confirmed: boolean
  } | null
  /** lazy fetch 일부 단계 실패 — main 캐시 TTL 5s 로 짧게. */
  partial: boolean
  ai: null
}
