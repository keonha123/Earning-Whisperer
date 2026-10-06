import type { TranscriptDiffChangeType } from '../../store/useTranscriptDiffStore'

/**
 * 직전 콜 대조의 변화 유형 표기 (docs/design/design-system.md 직전 콜 대조).
 *
 * 색만으로 구분하지 않고 기호와 문구를 늘 함께 둔다. 포르피라와 상승 빨강은 색각 이상이 있으면
 * 비슷하게 보일 수 있다.
 */
export const CHANGE_META: Record<
  TranscriptDiffChangeType,
  { label: string; symbol: string; color: string }
> = {
  improved: { label: '개선', symbol: '+', color: 'rgb(var(--olive))' },
  weakened: { label: '후퇴', symbol: '−', color: 'rgb(var(--porphyra))' },
  mixed: { label: '혼재', symbol: '±', color: 'var(--ink-2)' },
  unchanged: { label: '변화 없음', symbol: '=', color: 'var(--ink-3)' },
  new_claim: { label: '새 언급', symbol: '∗', color: 'var(--ink-3)' },
}

/** 집계 줄의 순서 — 먼저 봐야 하는 것부터. */
export const CHANGE_ORDER: readonly TranscriptDiffChangeType[] = [
  'weakened',
  'improved',
  'mixed',
  'new_claim',
  'unchanged',
]

/** 주제 라벨. 엔진의 7축을 한국어로 옮긴다. 목록에 없으면 원값을 그대로 쓴다. */
export const TOPIC_LABELS: Record<string, string> = {
  guidance: '가이던스',
  margin: '마진',
  demand: '수요',
  capex: '투자',
  supply: '공급망',
  competition: '경쟁',
  revenue: '매출',
}

export function topicLabel(topic: string): string {
  return TOPIC_LABELS[topic] ?? topic
}
