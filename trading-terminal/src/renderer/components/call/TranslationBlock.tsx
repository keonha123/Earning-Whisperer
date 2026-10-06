import { memo, useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import type { HighlightedTranslation } from '../../hooks/useTranscriptTranslation'
import type { TermSpan } from '../../lib/glossaryHighlight'

interface TranslationBlockProps {
  item: HighlightedTranslation
  compact?: boolean
}

/**
 * 번역 문단 — 원문 묶음의 마지막 발언 아래에 붙는다 (docs/design/screens/call.md 자막).
 *
 * 번역문 안의 전문용어는 점선 밑줄로 긋고, 누르면 초보 투자자용 쉬운 설명을 팝오버로 보여 준다. 사전은 미리 받아 두어
 * 누를 때 네트워크 요청이 없다. 같은 문단은 같은 객체로 오므로 memo 로 새 번역이 올 때 그 문단만 다시 그린다.
 */
function TranslationBlock({ item, compact = false }: TranslationBlockProps) {
  const [openSpan, setOpenSpan] = useState<{ span: TermSpan; anchor: HTMLElement } | null>(null)
  const popoverId = useId()
  const close = useCallback(() => setOpenSpan(null), [])
  // 같은 용어를 다시 누르면 닫는다
  const toggle = useCallback((span: TermSpan, anchor: HTMLElement) => {
    setOpenSpan((cur) => (cur?.anchor === anchor ? null : { span, anchor }))
  }, [])

  return (
    <div className={`border-l-2 border-white/15 ${compact ? 'pl-3' : 'pl-4'} flex flex-col gap-1`}>
      <span className="text-[11px] text-ink-3">번역</span>
      <p className={`select-text leading-[1.7] text-ink-1 ${compact ? 'text-[13px]' : 'text-[14.5px]'}`}>
        {renderWithTerms(item, openSpan?.span ?? null, popoverId, toggle)}
      </p>
      {openSpan && <TermPopover id={popoverId} span={openSpan.span} anchor={openSpan.anchor} onClose={close} />}
    </div>
  )
}

export default memo(TranslationBlock)

/** spans 로 번역문을 잘라 용어만 버튼으로 바꾼다. 번역문은 외부 데이터라 innerHTML 을 쓰지 않는다. */
function renderWithTerms(
  item: HighlightedTranslation,
  openSpan: TermSpan | null,
  popoverId: string,
  onToggle: (span: TermSpan, anchor: HTMLElement) => void,
) {
  const out: React.ReactNode[] = []
  let cursor = 0
  item.spans.forEach((span, i) => {
    // 겹치거나 범위를 벗어난 위치는 밑줄 없이 둔다
    if (span.start < cursor || span.end > item.textKo.length || span.end <= span.start) return
    if (span.start > cursor) out.push(item.textKo.slice(cursor, span.start))
    out.push(
      <button
        key={`${span.start}-${i}`}
        type="button"
        onClick={(e) => onToggle(span, e.currentTarget)}
        className="inline underline decoration-dotted decoration-ink-3 underline-offset-[5px] decoration-1
                   hover:decoration-ink-1 hover:text-ink-1 rounded-[4px]
                   focus-visible:outline focus-visible:outline-1 focus-visible:outline-gold"
        aria-haspopup="dialog"
        aria-expanded={openSpan === span}
        aria-controls={openSpan === span ? popoverId : undefined}
        aria-label={`${item.textKo.slice(span.start, span.end)} — 용어 설명 보기`}
      >
        {item.textKo.slice(span.start, span.end)}
      </button>,
    )
    cursor = span.end
  })
  if (cursor < item.textKo.length) out.push(item.textKo.slice(cursor))
  return out
}

const POPOVER_WIDTH = 320

/**
 * 용어 설명 팝오버. 화면 기준(fixed)으로 용어 아래에 띄우고 창 밖으로 나가지 않게 맞춘다.
 * 자막 면의 backdrop-filter 가 fixed 의 기준을 바꾸므로 body 로 portal 한다.
 *
 * 라이브 중에는 새 발언이 올 때마다 자막이 저절로 내려가므로, 스크롤 · 창 크기 변경에는 닫지 않고 용어를
 * 따라 자리를 다시 잡는다. 용어가 자막 면 밖으로 나가면 닫는다. Esc · 바깥 클릭 · 포커스가 밖으로 나가면 닫힌다.
 */
function TermPopover({
  id,
  span,
  anchor,
  onClose,
}: {
  id: string
  span: TermSpan
  anchor: HTMLElement
  onClose: () => void
}) {
  const ref = useRef<HTMLDivElement>(null)
  const [pos, setPos] = useState<{ left: number; top: number } | null>(null)

  const place = useCallback(() => {
    if (!anchor.isConnected) return onClose()
    const r = anchor.getBoundingClientRect()
    // 용어가 보이는 자막 영역(스크롤 부모) 밖으로 나가면 가리킬 대상이 없다
    const scroller = anchor.closest('.overflow-y-auto')
    const box = scroller?.getBoundingClientRect()
    if (box && (r.bottom < box.top || r.top > box.bottom)) return onClose()
    const h = ref.current?.offsetHeight ?? 0
    const left = Math.min(Math.max(12, r.left), window.innerWidth - POPOVER_WIDTH - 12)
    // 아래 공간이 모자라면 위로 띄운다
    const below = r.bottom + 8
    const top = below + h > window.innerHeight - 12 ? Math.max(12, r.top - 8 - h) : below
    setPos({ left, top })
  }, [anchor, onClose])

  useLayoutEffect(place, [place])

  // 열릴 때 한 번만 포커스를 옮긴다
  useEffect(() => {
    ref.current?.focus()
  }, [])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopPropagation()
        onClose()
        anchor.focus()
      }
    }
    const onDown = (e: PointerEvent) => {
      if (ref.current?.contains(e.target as Node) || anchor.contains(e.target as Node)) return
      onClose()
    }
    document.addEventListener('keydown', onKey, true)
    document.addEventListener('pointerdown', onDown)
    document.addEventListener('scroll', place, true)
    window.addEventListener('resize', place)
    return () => {
      document.removeEventListener('keydown', onKey, true)
      document.removeEventListener('pointerdown', onDown)
      document.removeEventListener('scroll', place, true)
      window.removeEventListener('resize', place)
    }
  }, [anchor, onClose, place])

  const { term } = span
  return createPortal(
    <div
      ref={ref}
      id={id}
      role="dialog"
      onBlur={(e) => {
        const next = e.relatedTarget as Node | null
        if (next && (e.currentTarget.contains(next) || anchor.contains(next))) return
        onClose()
      }}
      aria-label={`${term.ko} 용어 설명`}
      tabIndex={-1}
      className="frost rim fixed z-[400] rounded-[20px] px-5 py-4 flex flex-col gap-3 outline-none"
      // 글자 위에 뜨는 작은 판이라 서리 유리보다 짙게 깐다 — 뒤 자막이 비치면 설명을 읽기 어렵다
      style={{ width: POPOVER_WIDTH, left: pos?.left ?? -9999, top: pos?.top ?? -9999, background: 'rgba(18, 19, 22, 0.92)' }}
    >
      <div className="flex items-baseline gap-2 flex-wrap">
        <span className="text-[15px] font-semibold text-ink-1">{term.ko}</span>
        <span className="text-[12px] text-ink-3">{term.term}</span>
      </div>
      {/* 쉬운 설명 하나로 보여 준다. whyKo 는 수치를 어떻게 읽으면 되는지 덧붙이는 보충이라 제목 없이 잇는다. */}
      <div className="flex flex-col gap-1.5">
        {term.definitionKo && <p className="text-[13.5px] text-ink-1 leading-relaxed">{term.definitionKo}</p>}
        {term.whyKo && <p className="text-[13px] text-ink-2 leading-relaxed">{term.whyKo}</p>}
      </div>
    </div>,
    document.body,
  )
}
