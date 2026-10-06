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
 * KisStatusTimeline — KIS 연동 3-step 수직 타임라인.
 * 각 스텝은 22×22 원형 아이콘 + 점선 연결자 + 본문 (제목 + 모노스페이스 메타).
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
      bg: 'rgba(var(--caution-rgb),0.12)',
      border: 'rgba(var(--caution-rgb),0.35)',
      color: 'var(--caution)',
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
            borderLeft: '1px dashed #35363b',
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
        <span className="text-text-primary text-base font-medium">{step.title}</span>
        <span className="text-text-tertiary font-mono text-sm tracking-wide">
          {step.sub}
        </span>
      </div>
    </div>
  )
}
