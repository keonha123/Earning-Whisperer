import { useEffect, useRef } from 'react'
import type {
  PreviousCall,
  TranscriptDiffChangeType,
  TranscriptDiffItem,
} from '../../store/useTranscriptDiffStore'

/**
 * 변화 유형별 표기.
 *
 * 유형값은 AI Engine 의 5종을 단일 진실 공급원으로 삼되, 라벨은 발표를 보는 사람이
 * 바로 읽을 수 있는 한국어를 쓴다. FactCheckPanel 과 같은 방침이다.
 */
const CHANGE_META: Record<TranscriptDiffChangeType, { label: string; color: string; bg: string }> = {
  improved:   { label: '개선',      color: '#10b981', bg: 'rgba(16,185,129,0.12)'  },
  weakened:   { label: '후퇴',      color: '#ef4444', bg: 'rgba(239,68,68,0.12)'   },
  unchanged:  { label: '변화 없음', color: '#64748b', bg: 'rgba(100,116,139,0.12)' },
  mixed:      { label: '혼재',      color: '#f59e0b', bg: 'rgba(245,158,11,0.12)'  },
  new_claim:  { label: '새 언급',   color: '#3b82f6', bg: 'rgba(59,130,246,0.12)'  },
}

/** 주제 라벨. 엔진의 7축을 한국어로 옮긴다. 목록에 없으면 원값을 그대로 쓴다. */
const TOPIC_LABELS: Record<string, string> = {
  guidance: '가이던스',
  margin: '마진',
  demand: '수요',
  capex: '투자',
  supply: '공급망',
  competition: '경쟁',
  revenue: '매출',
}

interface TranscriptDiffPanelProps {
  /** 도착 순서(= 발언 순서)로 누적된 대조 결과. */
  items: readonly TranscriptDiffItem[]
  /** 비교 대상이 된 직전 콜. 없으면 아직 한 건도 도착하지 않은 상태다. */
  previousCall: PreviousCall | null
}

/**
 * TranscriptDiffPanel — 직전 콜 발언과의 대조 패널.
 *
 * 팩트체크가 <b>뉴스</b>를 근거로 "이 숫자가 맞는가" 를 보는 반면, 이쪽은
 * <b>같은 회사의 직전 콜</b>을 근거로 "지난 분기와 말이 달라졌는가" 를 본다.
 * 개인투자자가 혼자 하기 어려운 쪽은 후자다 — 여러 분기의 콜을 기억해야 하기 때문이다.
 *
 * 도착 빈도가 팩트체크보다 훨씬 낮다. 백엔드가 주제와 무관한 발언을 걸러내므로
 * 대부분의 발언에는 아무것도 오지 않는다. 그래서 "대기 중" 을 길게 띄우지 않는다.
 */
export default function TranscriptDiffPanel({ items, previousCall }: TranscriptDiffPanelProps) {
  const scrollRef = useRef<HTMLDivElement>(null)

  // 새 대조 도착 시 하단으로 스크롤.
  useEffect(() => {
    const el = scrollRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [items.length])

  return (
    <div className="flex flex-col min-h-0 h-full">
      {/* 헤더 */}
      <div className="h-10 px-3.5 flex items-center justify-between border-b border-border-subtle shrink-0 gap-2">
        <span className="text-[11px] font-semibold text-text-secondary uppercase tracking-[0.14em] inline-flex items-center gap-2">
          <span className="w-2 h-2 rounded-sm bg-accent-500 shadow-[0_0_8px_rgba(16,185,129,0.5)]" />
          지난 분기 대비
        </span>
        <span className="num text-[10px] text-text-tertiary tabular-nums">{items.length}건</span>
      </div>

      {/*
        무엇과 비교했는지 밝힌다. 이 줄이 없으면 "지난 분기" 가 어느 콜인지 알 수 없고,
        발표에서 근거를 물었을 때 답할 것이 없다.
      */}
      {previousCall && (
        <div className="px-3.5 py-1.5 border-b border-border-subtle shrink-0 text-[10px] text-text-tertiary leading-snug">
          비교 대상 ·{' '}
          <span className="text-text-secondary">
            {previousCall.fiscalQuarter || previousCall.title || previousCall.documentId}
          </span>
          {previousCall.publishedAt && (
            <span className="num text-text-disabled"> ({previousCall.publishedAt})</span>
          )}
        </div>
      )}

      {/* 카드 목록 */}
      <div
        ref={scrollRef}
        className="flex-1 overflow-y-auto min-h-0 px-2 py-1.5 flex flex-col gap-1.5"
      >
        {items.length === 0 ? (
          <div className="flex-1 flex items-center justify-center text-center px-3 text-[10.5px] text-text-disabled leading-relaxed">
            직전 콜과 달라진 발언이 나오면 표시됩니다.
          </div>
        ) : (
          items.map((item) => {
            const meta = CHANGE_META[item.changeType]
            const topic = TOPIC_LABELS[item.topic] ?? item.topic
            return (
              <div
                key={`${item.sequence}-${item.topic}-${item.changeType}`}
                className="rounded-md border border-border-subtle bg-surface-2 px-2.5 py-2 flex flex-col gap-1.5"
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="inline-flex items-center gap-1.5">
                    <span
                      className="text-[9.5px] font-semibold px-1.5 py-0.5 rounded"
                      style={{ color: meta.color, backgroundColor: meta.bg }}
                    >
                      {meta.label}
                    </span>
                    <span className="text-[10px] text-text-secondary">{topic}</span>
                  </span>
                  <span className="num text-[9.5px] text-text-disabled tabular-nums">
                    {Math.round(item.confidence * 100)}%
                  </span>
                </div>

                <p className="text-[11px] text-text-primary leading-snug">{item.summaryKo}</p>

                {/*
                  직전 발언은 원문 그대로 보여 준다. 요약만 띄우면 근거를 확인할 수 없고,
                  판단이 맞는지 발표 자리에서 검증할 방법이 없어진다.
                */}
                {item.priorClaim && (
                  <div className="border-l-2 border-border-subtle pl-2 flex flex-col gap-0.5">
                    <span className="text-[9px] text-text-disabled uppercase tracking-[0.1em]">
                      직전 콜
                    </span>
                    <p className="text-[10px] text-text-tertiary leading-snug">{item.priorClaim}</p>
                  </div>
                )}
              </div>
            )
          })
        )}
      </div>
    </div>
  )
}
