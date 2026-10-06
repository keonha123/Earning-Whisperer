/**
 * 콜 화면(#155)의 화면 판단 — 렌더링과 떼어 테스트하는 순수 함수 모음.
 *
 *  - 콜 상태: 시작 전 · 진행 중 · 종료 후 (화면의 주인공이 바뀌는 기준)
 *  - 직전 콜 대조를 발언에 붙이기와 펼칠지 판단
 *  - 주문 수량 한도
 */
import type { TranscriptSegment } from '../store/useTranscriptStore'
import type { TranscriptDiffItem, TranscriptDiffChangeType } from '../store/useTranscriptDiffStore'

export type CallPhase = 'BEFORE' | 'LIVE' | 'ENDED'

/**
 * 콜 상태를 정한다.
 *
 * 자막이 없으면 시작 전이다. 마지막 자막의 callId 가 종료 표시를 받았으면 종료 후, 아니면 진행 중이다.
 * 이번 콜의 종합 판단이 도착했으면 종료 표시를 놓쳤어도 종료 후로 본다 — 판단은 콜이 끝나야 만들어진다.
 * 판단의 callId 가 마지막 자막과 다르면 지난 회차 판단이라 상태를 정하는 데 쓰지 않는다.
 * 지난 회차 판단이 늦게 도착해 진행 중인 새 콜을 종료 후로 덮는 일을 막기 위해서다.
 */
export function deriveCallPhase(
  segments: readonly TranscriptSegment[],
  endedCallIds: ReadonlySet<string>,
  summaryCallId: string | null | undefined,
): CallPhase {
  const hasSummary = summaryCallId !== undefined
  if (segments.length === 0) return hasSummary ? 'ENDED' : 'BEFORE'
  const lastCallId = segments[segments.length - 1].callId
  if (endedCallIds.has(lastCallId)) return 'ENDED'
  // callId 가 없는 판단은 어느 회차인지 알 수 없어 지금 콜의 것으로 본다(옛 계약과 호환).
  if (hasSummary && (summaryCallId === null || summaryCallId === lastCallId)) return 'ENDED'
  return 'LIVE'
}

/**
 * 화면에 보일 자막 — 가장 최근 콜(callId)의 것만.
 *
 * 같은 종목을 다시 재생하면 store 에 지난 회차 자막이 남아 있다. 두 회차가 섞이면 발언 번호가
 * 겹쳐 대조가 엉뚱한 발언에 붙는다.
 */
export function currentCallSegments(segments: readonly TranscriptSegment[]): readonly TranscriptSegment[] {
  if (segments.length === 0) return segments
  const lastCallId = segments[segments.length - 1].callId
  if (segments[0].callId === lastCallId) return segments
  return segments.filter((s) => s.callId === lastCallId)
}

/** 대조 항목을 펼친 카드로 보여 주는 위험 점수 기준. ai-engine analysis_guard 의 risk_threshold 와 같다. */
export const PROMINENT_RISK_THRESHOLD = 0.7

/** `후퇴` 이거나 위험 점수가 높은 항목은 칩이 아니라 펼친 카드로 보인다 (design-system 직전 콜 대조). */
export function isProminentDiff(item: TranscriptDiffItem): boolean {
  return item.changeType === 'weakened' || item.riskScore >= PROMINENT_RISK_THRESHOLD
}

/** 발언 번호 → 그 발언에 붙는 대조 항목. 도착 순서를 지킨다. */
export function groupDiffsBySequence(
  items: readonly TranscriptDiffItem[],
): ReadonlyMap<number, readonly TranscriptDiffItem[]> {
  const map = new Map<number, TranscriptDiffItem[]>()
  for (const item of items) {
    const list = map.get(item.sequence)
    if (list) list.push(item)
    else map.set(item.sequence, [item])
  }
  return map
}

/** 변화 유형별 개수. 집계 줄과 종료 후 요약에 쓴다. */
export function countDiffsByType(
  items: readonly TranscriptDiffItem[],
): Record<TranscriptDiffChangeType, number> {
  const counts: Record<TranscriptDiffChangeType, number> = {
    improved: 0,
    weakened: 0,
    unchanged: 0,
    mixed: 0,
    new_claim: 0,
  }
  for (const item of items) counts[item.changeType] += 1
  return counts
}

/**
 * 주문 수량 한도.
 *
 * 매수는 예수금 ÷ 실제 주문 단가(즉시 체결이면 버퍼가 얹힌 가격), 매도는 보유 수량이다.
 * 기준을 모르면(가격 없음 · 잔고 미조회) null — 0 으로 두면 "살 수 없다" 로 읽힌다.
 */
export function maxOrderQty(params: {
  side: 'BUY' | 'SELL'
  unitPrice: number | null
  orderableCash: number
  heldQty: number | null
}): number | null {
  if (params.side === 'SELL') return params.heldQty
  if (params.unitPrice == null || !Number.isFinite(params.unitPrice) || params.unitPrice <= 0) return null
  if (!Number.isFinite(params.orderableCash) || params.orderableCash <= 0) return 0
  return Math.floor(params.orderableCash / params.unitPrice)
}

/** ms → "mm:ss", 한 시간을 넘으면 "h:mm:ss". 콜 시작 기준 경과 시간에 쓴다. */
export function formatCallClock(ms: number): string {
  if (!Number.isFinite(ms) || ms < 0) return '00:00'
  const total = Math.floor(ms / 1000)
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const s = total % 60
  const mm = String(m).padStart(2, '0')
  const ss = String(s).padStart(2, '0')
  return h > 0 ? `${h}:${mm}:${ss}` : `${mm}:${ss}`
}

/**
 * 콜 시작까지 남은 시간. 일정이 지났으면 null — "곧 시작" 처럼 지어낸 상태를 보이지 않고
 * 호출 측이 "예정 시각이 지났습니다" 로 알린다.
 */
export function countdownParts(
  scheduledAtSec: number,
  nowMs: number,
): { days: number; hours: number; minutes: number; seconds: number } | null {
  const diff = scheduledAtSec * 1000 - nowMs
  if (!Number.isFinite(diff) || diff <= 0) return null
  const total = Math.floor(diff / 1000)
  return {
    days: Math.floor(total / 86400),
    hours: Math.floor((total % 86400) / 3600),
    minutes: Math.floor((total % 3600) / 60),
    seconds: total % 60,
  }
}

/**
 * 번역 문단을 붙일 자리 — 문단에 담긴 마지막 원문 발언 번호 → 문단.
 *
 * 번역은 원문 몇 개를 묶어 몇 초 늦게 오므로, 묶음의 마지막 발언 아래에 붙여야 원문과 순서가 맞다.
 * 지금 콜(callId)의 번역만 남긴다 — 다시 재생하면 지난 회차 번역이 발언 번호가 겹친 채 남아 있다.
 */
export function translationsByLastSequence<T extends { callId: string; sequences: readonly number[] }>(
  items: readonly T[],
  callId: string | null,
): ReadonlyMap<number, T> {
  const map = new Map<number, T>()
  if (callId == null) return map
  for (const item of items) {
    if (item.callId !== callId || item.sequences.length === 0) continue
    // sequences 는 store 가 오름차순으로 맞춰 둔다
    map.set(item.sequences[item.sequences.length - 1], item)
  }
  return map
}
