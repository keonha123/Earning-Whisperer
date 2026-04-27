import type { ReactNode } from 'react'

interface SecurityBadgeProps {
  icon: ReactNode
  label: ReactNode
}

/**
 * SecurityBadge — Auth 페이지 하단에 정렬되는 보안 안내 배지.
 * 자물쇠/방패/네트워크 아이콘 + 라벨을 한 줄로 표시.
 */
export default function SecurityBadge({ icon, label }: SecurityBadgeProps) {
  return (
    <span
      className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-surface-2 border border-border-strong text-text-tertiary text-xs whitespace-nowrap"
    >
      <span className="text-accent-400 flex items-center" aria-hidden>
        {icon}
      </span>
      {label}
    </span>
  )
}
