import type { EarningsHistoryRow } from '../../fixtures/companyDetail.dev-mock'

interface EarningsHistoryTableProps {
  rows: EarningsHistoryRow[]
  className?: string
}

/**
 * EarningsHistoryTable — CompanyDrawer 안 어닝 히스토리 미니 테이블 (5컬럼).
 *
 * 디자인 매칭: CompanyDrawer.html `.etable`.
 *  - 4~5행 컴팩트.
 *  - surprise / 당일: 부호로 색 결정 (+ → buy, − → sell).
 *  - 부호는 fixture 가 plain string 으로 보유 ("+17.2%", "−1.7%") — 색은 첫 문자로 판정.
 */
export default function EarningsHistoryTable({
  rows,
  className = '',
}: EarningsHistoryTableProps) {
  if (rows.length === 0) {
    return (
      <div className={`text-[11px] text-text-disabled py-2 ${className}`}>
        어닝 히스토리가 없습니다.
      </div>
    )
  }

  return (
    <table className={`w-full border-collapse text-[11px] table-fixed ${className}`}>
      <thead>
        <tr>
          <Th align="left">분기</Th>
          <Th>EPS 예상</Th>
          <Th>EPS 실제</Th>
          <Th>Surprise</Th>
          <Th>당일</Th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.quarter}>
            <td className="num text-left text-text-primary text-[10px] font-medium tracking-[0.06em] py-1.5 px-1 border-b border-border-subtle">
              {r.quarter}
            </td>
            <td className="num text-right py-1.5 px-1 border-b border-border-subtle text-text-secondary tabular-nums">
              {r.epsEstimate}
            </td>
            <td className="num text-right py-1.5 px-1 border-b border-border-subtle text-text-secondary tabular-nums">
              {r.epsActual}
            </td>
            <PercentTd value={r.surprisePercent} />
            <PercentTd value={r.priceReactionPercent} />
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function Th({
  children,
  align = 'right',
}: {
  children: React.ReactNode
  align?: 'left' | 'right'
}) {
  return (
    <th
      className={`text-[9px] font-semibold text-text-tertiary uppercase tracking-[0.12em]
                  py-1.5 px-1 border-b border-border-subtle ${
                    align === 'left' ? 'text-left' : 'text-right'
                  }`}
    >
      {children}
    </th>
  )
}

function PercentTd({ value }: { value: string }) {
  // 부호 판정: '+' → buy, '−' / '-' → sell, 그 외 → tertiary
  const first = value.trim()[0]
  const cls =
    first === '+'
      ? 'text-buy'
      : first === '−' || first === '-'
        ? 'text-sell'
        : 'text-text-tertiary'
  return (
    <td
      className={`num text-right py-1.5 px-1 border-b border-border-subtle tabular-nums ${cls}`}
    >
      {value}
    </td>
  )
}
