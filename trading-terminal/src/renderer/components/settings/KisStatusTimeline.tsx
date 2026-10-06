import type { ReactNode } from 'react'

export type KisTimelineStatus = 'done' | 'pending' | 'error'

export interface KisTimelineStep {
  id: string
  title: string
  /** 서브 라인. ReactNode 로 받아 <b> 강조 등 마크업 가능 */
  sub: ReactNode
  status: KisTimelineStatus
}

interface KisStatusTimelineProps {
  steps: readonly KisTimelineStep[]
}

/**
 * KisStatusTimeline — KIS 연동 3단계 세로 타임라인.
 * 각 단계는 22×22 원형 아이콘 + 점선 연결자 + 본문(제목 + 설명)이다.
 * 아이콘 색은 상태색(ok · danger)만 쓰고, 아직 안 된 단계는 흐린 글자색으로 둔다.
 */
export default function KisStatusTimeline({ steps }: KisStatusTimelineProps) {
  return (
    <div className="flex flex-col py-1">
      {steps.map((step, idx) => (
        <TimelineStep key={step.id} step={step} isFirst={idx === 0} />
      ))}
    </div>
  )
}

function TimelineStep({
  step,
  isFirst,
}: {
  step: KisTimelineStep
  isFirst: boolean
}) {
  const iconStyles = {
    done: {
      bg: 'rgba(var(--ok-rgb),0.12)',
      border: 'rgba(var(--ok-rgb),0.35)',
      color: 'var(--ok)',
    },
    pending: {
      bg: 'transparent',
      border: 'var(--line-strong)',
      color: 'var(--ink-4)',
    },
    error: {
      bg: 'rgba(var(--danger-rgb),0.12)',
      border: 'rgba(var(--danger-rgb),0.35)',
      color: 'var(--danger)',
    },
  }[step.status]

  return (
    <div
      className="grid gap-3 items-start relative py-1.5"
      style={{ gridTemplateColumns: '32px 1fr' }}
    >
      {/* 점선 연결자 (첫 스텝 제외) */}
      {!isFirst && (
        <span
          className="absolute pointer-events-none"
          style={{
            left: '15px',
            top: '-6px',
            height: '12px',
            borderLeft: '1px dashed var(--line-strong)',
          }}
          aria-hidden
        />
      )}
      <div
        className="w-[22px] h-[22px] rounded-full grid place-items-center mx-[5px] my-0.5 relative z-[1]"
        style={{
          background: iconStyles.bg,
          border: `1px solid ${iconStyles.border}`,
          color: iconStyles.color,
        }}
        aria-hidden
      >
        {step.status === 'done' ? (
          <svg
            viewBox="0 0 12 12"
            width="10"
            height="10"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
          >
            <path d="M2.5 6l2.5 2.5L9.5 3.5" />
          </svg>
        ) : step.status === 'error' ? (
          <svg
            viewBox="0 0 12 12"
            width="10"
            height="10"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
          >
            <path d="M3 3l6 6M9 3l-6 6" />
          </svg>
        ) : (
          <span className="w-1.5 h-1.5 rounded-full bg-current" />
        )}
      </div>
      <div className="flex flex-col gap-0.5 py-px">
        <span className="text-ink-1 text-[14px] font-medium">{step.title}</span>
        <span className="text-ink-3 text-[12.5px] leading-snug">{step.sub}</span>
      </div>
    </div>
  )
}
