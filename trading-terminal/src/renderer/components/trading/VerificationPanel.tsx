import { useEffect, useMemo, useRef } from 'react'
import type { FactCheckClaim, FactCheckVerdict } from '../../store/useFactCheckStore'
import type {
  PreviousCall,
  TranscriptDiffChangeType,
  TranscriptDiffItem,
} from '../../store/useTranscriptDiffStore'

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

/** 변화 유형별 표기. 엔진의 5종을 그대로 쓴다. */
const CHANGE_META: Record<TranscriptDiffChangeType, { label: string; color: string; bg: string }> = {
  improved:  { label: '개선',      color: '#10b981', bg: 'rgba(16,185,129,0.12)'  },
  weakened:  { label: '후퇴',      color: '#ef4444', bg: 'rgba(239,68,68,0.12)'   },
  unchanged: { label: '변화 없음', color: '#64748b', bg: 'rgba(100,116,139,0.12)' },
  mixed:     { label: '혼재',      color: '#f59e0b', bg: 'rgba(245,158,11,0.12)'  },
  new_claim: { label: '새 언급',   color: '#3b82f6', bg: 'rgba(59,130,246,0.12)'  },
}

/** 주제 라벨. 엔진의 7축을 한국어로 옮긴다. 목록에 없으면 원값을 그대로 쓴다. */
const TOPIC_LABELS: Record<string, string> = {
  guidance: '가이던스',
  margin: '마진',
  demand: '수요',
  capex: '투자',
  supply: '공급망',
  competition: '경쟁',
  revenue: '매출',
}

/** 근거 종류 뱃지. 같은 흐름에 섞이므로 무엇과 대조한 판단인지 먼저 보여야 한다. */
const KIND_META = {
  news:  { label: '뉴스 대조',     color: '#94a3b8' },
  prior: { label: '지난 분기 대비', color: '#3b82f6' },
} as const

type VerificationEntry =
  | { kind: 'news'; sortKey: number; claim: FactCheckClaim }
  | { kind: 'prior'; sortKey: number; item: TranscriptDiffItem; index: number }

interface VerificationPanelProps {
  /** 뉴스 근거 팩트체크 판정. 도착 순서대로 누적된 것. */
  claims: readonly FactCheckClaim[]
  /** 직전 콜 대조 결과. */
  diffItems: readonly TranscriptDiffItem[]
  /** 비교 대상이 된 직전 콜. 대조가 한 건이라도 있을 때 밝힌다. */
  previousCall: PreviousCall | null
  /**
   * 검증 대기 중 여부. 발언은 화면에 떴는데 아직 판정이 안 온 상태.
   * AI Engine 이 3문장을 모아 LLM 2패스를 돌리므로 5~15초가 걸린다.
   * 이 표시가 없으면 사용자는 시스템이 멈춘 것으로 오해한다.
   */
  analyzing: boolean
}

/**
 * VerificationPanel — 발언 검증 패널.
 *
 * 어닝콜 발언에 대한 기계 판단을 한 흐름으로 보여준다. 근거가 두 종류다.
 *
 *  - <b>뉴스 대조</b> — 콜 전 30일 뉴스를 근거로 "이 말이 사실인가" 를 본다
 *  - <b>지난 분기 대비</b> — 같은 회사의 직전 콜을 근거로 "이 말이 달라졌는가" 를 본다
 *
 * 근거는 다르지만 둘 다 특정 발언에 붙는 판단이고 신뢰도와 인용을 함께 낸다. 그래서
 * 패널을 나누지 않고 뱃지로 구분한다. 나누면 같은 발언에 대한 두 판단이 떨어지고,
 * 도착이 드문 쪽은 빈 상자가 계속 자리를 차지한다.
 *
 * 정렬은 도착 순서가 아니라 <b>발언 순서</b>다. 대조가 팩트체크보다 늦게 도착해도
 * 스크립트와 같은 순서로 읽히고, 같은 발언의 두 판단이 나란히 붙는다.
 */
export default function VerificationPanel({
  claims,
  diffItems,
  previousCall,
  analyzing,
}: VerificationPanelProps) {
  const scrollRef = useRef<HTMLDivElement>(null)

  const entries = useMemo<VerificationEntry[]>(() => {
    const merged: VerificationEntry[] = [
      ...claims.map<VerificationEntry>((claim) => ({
        kind: 'news',
        // 배치는 발언 범위를 덮는다. 끝 sequence 기준으로 놓으면 그 범위 뒤에 온다.
        sortKey: claim.batchEndSequence,
        claim,
      })),
      ...diffItems.map<VerificationEntry>((item, index) => ({
        kind: 'prior',
        sortKey: item.sequence,
        item,
        index,
      })),
    ]
    // 같은 sequence 면 뉴스 대조를 먼저 놓는다 — 사실 확인이 변화 해석보다 앞선다.
    return merged.sort((a, b) =>
      a.sortKey !== b.sortKey
        ? a.sortKey - b.sortKey
        : Number(a.kind === 'prior') - Number(b.kind === 'prior'),
    )
  }, [claims, diffItems])

  // 새 판정 도착 시 하단으로 스크롤.
  useEffect(() => {
    const el = scrollRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [entries.length, analyzing])

  return (
    <div className="flex flex-col min-h-0 h-full">
      {/* 헤더 */}
      <div className="h-10 px-3.5 flex items-center justify-between border-b border-border-subtle shrink-0 gap-2">
        <span className="text-[11px] font-semibold text-text-secondary uppercase tracking-[0.14em] inline-flex items-center gap-2">
          <span className="w-2 h-2 rounded-sm bg-buy shadow-[0_0_8px_rgba(16,185,129,0.5)]" />
          발언 검증
        </span>
        <span className="num text-[10px] text-text-tertiary tabular-nums">
          뉴스 {claims.length} · 지난 분기 {diffItems.length}
        </span>
      </div>

      {/*
        무엇과 비교했는지 밝힌다. 이 줄이 없으면 "지난 분기" 가 어느 콜인지 알 수 없고,
        발표에서 근거를 물었을 때 답할 것이 없다.
      */}
      {previousCall && diffItems.length > 0 && (
        <div className="px-3.5 py-1.5 border-b border-border-subtle shrink-0 text-[10px] text-text-tertiary leading-snug">
          지난 분기 비교 대상 ·{' '}
          <span className="text-text-secondary">
            {previousCall.fiscalQuarter || previousCall.title || previousCall.documentId}
          </span>
          {previousCall.publishedAt && (
            <span className="num text-text-disabled"> ({previousCall.publishedAt})</span>
          )}
        </div>
      )}

      {/* 카드 목록 */}
      <div
        ref={scrollRef}
        className="flex-1 overflow-y-auto min-h-0 px-2 py-1.5 flex flex-col gap-1.5"
      >
        {entries.length === 0 && !analyzing ? (
          <div className="flex-1 flex items-center justify-center text-[11px] text-text-disabled">
            발언 분석 대기 중...
          </div>
        ) : (
          <>
            {entries.map((entry) =>
              entry.kind === 'news' ? (
                <NewsCard key={entry.claim.claimId} claim={entry.claim} />
              ) : (
                <PriorCard
                  key={`prior-${entry.item.sequence}-${entry.index}`}
                  item={entry.item}
                />
              ),
            )}

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

/** 근거 종류 뱃지. 두 카드가 같은 흐름에 있으므로 공통으로 쓴다. */
function KindBadge({ kind }: { kind: 'news' | 'prior' }) {
  const meta = KIND_META[kind]
  return (
    <span
      className="text-[8.5px] uppercase tracking-[0.08em] shrink-0"
      style={{ color: meta.color }}
    >
      {meta.label}
    </span>
  )
}

/** 뉴스 근거 판정 카드. */
function NewsCard({ claim }: { claim: FactCheckClaim }) {
  const v = VERDICT_META[claim.verdict]
  return (
    <div className="px-2.5 py-2 rounded bg-surface-2 border border-border-subtle animate-fade-in flex flex-col gap-1">
      <div className="flex items-center justify-between gap-1.5">
        <KindBadge kind="news" />
        <span
          className="shrink-0 px-1.5 py-px rounded text-[9px] font-bold tracking-[0.06em] border whitespace-nowrap"
          style={{ color: v.color, background: v.bg, borderColor: `${v.color}55` }}
        >
          {v.label}
        </span>
      </div>

      <span className="text-[10.5px] text-text-primary leading-snug">{claim.claim}</span>

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
              <span className="uppercase tracking-[0.06em] text-text-disabled">{e.source}</span>
              {e.title ? ` · ${e.title}` : ''}
            </div>
          ))}
        </div>
      )}

      <ConfidenceBar value={claim.confidence} color={v.color} />
    </div>
  )
}

/** 직전 콜 대조 카드. */
function PriorCard({ item }: { item: TranscriptDiffItem }) {
  const meta = CHANGE_META[item.changeType]
  const topic = TOPIC_LABELS[item.topic] ?? item.topic
  return (
    <div className="px-2.5 py-2 rounded bg-surface-2 border border-border-subtle animate-fade-in flex flex-col gap-1">
      <div className="flex items-center justify-between gap-1.5">
        <span className="inline-flex items-center gap-1.5 min-w-0">
          <KindBadge kind="prior" />
          <span className="text-[10px] text-text-secondary truncate">{topic}</span>
        </span>
        <span
          className="shrink-0 px-1.5 py-px rounded text-[9px] font-bold tracking-[0.06em] border whitespace-nowrap"
          style={{ color: meta.color, background: meta.bg, borderColor: `${meta.color}55` }}
        >
          {meta.label}
        </span>
      </div>

      <p className="text-[10.5px] text-text-primary leading-snug">{item.summaryKo}</p>

      {/*
        직전 발언은 원문 그대로 보여 준다. 요약만 띄우면 근거를 확인할 수 없고,
        판단이 맞는지 발표 자리에서 검증할 방법이 없어진다.
      */}
      {item.priorClaim && (
        <div className="border-l-2 border-border-subtle pl-2 flex flex-col gap-0.5">
          <span className="text-[9px] text-text-disabled uppercase tracking-[0.1em]">직전 콜</span>
          <p className="text-[10px] text-text-tertiary leading-snug">{item.priorClaim}</p>
        </div>
      )}

      <ConfidenceBar value={item.confidence} color={meta.color} />
    </div>
  )
}

function ConfidenceBar({ value, color }: { value: number; color: string }) {
  return (
    <div className="flex items-center gap-1.5 pt-0.5">
      <div className="flex-1 h-[2px] rounded-full bg-surface-0">
        <div className="h-full rounded-full" style={{ width: `${value * 100}%`, background: color }} />
      </div>
      <span className="num text-[9px] text-text-tertiary">{Math.round(value * 100)}% 신뢰</span>
    </div>
  )
}
