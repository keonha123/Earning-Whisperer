import { useEffect, useRef, type ReactNode } from 'react'

interface SidePanelProps {
  open: boolean
  onClose: () => void
  /** 패널 너비 (px). 기본 400px (디자인 매칭). */
  width?: number
  /** 오버레이 클릭 시 닫기 (기본 true). */
  closeOnOverlay?: boolean
  /** ESC 닫기 (기본 true). */
  closeOnEsc?: boolean
  ariaLabel?: string
  children: ReactNode
}

/**
 * SidePanel — 우측 슬라이드 컨테이너 (CompanyDrawer 본체).
 *
 * 디자인 매칭: CompanyDrawer.html `.drawer` + `.overlay`.
 *  - 오버레이: bg-bg-base/55 + 1.5px blur (CompanyDrawer.html 기준).
 *  - 패널: surface-0 배경 + border-strong 좌측 보더 + shadow.
 *  - 애니메이션: 220ms ease-out translate(40px → 0) + opacity (0.2 → 1).
 *
 * a11y:
 *  - role="dialog" + aria-modal=true.
 *  - ESC 닫기 + 오버레이 클릭 닫기 (옵션).
 *  - body scroll lock (open 상태에서만).
 *  - 간단한 focus trap: 패널 내부 첫 focusable 요소로 자동 포커스 이동.
 *    (전체 trap 은 의존성 추가 없이 가벼운 구현. 외부 포커스 차단은 inert 폴리필 필요.)
 *
 * NOTE: prefers-reduced-motion 사용자에 대해서는 transition 없이 즉시 표시 (CSS).
 */
export default function SidePanel({
  open,
  onClose,
  width = 400,
  closeOnOverlay = true,
  closeOnEsc = true,
  ariaLabel,
  children,
}: SidePanelProps) {
  const panelRef = useRef<HTMLElement>(null)
  const lastFocusRef = useRef<HTMLElement | null>(null)

  // ESC 닫기 + 자동 포커스
  useEffect(() => {
    if (!open) return

    lastFocusRef.current = document.activeElement as HTMLElement | null

    const onKey = (e: KeyboardEvent) => {
      if (closeOnEsc && e.key === 'Escape') {
        e.preventDefault()
        onClose()
      }
    }
    document.addEventListener('keydown', onKey)

    // body scroll lock
    const prevOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'

    // 첫 focusable 자동 포커스
    const focusable = panelRef.current?.querySelector<HTMLElement>(
      'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
    )
    focusable?.focus()

    return () => {
      document.removeEventListener('keydown', onKey)
      document.body.style.overflow = prevOverflow
      // 닫힌 후 포커스 복원
      lastFocusRef.current?.focus?.()
    }
  }, [open, closeOnEsc, onClose])

  if (!open) return null

  return (
    <div
      className="fixed inset-0 z-[300] animate-fade-in"
      // 오버레이는 portal 없이 fixed 로 충분 (App 루트에서 렌더되는 한 stacking context 충돌 없음).
    >
      <div
        aria-hidden="true"
        onClick={() => closeOnOverlay && onClose()}
        className="absolute inset-0 bg-bg-base/55"
        style={{ backdropFilter: 'blur(1.5px) brightness(0.85)' }}
      />
      <aside
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-label={ariaLabel}
        style={{
          width,
          animation: 'sidepanel-slide-in 220ms ease-out',
        }}
        className="absolute top-0 right-0 bottom-0 bg-surface-0 border-l border-border-strong
                   flex flex-col shadow-[-12px_0_48px_rgba(0,0,0,0.6)]"
      >
        {children}
      </aside>
      <style>{`
        @keyframes sidepanel-slide-in {
          from { transform: translateX(40px); opacity: 0.2; }
          to   { transform: translateX(0);    opacity: 1; }
        }
        @media (prefers-reduced-motion: reduce) {
          aside { animation: none !important; }
        }
      `}</style>
    </div>
  )
}
