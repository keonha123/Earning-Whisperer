import { useEffect, useRef, type ReactNode } from 'react'

interface ModalProps {
  open: boolean
  onClose: () => void
  /** ESC 닫기 (기본 true). */
  closeOnEsc?: boolean
  /** 오버레이 클릭 시 닫기 (기본 true). */
  closeOnOverlay?: boolean
  ariaLabel?: string
  children: ReactNode
}

/**
 * Modal — 화면 중앙 오버레이 모달.
 *
 * SidePanel 과 동일한 오버레이/ESC/스크롤락/포커스 패턴을 공유하되
 * 패널 대신 중앙 카드로 표시한다.
 *
 * a11y: role="dialog" + aria-modal + ESC + 오버레이 클릭 닫기.
 */
export default function Modal({
  open,
  onClose,
  closeOnEsc = true,
  closeOnOverlay = true,
  ariaLabel,
  children,
}: ModalProps) {
  const dialogRef = useRef<HTMLDivElement>(null)
  const lastFocusRef = useRef<HTMLElement | null>(null)

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

    const prevOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'

    const focusable = dialogRef.current?.querySelector<HTMLElement>(
      'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
    )
    focusable?.focus()

    return () => {
      document.removeEventListener('keydown', onKey)
      document.body.style.overflow = prevOverflow
      lastFocusRef.current?.focus?.()
    }
  }, [open, closeOnEsc, onClose])

  if (!open) return null

  return (
    <div className="fixed inset-0 z-[300] flex items-center justify-center animate-fade-in">
      <div
        aria-hidden="true"
        onClick={() => closeOnOverlay && onClose()}
        className="absolute inset-0 bg-bg-base/50"
        style={{ backdropFilter: 'blur(6px) brightness(0.85)' }}
      />
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-label={ariaLabel}
        // 대화상자는 읽을 내용이 있어 서리 유리 + 금테로 둔다
        className="frost rim rim-float relative z-10 rounded-[30px]
                   shadow-[0_24px_60px_-16px_rgba(0,0,0,0.7)] flex flex-col"
        style={{ animation: 'modal-pop-in 380ms cubic-bezier(0.3, 1.35, 0.5, 1)' }}
      >
        {children}
      </div>
      <style>{`
        @keyframes modal-pop-in {
          from { transform: scale(0.96) translateY(8px); opacity: 0.2; }
          to   { transform: scale(1)    translateY(0);   opacity: 1; }
        }
        @media (prefers-reduced-motion: reduce) {
          [role="dialog"] { animation: none !important; }
        }
      `}</style>
    </div>
  )
}
