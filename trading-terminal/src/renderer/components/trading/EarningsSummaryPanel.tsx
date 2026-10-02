import type { EarningsSummary, ImpactDirection, SignalDirection } from '../../types/earningsSummary'

/**
 * 방향 표기. 이 화면은 매매 지시가 아니라 어닝콜 해석이므로 "매수/매도" 가 아니라
 * "강세/약세" 로 쓴다. 실행 여부는 아래 실행 게이트 블록이 따로 말한다.
 */
const DIRECTION_META: Record<SignalDirection, { label: string; color: string }> = {
  BULLISH: { label: '강세', color: '#10b981' },
  BEARISH: { label: '약세', color: '#ef4444' },
  NEUTRAL: { label: '중립', color: '#f59e0b' },
}

/**
 * 엔진의 촉매 유형 코드 → 한국어.
 *
 * 엔진이 같은 뜻을 대문자(EARNINGS_REPORT)와 소문자(earnings_report) 두 표기로
 * 보내는 것을 실측했다. 조회 전에 대문자로 맞춘다.
 * 모르는 코드는 숨기지 않고 코드 그대로 보여준다.
 */
const CATALYST_LABELS: Record<string, string> = {
  EARNINGS_REPORT: '실적 발표',
  EARNINGS_GROWTH: '실적 성장',
  EARNINGS_GUIDANCE_UPGRADE: '가이던스 상향',
  EARNINGS_GUIDANCE_DOWNGRADE: '가이던스 하향',
  EARNINGS_MISS: '실적 미달',
  GUIDANCE: '가이던스',
  MARGIN_EXPANSION: '마진 개선',
  MARGIN_COMPRESSION: '마진 악화',
  PRODUCT_LAUNCH: '신제품',
  MACRO: '거시 환경',
  UNCLASSIFIED: '분류 안 됨',
}

/**
 * 실행 게이트의 `action` 표기.
 *
 * 이 값은 <b>방향이 아니라 실행 허용 여부</b>다. 화면에서 "매수/매도" 로 읽히면
 * 판단(강세/약세)과 뒤섞이므로, 실행 관점의 말로 옮긴다.
 */
const ACTION_LABELS: Record<string, string> = {
  AVOID: '실행 보류',
  HOLD: '관망',
  BUY: '진입 가능',
  SELL: '청산 우선',
  WATCH: '관찰',
}

/** 게이트 판정 코드 표기. */
const GATE_RESULT_LABELS: Record<string, string> = {
  pass: '통과',
  soft_block: '조건부 보류',
  hard_block: '차단',
}

/** 파급 영향 방향별 색. 모르는 값(null)은 회색 — 호재로 칠하지 않는다. */
const IMPACT_COLORS: Record<ImpactDirection, string> = {
  positive: '#10b981',
  negative: '#ef4444',
  mixed: '#f59e0b',
  neutral: '#64748b',
}

/** 기관 등급 A~E 색. */
function gradeColor(grade: string | null): string {
  switch (grade) {
    case 'A': return '#10b981'
    case 'B': return '#34d399'
    case 'C': return '#f59e0b'
    case 'D': return '#fb923c'
    case 'E': return '#ef4444'
    default:  return '#64748b'
  }
}

function pct(value: number | null): string {
  return value === null ? '—' : `${Math.round(value * 100)}%`
}

function price(value: number | null): string {
  return value === null ? '—' : value.toFixed(2)
}

/** ISO-8601 → HH:MM:SS. 파싱 실패하면 원문을 그대로 보여준다(값을 지어내지 않는다). */
function formatGeneratedAt(iso: string): string {
  const parsed = new Date(iso)
  return Number.isNaN(parsed.getTime()) ? iso : parsed.toLocaleTimeString('ko-KR', { hour12: false })
}

function signedPct(value: number | null): string {
  return value === null ? '—' : `${value.toFixed(1)}%`
}

interface MeterProps {
  label: string
  value: number | null
  color: string
}

function Meter({ label, value, color }: MeterProps) {
  return (
    <div className="flex items-center gap-2">
      <span className="text-[9.5px] text-text-tertiary shrink-0" style={{ width: 34 }}>
        {label}
      </span>
      {/* 값이 없으면 0% 막대로 그리지 않는다 — 0 과 미상은 다른 이야기다. */}
      <div
        className="flex-1 h-[3px] rounded-full bg-surface-2"
        style={
          value === null
            ? { backgroundImage: 'repeating-linear-gradient(90deg,#334155 0 3px,transparent 3px 6px)' }
            : undefined
        }
      >
        {value !== null && (
          <div
            className="h-full rounded-full transition-all duration-700"
            style={{ width: `${value * 100}%`, background: color }}
          />
        )}
      </div>
      <span className="num text-[10px] font-semibold shrink-0 w-8 text-right" style={{ color }}>
        {pct(value)}
      </span>
    </div>
  )
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <div className="text-[9.5px] font-semibold text-text-tertiary uppercase tracking-[0.12em] pt-0.5">
      {children}
    </div>
  )
}

interface Props {
  summary: EarningsSummary
}

/**
 * EarningsSummaryPanel — 어닝콜이 끝난 뒤의 종합 판단 (Contract 4.7).
 *
 * <p>구성 원칙 두 가지.
 *
 * <p>첫째, <b>판단과 실행 게이트를 분리한다.</b> 엔진의 `action` 은 방향이 아니라
 * "이 판단대로 움직여도 되는가" 의 답이라, 뉴스 근거가 없으면 강세 판단에도 회피가 붙는다.
 * 한 줄에 그리면 고장 난 것으로 읽히므로 블록을 나누고 사유를 함께 보여준다.
 *
 * <p>둘째, <b>없는 값을 0 으로 채우지 않는다.</b> 손절 계획이 산출되지 않았으면 0 원이
 * 아니라 사유를 보여준다. 경고 문구도 감추지 않는다 — 검증되지 않은 판단을 검증된 것처럼
 * 보이게 하는 것이 이 화면이 할 수 있는 가장 나쁜 일이다.
 */
export default function EarningsSummaryPanel({ summary }: Props) {
  const { judgment, gate, evasion, impactChain, riskPlan, warnings } = summary
  // 부가 정보를 못 가져온 것과 엔진이 "해당 없음" 이라 답한 것은 다른 이야기다.
  // 전자를 말없이 비워 두면 회피 지표가 없는 어닝콜처럼 보인다.
  const intelligenceFailed = summary.intelligenceAvailable === false
  const dir = DIRECTION_META[judgment.direction]
  const catalyst = judgment.catalystType
    ? CATALYST_LABELS[judgment.catalystType.toUpperCase()] ?? judgment.catalystType
    : null

  return (
    <div className="flex-1 flex flex-col min-h-0 overflow-y-auto px-3 py-2.5 gap-3">
      {/* ── 판단 ─────────────────────────────────────────────────────────── */}
      <div className="flex items-start justify-between gap-2">
        <div className="flex flex-col gap-0.5 min-w-0">
          <span className="num text-[24px] font-bold leading-none" style={{ color: dir.color }}>
            {dir.label}
          </span>
          {catalyst && (
            <span className="text-[9.5px] text-text-tertiary mt-1">{catalyst}</span>
          )}
        </div>
        {gate?.institutionalGrade && (
          <div className="flex flex-col items-end shrink-0">
            <span
              className="num text-[20px] font-bold leading-none"
              style={{ color: gradeColor(gate.institutionalGrade) }}
            >
              {gate.institutionalGrade}
            </span>
            <span className="text-[10px] text-text-tertiary mt-0.5">
              기관 등급
              {gate.institutionalGradeScore !== null &&
                ` ${Math.round(gate.institutionalGradeScore)}`}
            </span>
          </div>
        )}
      </div>

      <div className="flex flex-col gap-1.5">
        <Meter label="강도" value={judgment.magnitude} color={dir.color} />
        <Meter label="신뢰도" value={judgment.confidence} color={dir.color} />
      </div>

      {judgment.rationale && (
        <p className="text-[10px] leading-relaxed text-text-secondary">{judgment.rationale}</p>
      )}

      {/* ── 실행 게이트 ───────────────────────────────────────────────────── */}
      {gate &&
        (gate.action ||
          gate.positionIntentKo ||
          gate.noTradeSummaryKo ||
          gate.counterThesisKo ||
          gate.riskFlagsKo.length > 0) && (
        <div className="flex flex-col gap-1.5 rounded border border-border-subtle bg-surface-2 px-2.5 py-2">
          <div className="flex items-center justify-between gap-2">
            <SectionTitle>실행 판단</SectionTitle>
            {/*
              action 은 엔진이 항상 채우는 반면 아래 한국어 설명들은 비어 있을 수 있다.
              설명이 없다고 이 배지까지 빠지면, 강세 판단 옆에서 "실행 보류" 가 통째로
              사라져 판단만 남는다 — 이 화면이 가장 피해야 할 모습이다.
            */}
            {gate.action && (
              <span
                className="shrink-0 px-1.5 py-px rounded text-[10px] font-bold tracking-[0.04em]"
                style={{ color: '#f59e0b', background: 'rgba(245,158,11,0.12)' }}
              >
                {ACTION_LABELS[gate.action] ?? gate.action}
                {gate.gateResult && ` · ${GATE_RESULT_LABELS[gate.gateResult] ?? gate.gateResult}`}
              </span>
            )}
          </div>
          {gate.positionIntentKo && (
            <div className="text-[10px] text-text-primary leading-snug">{gate.positionIntentKo}</div>
          )}
          {gate.noTradeSummaryKo && (
            <div className="text-[9.5px] text-text-tertiary leading-snug">
              보류 사유 · {gate.noTradeSummaryKo}
            </div>
          )}
          {gate.counterThesisKo && (
            <div className="text-[9.5px] text-text-tertiary leading-snug">
              반대 논거 · {gate.counterThesisKo}
            </div>
          )}
          {gate.riskFlagsKo.length > 0 && (
            <ul className="flex flex-col gap-0.5">
              {gate.riskFlagsKo.map((flag, i) => (
                <li key={`${i}-${flag}`} className="text-[9.5px] text-text-tertiary leading-snug">
                  · {flag}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {/* ── 질문 회피 ─────────────────────────────────────────────────────── */}
      {evasion && (
        <div className="flex flex-col gap-1.5">
          <SectionTitle>질문 회피</SectionTitle>
          <Meter
            label="회피도"
            value={evasion.evasionScore}
            color={evasion.evasionScore !== null && evasion.evasionScore >= 0.5 ? '#f59e0b' : '#64748b'}
          />
          {evasion.missingTopics.length > 0 && (
            <div className="flex flex-wrap gap-1">
              <span className="text-[9.5px] text-text-tertiary">답변에서 빠진 주제</span>
              {evasion.missingTopics.map((topic, i) => (
                <span
                  key={`${i}-${topic}`}
                  className="px-1.5 py-px rounded text-[9px] font-semibold"
                  style={{ color: '#f59e0b', background: 'rgba(245,158,11,0.12)' }}
                >
                  {topic}
                </span>
              ))}
            </div>
          )}
          {evasion.pivotDetected && (
            <div className="text-[9.5px]" style={{ color: '#f59e0b' }}>
              답변이 다른 주제로 전환되었습니다.
            </div>
          )}
          {/* 숫자만 놓고 왜 그 점수인지 말하지 않으면 지표를 읽을 수 없다. */}
          {evasion.rationaleKo && (
            <div className="text-[9.5px] text-text-tertiary leading-snug">{evasion.rationaleKo}</div>
          )}
        </div>
      )}

      {/* ── 손절 / 익절 ───────────────────────────────────────────────────── */}
      {riskPlan && (
        <div className="flex flex-col gap-1.5">
          <div className="flex items-center justify-between gap-2">
            <SectionTitle>손절 · 익절 계획</SectionTitle>
            {/* LONG/SHORT 를 모르면 손절가의 위/아래를 해석할 수 없다. */}
            {riskPlan.available === true && riskPlan.direction && (
              <span className="num text-[9.5px] text-text-tertiary">
                {riskPlan.direction}
                {riskPlan.referencePrice !== null && ` · 기준 ${price(riskPlan.referencePrice)}`}
              </span>
            )}
          </div>
          {riskPlan.available === true ? (
            <>
              <div className="grid grid-cols-3 gap-1.5">
                <PlanCell label="손절" value={price(riskPlan.stopLoss)} sub={signedPct(riskPlan.stopPct)} color="#ef4444" />
                <PlanCell label="1차 익절" value={price(riskPlan.takeProfit1)} sub={signedPct(riskPlan.takeProfit1Pct)} color="#10b981" />
                <PlanCell label="2차 익절" value={price(riskPlan.takeProfit2)} sub={signedPct(riskPlan.takeProfit2Pct)} color="#10b981" />
              </div>
              <div className="flex items-center justify-between text-[9.5px] text-text-tertiary">
                <span>
                  손익비 {riskPlan.riskReward1 === null ? '—' : `${riskPlan.riskReward1.toFixed(2)}:1`}
                </span>
                {riskPlan.timeStopDays !== null && <span>시간 손절 {riskPlan.timeStopDays}일</span>}
              </div>
              {riskPlan.invalidationText && (
                <div className="text-[9.5px] text-text-tertiary leading-snug">
                  {riskPlan.invalidationText}
                </div>
              )}
            </>
          ) : riskPlan.available === false ? (
            // 값이 없다고 0 으로 채우면 없는 계획이 있는 것처럼 보인다.
            <div className="text-[9.5px] text-text-tertiary leading-snug">
              {riskPlan.invalidationText ?? '가격 정보가 없어 계획을 산출하지 못했습니다.'}
            </div>
          ) : (
            // available 이 아예 없는 경우. "가격 정보가 없다" 고 단정하면 사실이 아닌
            // 사유를 지어내는 것이 된다 — 계약이 어긋났다고만 말한다.
            <div className="text-[9.5px] text-text-tertiary leading-snug">
              계획 산출 여부를 확인할 수 없습니다(엔진 응답 형식 확인 필요).
            </div>
          )}
        </div>
      )}

      {/* ── 파급효과 ──────────────────────────────────────────────────────── */}
      {impactChain.length > 0 && (
        <div className="flex flex-col gap-1">
          <SectionTitle>파급 영향 후보</SectionTitle>
          {impactChain.map((link) => (
            <div key={link.ticker} className="flex items-center gap-2" title={link.rationaleKo ?? undefined}>
              <span className="num text-[10px] font-semibold text-text-primary w-11 shrink-0">
                {link.ticker}
              </span>
              <div
                className="flex-1 h-[3px] rounded-full bg-surface-2"
                // 점수가 없다는 건 "영향 0" 이 아니라 "잴 근거가 없었다" 는 뜻이다.
                // 빈 막대로 두면 0% 와 구별되지 않으므로 빗금 트랙으로 표시한다.
                style={
                  link.impactScore === null
                    ? {
                        backgroundImage:
                          'repeating-linear-gradient(45deg, #334155 0 3px, transparent 3px 6px)',
                      }
                    : undefined
                }
              >
                {link.impactScore !== null && (
                  <div
                    className="h-full rounded-full"
                    style={{
                      width: `${link.impactScore * 100}%`,
                      // 모르는 방향을 초록으로 칠하면 없는 호재 판단을 만들어내는 셈이다.
                      background: link.direction ? IMPACT_COLORS[link.direction] : '#64748b',
                    }}
                  />
                )}
              </div>
              <span className="num text-[9.5px] text-text-tertiary w-8 text-right">
                {pct(link.impactScore)}
              </span>
            </div>
          ))}
        </div>
      )}

      {intelligenceFailed && (
        <div className="text-[9.5px] text-text-tertiary leading-snug rounded border border-border-subtle px-2.5 py-2">
          회피 지표 · 파급 영향 · 손절 계획을 가져오지 못했습니다. 판단만 표시합니다.
        </div>
      )}

      {/* ── 엔진 경고 ─────────────────────────────────────────────────────── */}
      {warnings.length > 0 && (
        <div
          className="rounded px-2.5 py-2 flex flex-col gap-0.5"
          style={{ background: 'rgba(245,158,11,0.10)', border: '1px solid rgba(245,158,11,0.30)' }}
        >
          {warnings.map((warning, i) => (
            <div key={`${i}-${warning}`} className="text-[9.5px] leading-snug" style={{ color: '#f59e0b' }}>
              {warning}
            </div>
          ))}
        </div>
      )}

      {/*
        판단에 실제로 쓰인 모델과 회차 식별자.
        모델명은 폴백 여부를 눈으로 확인하는 용도이고, 회차 정보는 재생을 두 번 돌렸을 때
        화면의 판단이 이번 회차 것인지 확인하는 용도다. 둘 다 읽을 수 있어야 쓸모가 있으므로
        disabled 색은 쓰지 않는다.
      */}
      <div className="flex items-center justify-between gap-2 text-[10px] text-text-tertiary pt-0.5">
        <span className="num truncate">{judgment.modelVersion ?? '모델 미상'}</span>
        {summary.generatedAt && (
          <span className="num shrink-0">{formatGeneratedAt(summary.generatedAt)}</span>
        )}
      </div>
    </div>
  )
}

function PlanCell({
  label,
  value,
  sub,
  color,
}: {
  label: string
  value: string
  sub: string
  color: string
}) {
  return (
    <div className="flex flex-col rounded bg-surface-2 border border-border-subtle px-1.5 py-1">
      <span className="text-[10px] text-text-tertiary">{label}</span>
      {/* 이 패널에서 손실 한도를 말하는 유일한 숫자다. 다른 값보다 크게 둔다. */}
      <span className="num text-[13px] font-semibold" style={{ color }}>
        {value}
      </span>
      <span className="num text-[10px] text-text-tertiary">{sub}</span>
    </div>
  )
}
