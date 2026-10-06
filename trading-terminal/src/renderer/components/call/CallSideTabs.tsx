import { useMemo, type ReactNode } from 'react'
import SegmentedControl from '../common/SegmentedControl'
import { EmptyState } from '../common/StateView'
import type { TranscriptDiffItem } from '../../store/useTranscriptDiffStore'
import { countDiffsByType } from '../../lib/callScreen'
import { CHANGE_META, CHANGE_ORDER, topicLabel } from './diffMeta'
import ScrollEdge from './ScrollEdge'

export type SideTab = 'diff' | 'ask' | 'price'

const TABS: { id: SideTab; label: string }[] = [
  { id: 'diff', label: '대조' },
  { id: 'ask', label: '질문' },
  { id: 'price', label: '가격' },
]

interface CallSideTabsProps {
  diffItems: readonly TranscriptDiffItem[]
  /** 대조 목록에서 항목을 누르면 그 발언으로 자막을 옮긴다. */
  onFocusSequence: (sequence: number) => void
  /** 가격 탭 내용 — 시작 전 옆 자리와 같은 카드를 쓴다. */
  price: ReactNode
  /** 질문 탭 내용 — 질의응답 패널. */
  ask: ReactNode
  /** 자막에서 '이 대목 질문' 을 누르면 질문 탭으로 옮겨야 해서 탭은 화면이 쥔다. */
  tab: SideTab
  onTabChange: (tab: SideTab) => void
  topInset: number
}

/**
 * 콜 진행 중의 옆 자리 — 대조 · 질문 · 가격 탭 (docs/design/ux.md 콜 시청).
 *
 *  - 대조: 변화 유형별 집계와 목록. 누르면 해당 발언으로 이동한다. 발언 아래 붙은 대조의 색인 역할이다.
 *  - 질문: 콜 전체나 고른 발언에 대해 묻는 질의응답(#112).
 *  - 가격: 가격 · 보유는 콜 중에는 보조 정보라 탭 하나로 내린다.
 */
export default function CallSideTabs({ diffItems, onFocusSequence, price, ask, tab, onTabChange, topInset }: CallSideTabsProps) {
  const counts = useMemo(() => countDiffsByType(diffItems), [diffItems])
  // 발언 순서대로. 도착 순서로 두면 자막과 순서가 어긋난다.
  const ordered = useMemo(() => [...diffItems].sort((a, b) => a.sequence - b.sequence), [diffItems])

  return (
    <section className="frost relative h-full rounded-[28px] overflow-hidden flex flex-col" style={{ paddingTop: topInset }}>
      <ScrollEdge height={topInset + 12} />
      <div className="px-5 pt-4 pb-3 shrink-0">
        <SegmentedControl items={TABS} activeId={tab} onChange={onTabChange} />
      </div>

      {/* 질문 탭은 대화 목록과 입력칸이 각자 자리를 나눠 써서 바깥 스크롤을 두지 않는다 */}
      {tab === 'ask' && <div className="flex-1 min-h-0 px-5 pb-5 flex flex-col">{ask}</div>}

      <div className={`flex-1 min-h-0 overflow-y-auto px-5 pb-6 ${tab === 'ask' ? 'hidden' : ''}`}>
        {tab === 'diff' && (
          <div className="flex flex-col gap-4">
            <div className="flex flex-wrap gap-x-4 gap-y-1.5 text-[13px]" aria-label="변화 유형별 개수">
              {CHANGE_ORDER.map((type) => (
                <span key={type} className="inline-flex items-baseline gap-1.5">
                  <span style={{ color: CHANGE_META[type].color }}>
                    {CHANGE_META[type].symbol} {CHANGE_META[type].label}
                  </span>
                  <span className="tabular-nums text-ink-2">{counts[type]}</span>
                </span>
              ))}
            </div>

            {ordered.length === 0 ? (
              <EmptyState message="직전 콜과 견줄 만한 발언이 나오면 여기에 쌓입니다. 주제와 무관한 발언에는 붙지 않습니다." />
            ) : (
              <ul className="flex flex-col gap-1">
                {ordered.map((item, i) => {
                  const meta = CHANGE_META[item.changeType]
                  return (
                    <li key={`${item.sequence}-${item.topic}-${i}`}>
                      <button
                        type="button"
                        onClick={() => onFocusSequence(item.sequence)}
                        className="w-full text-left rounded-[14px] px-3 py-2 hover:bg-white/[0.05] flex flex-col gap-0.5"
                      >
                        <span className="text-[12.5px] font-semibold" style={{ color: meta.color }}>
                          {meta.symbol} {meta.label} · <span className="text-ink-2 font-medium">{topicLabel(item.topic)}</span>
                        </span>
                        <span className="text-[12.5px] text-ink-2 leading-snug line-clamp-2">{item.summaryKo}</span>
                      </button>
                    </li>
                  )
                })}
              </ul>
            )}
          </div>
        )}

        {tab === 'price' && price}
      </div>
    </section>
  )
}
