import type { EvaluationScore } from '../../fixtures/earningsEvaluation.dev-mock'

interface Props {
  scores: readonly EvaluationScore[]
  totalScore: number
}

function scoreColor(score: number): string {
  if (score >= 85) return '#10b981'
  if (score >= 70) return '#f59e0b'
  return '#f87171'
}

export default function EarningsEvaluationCard({ scores, totalScore }: Props) {
  const totalColor = scoreColor(totalScore)

  return (
    <div className="flex flex-col border border-border-subtle rounded bg-surface-1 shrink-0">
      <div className="h-8 px-3 flex items-center border-b border-border-subtle">
        <span
          className="w-1.5 h-1.5 rounded-sm mr-2 shrink-0"
          style={{ background: '#a78bfa', boxShadow: '0 0 6px rgba(167,139,250,0.45)' }}
        />
        <span className="text-[10.5px] font-semibold text-text-secondary uppercase tracking-[0.1em]">
          어닝콜 종합 평가
        </span>
      </div>

      <div className="px-3 py-2.5 flex flex-col gap-2">
        {scores.map(({ label, score }) => {
          const c = scoreColor(score)
          return (
            <div key={label} className="flex items-center gap-2">
              <span className="text-[9.5px] text-text-tertiary shrink-0" style={{ width: 76 }}>
                {label}
              </span>
              <div className="flex-1 h-[3px] rounded-full bg-surface-2">
                <div
                  className="h-full rounded-full transition-all duration-700"
                  style={{ width: `${score}%`, background: c }}
                />
              </div>
              <span
                className="num text-[10px] font-semibold shrink-0 w-6 text-right"
                style={{ color: c }}
              >
                {score}
              </span>
            </div>
          )
        })}
      </div>

      <div className="px-3 py-2 border-t border-border-subtle flex items-center justify-between">
        <span className="text-[10px] text-text-tertiary">종합 점수</span>
        <span className="num text-[20px] font-bold leading-none" style={{ color: totalColor }}>
          {totalScore}
        </span>
      </div>
    </div>
  )
}
