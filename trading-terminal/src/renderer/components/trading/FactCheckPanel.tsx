import { useEffect, useRef } from 'react'
import type { FactCheckClaim, FactCheckVerdict } from '../../store/useFactCheckStore'

/**
 * 판정별 표기.
 *
 * 판정값은 AI Engine 의 3종(Contract 9.3)을 단일 진실 공급원으로 삼되,
 * 라벨은 발표를 보는 사람이 바로 읽을 수 있는 한국어를 쓴다.
 * "반박됨" 보다 "사실과 다름" 이 무슨 뜻인지 설명이 필요 없다.
 */
const VERDICT_META: Record<FactCheckVerdict, { label: string; color: string; bg: string }> = {
  SUPPORTED:             { label: '사실 확인',   color: '#10b981', bg: 'rgba(16,185,129,0.12)'  },
  CONTRADICTED:          { label: '사실과 다름', color: '#ef4444', bg: 'rgba(239,68,68,0.12)'   },
  INSUFFICIENT_EVIDENCE: { label: '근거 부족',   color: '#64748b', bg: 'rgba(100,116,139,0.12)' },
}

interface FactCheckPanelProps {
  /** 도착 순서(= 발언 순서)로 누적된 판정. */
  claims: readonly FactCheckClaim[]
  /**
   * 검증 대기 중 여부. 발언은 화면에 떴는데 아직 판정이 안 온 상태.
   * AI Engine 이 3문장을 모아 LLM 2패스를 돌리므로 5~15초가 걸린다.
   * 이 표시가 없으면 사용자는 시스템이 멈춘 것으로 오해한다.
   */
  analyzing: boolean
}

/**
 * FactCheckPanel — 중앙 하단 어닝콜 실시간 팩트체크 패널.
 *
 * Backend Contract 4.6 (/topic/factcheck/{ticker}) 로 도착한 판정을 순서대로 표시한다.
 * 판정은 이미 서버에서 완료되어 도착하므로 클라이언트는 "분석 중" 을 흉내내지 않는다 —
 * 다만 아직 도착하지 않은 구간이 있으면 마지막에 대기 표시를 둔다.
 */
export default function FactCheckPanel({ claims, analyzing }: FactCheckPanelProps) {
  const scrollRef = useRef<HTMLDivElement>(null)

  // 새 판정 도착 시 하단으로 스크롤.
  useEffect(() => {
    const el = scrollRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [claims.length, analyzing])

  return (
    <div className="flex-1 flex flex-col min-h-0 border-t border-border-subtle bg-surface-1">
      {/* 헤더 */}
      <div className="h-[34px] px-3.5 flex items-center justify-between border-b border-border-subtle shrink-0 gap-2">
        <span className="text-[10.5px] font-semibold text-text-secondary uppercase tracking-[0.14em] inline-flex items-center gap-2">
          <span className="w-2 h-2 rounded-sm bg-buy shadow-[0_0_8px_rgba(16,185,129,0.5)]" />
          실시간 팩트체크
        </span>
        <span className="num text-[10px] text-text-tertiary tabular-nums">{claims.length}건</span>
      </div>

      {/* 카드 목록 */}
      <div
        ref={scrollRef}
        className="flex-1 overflow-y-auto min-h-0 px-2 py-1.5 flex flex-col gap-1.5"
      >
        {claims.length === 0 && !analyzing ? (
          <div className="flex-1 flex items-center justify-center text-[11px] text-text-disabled">
            발언 분석 대기 중...
          </div>
        ) : (
          <>
            {claims.map((claim) => {
              const v = VERDICT_META[claim.verdict]
              return (
                <div
                  key={claim.claimId}
                  className="px-2.5 py-2 rounded bg-surface-2 border border-border-subtle animate-fade-in flex flex-col gap-1"
                >
                  {/* 주장 + 판정 뱃지 */}
                  <div className="flex items-start gap-1.5">
                    <span className="flex-1 min-w-0 text-[10.5px] text-text-primary leading-snug">
                      {claim.claim}
                    </span>
                    <span
                      className="shrink-0 px-1.5 py-px rounded text-[9px] font-bold tracking-[0.06em] border whitespace-nowrap"
                      style={{ color: v.color, background: v.bg, borderColor: `${v.color}55` }}
                    >
                      {v.label}
                    </span>
                  </div>

                  {/* 판정 근거 설명 (AI Engine 이 한국어로 생성) */}
                  <div className="text-[10px] leading-snug" style={{ color: v.color }}>
                    → {claim.explanationKo}
                  </div>

                  {/* 인용 출처 — 매체명과 제목. 판정의 신뢰성을 보여주는 핵심 정보다. */}
                  {claim.evidence.length > 0 && (
                    <div className="flex flex-col gap-0.5">
                      {claim.evidence.map((e) => (
                        <div
                          key={e.docId}
                          className="text-[10px] text-text-tertiary leading-snug truncate"
                          title={e.snippet}
                        >
                          <span className="uppercase tracking-[0.06em] text-text-disabled">
                            {e.source}
                          </span>
                          {e.title ? ` · ${e.title}` : ''}
                        </div>
                      ))}
                    </div>
                  )}

                  {/* 신뢰도 바 */}
                  <div className="flex items-center gap-1.5 pt-0.5">
                    <div className="flex-1 h-[2px] rounded-full bg-surface-0">
                      <div
                        className="h-full rounded-full"
                        style={{ width: `${claim.confidence * 100}%`, background: v.color }}
                      />
                    </div>
                    <span className="num text-[9px] text-text-tertiary">
                      {Math.round(claim.confidence * 100)}% 신뢰
                    </span>
                  </div>
                </div>
              )
            })}

            {analyzing && (
              <div className="px-2.5 py-2 rounded bg-surface-2 border border-border-subtle animate-pulse">
                <div className="text-[10px] text-text-disabled">AI 교차 분석 중...</div>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}
