import { useEffect, useMemo, useRef, useState } from 'react'
import {
  useAssistantStore,
  selectIsStreaming,
  selectRemainingQuestions,
  type AssistantCitation,
  type AssistantTurn,
} from '../../store/useAssistantStore'
import {
  ASSISTANT_DISCLAIMER,
  MAX_QUESTION_CHARS,
  MAX_QUESTIONS_PER_CONVERSATION,
  MISSING_SOURCE_LABELS,
  SUGGESTED_QUESTIONS,
} from '../../constants/assistant'
import type { SuggestedQuestionId } from '../../../lib/types/assistant'
import type { TranscriptSegment } from '../../store/useTranscriptStore'
import { formatCallClock } from '../../lib/callScreen'
import { citationKindLabel, numberCitations, splitAnswer } from '../../lib/assistantAnswer'

interface AssistantPanelProps {
  ticker: string
  callId: string
  /** 이번 콜 자막. 고른 대목과 질문 시점을 글로 보여 줄 때 쓴다. */
  segments: readonly TranscriptSegment[]
  /** 고른 대목의 발언 번호. null 이면 콜 전체에 대한 질문이다. */
  anchorSequence: number | null
  onClearAnchor: () => void
  /** 근거 발언으로 자막을 옮긴다. */
  onFocusSequence: (sequence: number) => void
  isLive: boolean
}

/**
 * 어닝콜 질의응답(#112) — 지금까지 나온 콜 내용이나 고른 대목에 대해 묻는다 (docs/design/screens/call.md 질문).
 *
 *  - 범위(콜 전체 / 고른 대목)가 맨 위에 늘 보인다. 범위가 바뀌면 새 대화다(스토어가 정한다).
 *  - 답은 스트리밍으로 늘어나고, 본문의 근거 표시는 번호 칩이 되어 아래 근거 목록과 짝을 이룬다.
 *  - 상시 고지는 입력칸 바로 위에 늘 둔다.
 *  - 답 본문은 외부 데이터라 innerHTML 을 쓰지 않는다.
 */
export default function AssistantPanel({
  ticker,
  callId,
  segments,
  anchorSequence,
  onClearAnchor,
  onFocusSequence,
  isLive,
}: AssistantPanelProps) {
  const conversation = useAssistantStore((s) => s.conversation)
  const open = useAssistantStore((s) => s.open)
  const ask = useAssistantStore((s) => s.ask)
  const cancel = useAssistantStore((s) => s.cancel)
  const reset = useAssistantStore((s) => s.reset)
  const streaming = useAssistantStore(selectIsStreaming)
  const remaining = useAssistantStore(selectRemainingQuestions)
  // 하루 한도에 걸리면 다시 보내도 또 거절되므로 입력을 막는다
  const lastError = useAssistantStore((s) => s.conversation?.turns.at(-1)?.error?.code ?? null)
  const dailyLimited = lastError === 'daily_limit_exceeded'

  useEffect(() => {
    open({ ticker, callId, anchorSequence })
  }, [open, ticker, callId, anchorSequence])

  const bySequence = useMemo(() => new Map(segments.map((s) => [s.sequence, s])), [segments])
  const anchor = anchorSequence != null ? bySequence.get(anchorSequence) ?? null : null
  const turns = conversation?.turns ?? []

  // 새 질문 · 늘어나는 답을 따라 내려간다. 위로 올려 읽는 중이면 멈춘다.
  const scrollRef = useRef<HTMLDivElement>(null)
  const stuck = useRef(true)
  const lastTurn = turns[turns.length - 1]
  useEffect(() => {
    const el = scrollRef.current
    if (el && stuck.current) el.scrollTop = el.scrollHeight
  }, [turns.length, lastTurn?.text, lastTurn?.status, lastTurn?.citations.length])

  const startNewConversation = () => {
    // 진행 중인 답이 있으면 서버 요청부터 멈춘다. reset 만 하면 생성이 끝까지 돌고 하루 한도도 줄어든다.
    void cancel()
    reset()
    open({ ticker, callId, anchorSequence })
  }

  const send = (question: string, suggestedQuestionId: SuggestedQuestionId | null = null) => {
    stuck.current = true
    void ask({ question, suggestedQuestionId })
  }

  return (
    <div className="flex flex-col h-full min-h-0">
      <ScopeHeader anchor={anchor} anchorSequence={anchorSequence} onClearAnchor={onClearAnchor} onFocusSequence={onFocusSequence} />

      <div
        ref={scrollRef}
        onScroll={(e) => {
          const el = e.currentTarget
          stuck.current = el.scrollHeight - el.scrollTop - el.clientHeight < 24
        }}
        className="flex-1 min-h-0 overflow-y-auto flex flex-col gap-5 py-4"
      >
        {turns.length === 0 ? (
          <SuggestedQuestions
            title={anchor ? '이 대목 말고 콜 전체에 대해 물어볼 수도 있습니다' : '이런 걸 물어볼 수 있습니다'}
            ids={SUGGESTED_QUESTIONS.map((q) => q.id)}
            disabled={streaming}
            onAsk={send}
          />
        ) : (
          turns.map((turn, i) => (
            <TurnView
              key={turn.id}
              turn={turn}
              isLast={i === turns.length - 1}
              isLive={isLive}
              bySequence={bySequence}
              canAsk={!streaming && remaining > 0}
              onAsk={send}
              onFocusSequence={onFocusSequence}
            />
          ))
        )}
      </div>

      {/* 늘어나는 답 본문 대신 짧은 상태만 읽어 준다. 패널에 늘 있어야 첫 알림도 읽힌다. */}
      <p className="sr-only" aria-live="polite">
        {lastTurn ? STATUS_ANNOUNCE[lastTurn.status] : ''}
      </p>

      <Composer
        streaming={streaming}
        remaining={remaining}
        locked={dailyLimited}
        onSend={(q) => send(q)}
        onCancel={() => void cancel()}
        onNewConversation={startNewConversation}
      />
    </div>
  )
}

// ── 범위 ────────────────────────────────────────────────────────────────

function ScopeHeader({
  anchor,
  anchorSequence,
  onClearAnchor,
  onFocusSequence,
}: {
  anchor: TranscriptSegment | null
  anchorSequence: number | null
  onClearAnchor: () => void
  onFocusSequence: (sequence: number) => void
}) {
  if (anchorSequence == null) {
    return (
      <p className="shrink-0 text-[12.5px] text-ink-3">
        지금까지 나온 <span className="text-ink-2">콜 전체</span>에 대해 묻습니다. 특정 발언을 물으려면 자막에서 '이 대목 질문'을
        누르세요.
      </p>
    )
  }
  return (
    <div className="shrink-0 rounded-[18px] px-4 py-3 flex flex-col gap-1.5 bg-white/[0.05] border border-white/10">
      <div className="flex items-center justify-between gap-2">
        <span className="text-[12px] font-semibold text-ink-2">이 대목에 대해 묻습니다</span>
        <button type="button" onClick={onClearAnchor} className="text-[12px] text-ink-3 hover:text-ink-1">
          콜 전체로
        </button>
      </div>
      {anchor ? (
        <button
          type="button"
          onClick={() => onFocusSequence(anchor.sequence)}
          className="text-left flex flex-col gap-0.5 rounded-[10px] hover:bg-white/[0.04]"
          title="자막에서 보기"
        >
          <span className="text-[11.5px] text-ink-3">
            <span className="num">{formatCallClock(anchor.startMs)}</span>
            {anchor.speaker && ` · ${anchor.speaker}`}
          </span>
          <span className="text-[13px] text-ink-1 leading-snug line-clamp-3 select-text">{anchor.text}</span>
        </button>
      ) : (
        <span className="text-[12.5px] text-ink-3">고른 발언을 자막에서 찾지 못했습니다.</span>
      )}
    </div>
  )
}

// ── 추천 질문 ────────────────────────────────────────────────────────────

function SuggestedQuestions({
  title,
  ids,
  disabled,
  onAsk,
}: {
  title: string
  ids: readonly SuggestedQuestionId[]
  disabled: boolean
  onAsk: (question: string, id: SuggestedQuestionId) => void
}) {
  const items = SUGGESTED_QUESTIONS.filter((q) => ids.includes(q.id))
  if (items.length === 0) return null
  return (
    <div className="flex flex-col gap-2">
      <span className="text-[12px] text-ink-3">{title}</span>
      <div className="flex flex-wrap gap-2">
        {items.map((q) => (
          <button
            key={q.id}
            type="button"
            disabled={disabled}
            onClick={() => onAsk(q.label, q.id)}
            className="gbtn gbtn-sm !font-medium !whitespace-normal text-left"
          >
            {q.label}
          </button>
        ))}
      </div>
      <span className="text-[11.5px] text-ink-3">추천 질문은 고른 대목과 관계없이 콜 전체를 보고 답합니다.</span>
    </div>
  )
}

// ── 질문 · 답 한 쌍 ──────────────────────────────────────────────────────

function TurnView({
  turn,
  isLast,
  isLive,
  bySequence,
  canAsk,
  onAsk,
  onFocusSequence,
}: {
  turn: AssistantTurn
  isLast: boolean
  isLive: boolean
  bySequence: ReadonlyMap<number, TranscriptSegment>
  canAsk: boolean
  onAsk: (question: string, id?: SuggestedQuestionId | null) => void
  onFocusSequence: (sequence: number) => void
}) {
  const [flash, setFlash] = useState<{ marker: string; nonce: number } | null>(null)
  const numbers = useMemo(
    () => numberCitations(turn.text, turn.citations.map((c) => c.marker)),
    [turn.text, turn.citations],
  )
  const byMarker = useMemo(() => new Map(turn.citations.map((c) => [c.marker, c])), [turn.citations])
  const citationsDone = turn.status !== 'pending' && turn.status !== 'streaming'
  const asOf = turn.meta ? bySequence.get(turn.meta.asOfSequence) : undefined

  useEffect(() => {
    if (!flash) return
    const t = setTimeout(() => setFlash(null), 1400)
    return () => clearTimeout(t)
  }, [flash])

  return (
    <article className="flex flex-col gap-2.5" aria-label={`질문: ${turn.question}`}>
      <p className="self-end max-w-[88%] rounded-[16px] px-3.5 py-2 text-[13.5px] text-ink-1 leading-snug select-text bg-white/[0.07]">
        {turn.question}
      </p>

      <div className="flex flex-col gap-2.5" aria-busy={turn.status === 'streaming' || turn.status === 'pending'}>
        {turn.status === 'pending' && <p className="text-[13px] text-ink-3">콜 내용에서 근거를 찾고 있습니다…</p>}

        {turn.text && (
          <p className="text-[14px] text-ink-1 leading-[1.7] select-text whitespace-pre-wrap">
            {splitAnswer(visibleText(turn)).map((part, i) =>
              part.kind === 'text' ? (
                <span key={i}>{part.text}</span>
              ) : (
                <CiteChip
                  key={i}
                  number={numbers.get(part.marker)}
                  citation={byMarker.get(part.marker)}
                  citationsDone={citationsDone}
                  onClick={() => setFlash({ marker: part.marker, nonce: Date.now() })}
                />
              ),
            )}
            {turn.status === 'streaming' && <span className="inline-block w-1.5 h-[1em] align-[-2px] ml-0.5 bg-ink-2 animate-pulse" aria-hidden />}
          </p>
        )}

        {turn.status === 'cancelled' && <p className="text-[12.5px] text-ink-3">질문을 취소했습니다.</p>}

        {turn.status === 'error' && turn.error && (
          <div className="flex flex-col items-start gap-2">
            <p className="text-[13px]" style={{ color: 'var(--danger)' }}>
              {turn.error.message}
              {turn.error.code === 'daily_limit_exceeded' && turn.resetAt && ` ${formatResetAt(turn.resetAt)}부터 다시 질문할 수 있습니다.`}
            </p>
            {!NO_RETRY_CODES.has(turn.error.code) && isLast && (
              <button type="button" className="gbtn gbtn-sm" disabled={!canAsk} onClick={() => onAsk(turn.question, turn.suggestedQuestionId)}>
                다시 질문
              </button>
            )}
          </div>
        )}

        {turn.status === 'refused' && isLast && (
          <SuggestedQuestions title="대신 이런 질문은 답할 수 있습니다" ids={turn.suggestedQuestionIds} disabled={!canAsk} onAsk={onAsk} />
        )}

        {turn.meta && turn.meta.missingSources.length > 0 && (
          <p className="text-[12px] text-ink-3">
            {turn.meta.missingSources.map((s) => MISSING_SOURCE_LABELS[s] ?? s).join(' · ')}을(를) 불러오지 못해 나머지 자료로 답했습니다.
          </p>
        )}

        {turn.citations.length > 0 && (
          <CitationList
            citations={turn.citations}
            numbers={numbers}
            flash={flash}
            onFocusSequence={onFocusSequence}
          />
        )}

        {isLive && asOf && citationsDone && turn.status !== 'error' && turn.status !== 'cancelled' && (
          <p className="text-[11.5px] text-ink-3">
            콜 <span className="num">{formatCallClock(asOf.startMs)}</span> 시점까지의 내용으로 답했습니다. 그 뒤 발언은 반영하지 않았습니다.
          </p>
        )}
      </div>
    </article>
  )
}

/** 본문 속 근거 번호. 원문과 일치하는지 확인하지 못한 근거는 점선 테두리로 약하게 둔다. */
function CiteChip({
  number,
  citation,
  citationsDone,
  onClick,
}: {
  number: number | undefined
  citation: AssistantCitation | undefined
  citationsDone: boolean
  onClick: () => void
}) {
  // 근거 목록이 끝난 뒤에도 짝이 없으면 근거 목록에 없는 표시다
  const weak = citationsDone && (!citation || citation.type === null || !citation.verified)
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={!citation}
      className={`inline-flex items-center justify-center min-w-[18px] h-[18px] px-1 mx-0.5 align-[2px] rounded-full text-[10.5px] font-semibold tabular-nums
                  ${weak ? 'border border-dashed border-white/25 text-ink-3' : 'border border-white/20 text-ink-2 hover:text-ink-1 hover:border-white/40'}`}
      aria-label={`근거 ${number ?? ''}${weak ? ' — 원문과 일치하지 않을 수 있음' : ''}`}
    >
      {number ?? '·'}
    </button>
  )
}

function CitationList({
  citations,
  numbers,
  flash,
  onFocusSequence,
}: {
  citations: readonly AssistantCitation[]
  numbers: ReadonlyMap<string, number>
  flash: { marker: string; nonce: number } | null
  onFocusSequence: (sequence: number) => void
}) {
  const flashMarker = flash?.marker ?? null
  const refs = useRef(new Map<string, HTMLLIElement>())
  useEffect(() => {
    if (flash) refs.current.get(flash.marker)?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  }, [flash])

  return (
    <div className="flex flex-col gap-1.5 pt-1">
      <span className="text-[11.5px] font-semibold text-ink-3">근거</span>
      <ol className="flex flex-col gap-1.5">
        {citations.map((c) => {
          const weak = c.type === null || !c.verified
          const sequence = c.type === 'segment' ? segmentSequenceOf(c) : NaN
          return (
            <li
              key={c.marker}
              ref={(el) => {
                if (el) refs.current.set(c.marker, el)
                else refs.current.delete(c.marker)
              }}
              className={`rounded-[14px] px-3 py-2 flex gap-2.5 transition-colors duration-500 ${
                flashMarker === c.marker ? 'bg-white/[0.08]' : 'bg-white/[0.03]'
              } ${weak ? 'border border-dashed border-white/15' : ''}`}
            >
              <span className="text-[11px] font-semibold tabular-nums text-ink-3 pt-px w-4 shrink-0 text-right">
                {numbers.get(c.marker)}
              </span>
              <div className="flex flex-col gap-1 min-w-0 flex-1">
                <span className="text-[11.5px] text-ink-3">
                  {citationKindLabel(c.type)}
                  {c.speaker && ` · ${c.speaker}`}
                  {c.type === 'segment' && c.startMs != null && (
                    <>
                      {' · '}
                      <span className="num">{formatCallClock(c.startMs)}</span>
                    </>
                  )}
                  {c.type !== 'segment' && c.source && ` · ${c.source}`}
                  {c.type !== 'segment' && c.publishedAt && ` · ${formatDate(c.publishedAt)}`}
                </span>
                {c.title && <span className="text-[12.5px] text-ink-1 font-medium leading-snug">{c.title}</span>}
                {c.quote && (
                  <p className={`text-[12.5px] leading-snug select-text line-clamp-3 ${weak ? 'text-ink-3' : 'text-ink-2'}`}>{c.quote}</p>
                )}
                {weak && <span className="text-[11px] text-ink-3">원문과 일치하지 않을 수 있습니다</span>}
                {Number.isFinite(sequence) && (
                  <button
                    type="button"
                    onClick={() => onFocusSequence(sequence)}
                    className="self-start text-[11.5px] text-ink-2 hover:text-ink-1 underline decoration-dotted underline-offset-2"
                  >
                    자막에서 보기
                  </button>
                )}
              </div>
            </li>
          )
        })}
      </ol>
    </div>
  )
}

// ── 입력 ────────────────────────────────────────────────────────────────

function Composer({
  streaming,
  remaining,
  locked,
  onSend,
  onCancel,
  onNewConversation,
}: {
  streaming: boolean
  remaining: number
  /** 하루 한도 초과 — 입력과 보내기를 막는다. */
  locked: boolean
  onSend: (question: string) => void
  onCancel: () => void
  onNewConversation: () => void
}) {
  const [draft, setDraft] = useState('')
  const trimmed = draft.trim()
  const tooLong = trimmed.length > MAX_QUESTION_CHARS
  const canSend = !streaming && !locked && remaining > 0 && trimmed.length > 0 && !tooLong

  const submit = () => {
    if (!canSend) return
    onSend(trimmed)
    setDraft('')
  }

  return (
    <div className="shrink-0 flex flex-col gap-2 pt-3 border-t border-white/[0.08]">
      <p className="text-[11.5px] text-ink-3 leading-snug">{ASSISTANT_DISCLAIMER}</p>

      {remaining <= 0 && !streaming ? (
        <div className="flex items-center justify-between gap-3 py-1">
          <span className="text-[12.5px] text-ink-2">
            이 대화의 질문 {MAX_QUESTIONS_PER_CONVERSATION}개를 모두 썼습니다. 새 대화에서 이어서 물어보세요.
          </span>
          <button type="button" className="gbtn gbtn-sm shrink-0" onClick={onNewConversation}>
            새 대화
          </button>
        </div>
      ) : (
        <>
          <textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              // 한글 조합 중 Enter 는 글자 확정이라 보내지 않는다
              if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
                e.preventDefault()
                submit()
              }
            }}
            rows={2}
            disabled={locked}
            placeholder={locked ? '오늘 질문 횟수를 모두 썼습니다' : '콜 내용에 대해 질문하세요'}
            aria-label="질문"
            className={`${tooLong ? 'input-error' : 'input-base'} !text-[13.5px] resize-none leading-snug`}
          />
          <div className="flex items-center justify-between gap-3">
            <span className="text-[11.5px] text-ink-3 tabular-nums">
              남은 질문 {remaining} ·{' '}
              <span style={tooLong ? { color: 'var(--danger)' } : undefined}>
                {trimmed.length}/{MAX_QUESTION_CHARS}자
              </span>
            </span>
            {streaming ? (
              <button type="button" className="gbtn gbtn-sm" onClick={onCancel}>
                답변 멈추기
              </button>
            ) : (
              <button type="button" className="gbtn gbtn-sm" disabled={!canSend} onClick={submit}>
                질문하기
              </button>
            )}
          </div>
        </>
      )}
    </div>
  )
}

/** 다시 보내도 결과가 같은 오류. 하루 한도는 입력칸까지 막는다. */
const NO_RETRY_CODES = new Set(['daily_limit_exceeded', 'auth_expired', 'validation', 'ticker_mismatch'])

/** 발언 근거의 발언 번호. ref 가 비거나 숫자가 아니면 표시(`S12`)의 숫자를 쓴다. */
function segmentSequenceOf(c: AssistantCitation): number {
  const fromRef = c.ref != null && c.ref.trim() !== '' ? Number(c.ref) : NaN
  if (Number.isInteger(fromRef)) return fromRef
  const m = /^S(\d+)$/.exec(c.marker)
  return m ? Number(m[1]) : NaN
}

const STATUS_ANNOUNCE: Record<AssistantTurn['status'], string> = {
  pending: '답변을 준비하고 있습니다',
  streaming: '답변을 받는 중입니다',
  answered: '답변이 끝났습니다',
  no_evidence: '답변이 끝났습니다',
  refused: '답할 수 없는 질문입니다',
  error: '답변을 받지 못했습니다',
  cancelled: '질문을 취소했습니다',
}

/** 스트리밍 중에는 끝에 아직 닫히지 않은 근거 표시(`[S2` 처럼)가 걸릴 수 있어 그 조각을 숨긴다. */
function visibleText(turn: AssistantTurn): string {
  return turn.status === 'streaming' ? turn.text.replace(/\[[A-Z]?\d*$/, '') : turn.text
}

const KST_TIME = new Intl.DateTimeFormat('ko-KR', { timeZone: 'Asia/Seoul', month: 'long', day: 'numeric', hour: 'numeric', minute: '2-digit' })
const DATE = new Intl.DateTimeFormat('ko-KR', { timeZone: 'Asia/Seoul', year: 'numeric', month: 'numeric', day: 'numeric' })

function formatResetAt(iso: string): string {
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? '내일' : `${KST_TIME.format(d)}(한국 시간)`
}

function formatDate(sec: number): string {
  return DATE.format(new Date(sec * 1000))
}
