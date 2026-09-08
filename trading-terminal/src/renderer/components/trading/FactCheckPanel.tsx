import { useRef, useState, useEffect } from 'react'
import type { FactCheckItem } from '../../fixtures/factCheck.dev-mock'

/** CHECKING 상태 지속 시간 (ms). 카드 노출 후 이 시간 동안 "분석 중" 표시. */
const ANALYSIS_DELAY_MS = 2500

type Verdict = FactCheckItem['verdict']

const VERDICT_META: Record<Verdict, { label: string; color: string; bg: string }> = {
  CONFIRMED:   { label: '일치',      color: '#10b981', bg: 'rgba(16,185,129,0.12)'  },
  EXAGGERATED: { label: '과장',      color: '#f59e0b', bg: 'rgba(245,158,11,0.12)'  },
  SHIFTED:     { label: '입장 변화', color: '#a78bfa', bg: 'rgba(167,139,250,0.12)' },
  UNVERIFIED:  { label: '미검증',    color: '#64748b', bg: 'rgba(100,116,139,0.12)' },
}

interface FactCheckPanelProps {
  items: readonly FactCheckItem[]
  sttStep: number
}

/**
 * FactCheckPanel — 중앙 하단 어닝콜 실시간 팩트체크 패널.
 *
 * sttStep >= item.triggerStep 인 항목을 순차 노출한다.
 * 처음 노출 후 ANALYSIS_DELAY_MS 동안 "AI 교차 분석 중..." 상태를 표시하고,
 * 이후 검증 결과(verdict·pastReference·delta·confidence)를 표시한다.
 *
 * loopKey 를 컴포넌트 key 로 사용하면 루프 재시작 시 자동 remount 되어
 * revealedAt 상태가 초기화된다.
 */
export default function FactCheckPanel({ items, sttStep }: FactCheckPanelProps) {
  // item.id → 최초 노출 epoch(ms).
  const revealedAt = useRef<Map<string, number>>(new Map())
  // ANALYSIS_DELAY_MS 경과 후 강제 리렌더 트리거.
  const [, rerender] = useState(0)
  const scrollRef = useRef<HTMLDivElement>(null)

  const visible = items.filter((it) => sttStep >= it.triggerStep)

  // 새 카드 등장 시: revealedAt 기록 + ANALYSIS_DELAY 후 리렌더.
  useEffect(() => {
    const now = Date.now()
    let hadNew = false
    visible.forEach((it) => {
      if (!revealedAt.current.has(it.id)) {
        revealedAt.current.set(it.id, now)
        hadNew = true
      }
    })
    if (!hadNew) return
    const t = setTimeout(() => rerender((n) => n + 1), ANALYSIS_DELAY_MS + 50)
    return () => clearTimeout(t)
    // visible.length 변화만 감지하면 충분 — visible 배열 참조 재생성 무시.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visible.length])

  // 새 카드 등장 시 자동 스크롤.
  useEffect(() => {
    const el = scrollRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [visible.length])

  const now = Date.now()

  return (
    <div className="flex-1 flex flex-col min-h-0 border-t border-border-subtle bg-surface-1">
      {/* 헤더 */}
      <div className="h-[34px] px-3.5 flex items-center justify-between border-b border-border-subtle shrink-0 gap-2">
        <span className="text-[10.5px] font-semibold text-text-secondary uppercase tracking-[0.14em] inline-flex items-center gap-2">
          <span className="w-2 h-2 rounded-sm bg-buy shadow-[0_0_8px_rgba(16,185,129,0.5)]" />
          실시간 팩트체크
        </span>
        <span className="num text-[10px] text-text-tertiary tabular-nums">
          {visible.length} / {items.length}
        </span>
      </div>

      {/* 카드 목록 */}
      <div
        ref={scrollRef}
        className="flex-1 overflow-y-auto min-h-0 px-2 py-1.5 flex flex-col gap-1.5"
      >
        {visible.length === 0 ? (
          <div className="flex-1 flex items-center justify-center text-[11px] text-text-disabled">
            발언 분석 대기 중...
          </div>
        ) : (
          visible.map((item) => {
            const at = revealedAt.current.get(item.id) ?? now
            const checking = now - at < ANALYSIS_DELAY_MS
            const v = VERDICT_META[item.verdict]

            if (checking) {
              return (
                <div
                  key={item.id}
                  className="px-2.5 py-2 rounded bg-surface-2 border border-border-subtle animate-pulse"
                >
                  <div className="text-[10.5px] text-text-tertiary leading-snug truncate">
                    {item.claim}
                  </div>
                  <div className="mt-1 text-[10px] text-text-disabled">AI 교차 분석 중...</div>
                </div>
              )
            }

            return (
              <div
                key={item.id}
                className="px-2.5 py-2 rounded bg-surface-2 border border-border-subtle animate-fade-in flex flex-col gap-1"
              >
                {/* 주장 + 판정 뱃지 */}
                <div className="flex items-start gap-1.5">
                  <span className="flex-1 min-w-0 text-[10.5px] text-text-primary leading-snug">
                    {item.claim}
                  </span>
                  <span
                    className="shrink-0 px-1.5 py-px rounded text-[9px] font-bold tracking-[0.06em] border whitespace-nowrap"
                    style={{ color: v.color, background: v.bg, borderColor: `${v.color}55` }}
                  >
                    {v.label}
                  </span>
                </div>

                {/* 과거 레퍼런스 */}
                <div className="text-[10px] text-text-tertiary leading-snug">
                  {item.pastReference}
                </div>

                {/* 교차검증 인사이트 */}
                <div className="text-[10px] leading-snug" style={{ color: v.color }}>
                  → {item.delta}
                </div>

                {/* 신뢰도 바 */}
                <div className="flex items-center gap-1.5 pt-0.5">
                  <div className="flex-1 h-[2px] rounded-full bg-surface-0">
                    <div
                      className="h-full rounded-full"
                      style={{ width: `${item.confidence * 100}%`, background: v.color }}
                    />
                  </div>
                  <span className="num text-[9px] text-text-tertiary">
                    {Math.round(item.confidence * 100)}% 신뢰
                  </span>
                </div>
              </div>
            )
          })
        )}
      </div>
    </div>
  )
}
