/**
 * 화면 공통 상태 패턴 (docs/design/design-system.md "상태 패턴").
 *
 *  - LoadingBlock : 불러오는 중. 자리와 크기를 미리 잡은 흐린 막대로 레이아웃이 밀리지 않게 한다.
 *  - EmptyState   : 데이터 없음. 무엇이 없는지와 언제 생기는지를 한 문장으로 쓴다.
 *  - ComingSoon   : 아직 없는 기능. 자리를 두고 흐리게 둔다.
 *  - 실패(마지막 값 유지)는 StaleDataOverlay 가 맡는다.
 */
import type { ReactNode } from 'react'

interface LoadingBlockProps {
  /** 막대 줄 수. 실제 내용의 줄 수에 맞춘다. */
  lines?: number
  /** 한 줄 높이(px). */
  lineHeight?: number
  className?: string
}

export function LoadingBlock({ lines = 3, lineHeight = 14, className = '' }: LoadingBlockProps) {
  return (
    <div className={`flex flex-col gap-2.5 ${className}`} role="status" aria-label="불러오는 중">
      {Array.from({ length: lines }, (_, i) => (
        <div
          key={i}
          className="skeleton"
          // 마지막 줄을 짧게 두어 글 단락처럼 보이게 한다
          style={{ height: lineHeight, width: i === lines - 1 && lines > 1 ? '62%' : '100%' }}
        />
      ))}
    </div>
  )
}

interface EmptyStateProps {
  /** 무엇이 없는지 + 언제 생기는지, 한 문장. */
  message: string
  /** 다음 행동 하나 (보통 맑은 유리 보조 버튼). */
  action?: ReactNode
  className?: string
}

export function EmptyState({ message, action, className = '' }: EmptyStateProps) {
  return (
    <div className={`flex flex-col items-center justify-center gap-3 py-10 text-center ${className}`}>
      <p className="text-ink-3 text-[13px] leading-relaxed max-w-[36ch]">{message}</p>
      {action}
    </div>
  )
}

interface ComingSoonProps {
  /** 이 자리에 들어올 기능 이름. */
  title: string
  /** 언제 · 어디서 다루는지 한 줄 (선택). */
  note?: string
  className?: string
}

export function ComingSoon({ title, note, className = '' }: ComingSoonProps) {
  return (
    <div
      className={`flex flex-col items-center justify-center gap-1.5 py-10 text-center rounded-[20px]
                  border border-dashed border-border-strong opacity-70 ${className}`}
      aria-disabled="true"
    >
      <span className="text-ink-2 text-[14px] font-semibold">{title}</span>
      <span className="text-ink-3 text-[12px]">{note ?? '준비 중입니다'}</span>
    </div>
  )
}
