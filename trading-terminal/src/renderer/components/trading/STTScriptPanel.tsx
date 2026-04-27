import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import type { TranscriptLine } from '../../fixtures/sttTranscript.dev-mock'

interface STTScriptPanelProps {
  /** STT 라인 목록 (오래된 → 최신 순). 컨테이너가 자동으로 가장 마지막 라인을 강조한다. */
  transcript: readonly TranscriptLine[]
  /** LIVE 세션 진행 중 여부. false 면 placeholder 표시. */
  isLive: boolean
  /** WPM 메타 (헤더 우측 표시). */
  wpm?: number
  /** "최신 라인으로 점프" 콜백 (선택). 미제공 시 내부에서만 처리. */
  onJumpLatest?: () => void
}

/**
 * STTScriptPanel — 좌측 35% 패널, 어닝콜 STT 스크립트 스트리밍.
 *
 * 디자인 매칭: TradingRoomPage.html `.stt` / `.stt-body` / `.chunk` / `.chunk.latest`.
 *
 * 자동 스크롤 패턴:
 *  - 새 라인 추가 시 bottom 으로 스크롤.
 *  - 사용자가 위로 스크롤하면 자동 스크롤 일시 중단 (sticky bottom 패턴).
 *  - 다시 bottom 근처로 가면 자동 스크롤 재개.
 *  - 일시 중단 중에는 우측 상단에 "최신 ↓" 버튼 표시.
 *
 * 보안:
 *  - text 는 plain string 만 — innerHTML 미사용 (어닝콜 텍스트는 외부 데이터).
 *  - 키워드 하이라이트 (kw-buy 등) 는 PR #4 범위 밖 — 향후 별도 토큰화 후 적용.
 *
 * 데이터 소스:
 *  - PR #4: sttTranscript.dev-mock fixture (DEV ONLY).
 *  - 향후 PR: STOMP `/user/{userId}/queue/transcript` IPC 채널.
 */
export default function STTScriptPanel({
  transcript,
  isLive,
  wpm,
  onJumpLatest,
}: STTScriptPanelProps) {
  const scrollRef = useRef<HTMLDivElement>(null)
  const [isStickyBottom, setIsStickyBottom] = useState(true)
  const navigate = useNavigate()

  // 새 라인 추가 시 자동 스크롤 (sticky bottom 일 때만).
  useEffect(() => {
    if (!isStickyBottom) return
    const el = scrollRef.current
    if (!el) return
    el.scrollTop = el.scrollHeight
  }, [transcript.length, isStickyBottom])

  // 사용자 스크롤 → bottom 근처 (16px 이내) 면 sticky 활성, 그 외 비활성.
  function handleScroll() {
    const el = scrollRef.current
    if (!el) return
    const distFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight
    setIsStickyBottom(distFromBottom < 16)
  }

  function jumpToLatest() {
    const el = scrollRef.current
    if (el) el.scrollTop = el.scrollHeight
    setIsStickyBottom(true)
    onJumpLatest?.()
  }

  if (!isLive) {
    return (
      <section className="card p-0 flex flex-col overflow-hidden h-full">
        <div className="h-10 px-3.5 flex items-center justify-between border-b border-border-subtle shrink-0">
          <span className="text-[11px] font-semibold text-text-secondary uppercase tracking-[0.14em]">
            실시간 스크립트
          </span>
          <span className="text-[11px] text-text-tertiary">대기 중</span>
        </div>
        <div className="flex-1 flex flex-col items-center justify-center text-center px-6 gap-3">
          <p className="text-sm text-text-tertiary leading-relaxed">
            진행 중인 어닝콜이 없습니다.
          </p>
          <button
            type="button"
            onClick={() => navigate('/dashboard')}
            className="text-xs text-accent-400 hover:text-accent-300 underline underline-offset-4
                       transition-colors duration-100"
          >
            대시보드에서 어닝콜 선택 →
          </button>
        </div>
      </section>
    )
  }

  const latestIdx = transcript.length - 1

  return (
    <section className="card p-0 flex flex-col overflow-hidden h-full">
      <div className="h-10 px-3.5 flex items-center justify-between border-b border-border-subtle shrink-0">
        <span className="text-[11px] font-semibold text-text-secondary uppercase tracking-[0.14em]">
          실시간 스크립트
        </span>
        <span className="inline-flex items-center gap-1.5 px-2 py-[3px] rounded
                         bg-surface-2 num text-[11px] text-text-secondary">
          WPM <b className="text-accent-400 font-semibold">{wpm ?? '--'}</b>
          <span className="w-1 h-1 rounded-full bg-buy" />
          자동
        </span>
      </div>

      <div className="relative flex-1 min-h-0">
        <div
          ref={scrollRef}
          onScroll={handleScroll}
          className="absolute inset-0 overflow-y-auto px-3.5 py-3 flex flex-col gap-2.5"
        >
          {transcript.map((line, i) => {
            const isLatest = i === latestIdx
            return (
              <div
                key={line.id}
                className={
                  isLatest
                    ? 'relative pl-3 pr-2.5 py-2 -mx-2.5 rounded-md bg-white/[0.05] animate-fade-in'
                    : 'flex flex-col gap-1'
                }
              >
                {isLatest && (
                  <span
                    className="absolute left-0 top-1.5 bottom-1.5 w-0.5 rounded
                               bg-text-secondary shadow-[0_0_6px_rgba(255,255,255,0.25)]"
                  />
                )}
                <div className="num text-[10px] text-text-tertiary">
                  [{line.timestamp}] · {line.speaker}
                  {line.ai_score != null && (
                    <span
                      className={
                        'ml-2 px-1 py-px rounded bg-surface-2 text-[9px] ' +
                        // 음수 점수: text-text-tertiary 토큰 (#94a3b8) 그대로 사용.
                        (line.ai_score >= 0 ? '' : 'text-text-tertiary')
                      }
                      // 양수 점수만 인라인 hex — design-canvas: AI score purple
                      // (#a78bfa, violet-400). 디자인 시스템에 ai-* 토큰 정식 정의 후
                      // 일괄 치환 예정 (TradingRoomPage 보라색 칩들과 동일 사유).
                      style={
                        line.ai_score >= 0
                          ? { color: '#a78bfa' }
                          : undefined
                      }
                    >
                      AI {line.ai_score >= 0 ? '+' : ''}{line.ai_score.toFixed(2)}
                    </span>
                  )}
                </div>
                <div
                  className={
                    isLatest
                      ? 'text-[13px] text-text-primary leading-[1.55]'
                      : 'text-[13px] text-text-secondary leading-[1.55]'
                  }
                >
                  {line.text}
                </div>
              </div>
            )
          })}
        </div>

        {/* 우측 스크롤 인디케이터 라인 — 디자인 캔버스 .stt-scroll-indicator */}
        <span
          className="pointer-events-none absolute right-1.5 top-3 bottom-3 w-0.5 opacity-40 rounded"
          style={{ background: 'linear-gradient(#10b981, transparent)' }}
        />

        {!isStickyBottom && (
          <button
            type="button"
            onClick={jumpToLatest}
            className="absolute right-3 bottom-3 px-2.5 py-1 rounded-md
                       bg-accent-500 text-accent-foreground text-[10px] font-bold tracking-[0.06em]
                       shadow-md hover:bg-accent-600 transition-colors duration-100"
          >
            최신 ↓
          </button>
        )}
      </div>
    </section>
  )
}
