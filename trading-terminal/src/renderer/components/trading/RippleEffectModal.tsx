import Modal from '../common/Modal'
import type { RippleNode, RippleEdge } from '../../fixtures/rippleEffect.dev-mock'

interface RippleEffectModalProps {
  open: boolean
  onClose: () => void
  nodes: readonly RippleNode[]
  edges: readonly RippleEdge[]
  /** 어닝콜 발원 종목 (중심 노드 ID). */
  centerTicker: string
}

/** impact 값에 따른 색상. */
function impactColor(impact: number): string {
  if (impact >= 0.5) return '#10b981'   // 강 긍정 — buy green
  if (impact >= 0.1) return '#34d399'   // 약 긍정
  if (impact <= -0.3) return '#f87171'  // 강 부정 — sell red
  if (impact < 0) return '#fca5a5'      // 약 부정
  return '#94a3b8'                      // 중립
}

function impactLabel(impact: number): string {
  if (impact >= 0.6) return '강 수혜'
  if (impact >= 0.2) return '수혜'
  if (impact <= -0.3) return '부정'
  if (impact < 0) return '약 부정'
  return '중립'
}

/**
 * RippleEffectModal — 어닝콜 파급효과 시각화 (중앙 대형 모달).
 *
 * SVG 방사형 네트워크 그래프 + 우측 종목 리스트.
 * 노드 좌표는 fixture 의 cx/cy (0–100%) → SVG viewBox 비율 매핑.
 * 신규 의존성 없음 — 기존 SVG 패턴(ChartPane) 일관.
 */
export default function RippleEffectModal({
  open,
  onClose,
  nodes,
  edges,
  centerTicker,
}: RippleEffectModalProps) {
  const VIEW = 300
  const nodeById = new Map(nodes.map((n) => [n.id, n]))

  return (
    <Modal open={open} onClose={onClose} ariaLabel="어닝콜 파급효과 분석">
      <div style={{ width: 780 }} className="flex flex-col max-h-[85vh]">
        {/* 헤더 */}
        <div className="h-12 px-5 flex items-center justify-between border-b border-border-subtle shrink-0">
          <div className="flex items-center gap-2.5">
            <span
              className="w-2 h-2 rounded-sm"
              style={{ background: '#10b981', boxShadow: '0 0 8px rgba(16,185,129,0.5)' }}
            />
            <span className="text-[13px] font-semibold text-text-primary">
              어닝콜 파급효과 분석
            </span>
            <span className="num text-[11px] text-text-tertiary">· {centerTicker}</span>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="w-6 h-6 flex items-center justify-center rounded text-text-tertiary
                       hover:text-text-primary hover:bg-surface-2 transition-colors duration-100"
            aria-label="닫기"
          >
            <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.5">
              <path d="M2 2l8 8M10 2l-8 8" strokeLinecap="round" />
            </svg>
          </button>
        </div>

        {/* 바디: 그래프 + 리스트 */}
        <div className="flex flex-1 min-h-0 overflow-hidden">
          {/* SVG 네트워크 그래프 */}
          <div className="flex-1 min-w-0 p-4 flex items-center justify-center bg-surface-1 border-r border-border-subtle">
            <svg
              viewBox={`0 0 ${VIEW} ${VIEW}`}
              width="100%"
              height="100%"
              style={{ maxWidth: 340, maxHeight: 340 }}
              role="img"
              aria-label="서플라이체인 파급효과 네트워크"
            >
              {/* 엣지 */}
              {edges.map((e) => {
                const from = nodeById.get(e.from)
                const to = nodeById.get(e.to)
                if (!from || !to) return null
                const fx = (from.cx / 100) * VIEW
                const fy = (from.cy / 100) * VIEW
                const tx = (to.cx / 100) * VIEW
                const ty = (to.cy / 100) * VIEW
                const color = impactColor(to.impact)
                return (
                  <line
                    key={`${e.from}-${e.to}`}
                    x1={fx} y1={fy} x2={tx} y2={ty}
                    stroke={color}
                    strokeWidth={Math.abs(to.impact) * 2 + 0.5}
                    strokeOpacity={0.45}
                    strokeDasharray={to.impact < 0 ? '4 3' : undefined}
                  />
                )
              })}

              {/* 노드 */}
              {nodes.map((node) => {
                const x = (node.cx / 100) * VIEW
                const y = (node.cy / 100) * VIEW
                const isCenter = node.id === centerTicker
                const color = impactColor(node.impact)
                const r = isCenter ? 18 : 12

                return (
                  <g key={node.id}>
                    {/* glow ring */}
                    <circle
                      cx={x} cy={y} r={r + 5}
                      fill={color}
                      fillOpacity={0.1}
                    />
                    {/* 노드 원 */}
                    <circle
                      cx={x} cy={y} r={r}
                      fill="#0b1017"
                      stroke={color}
                      strokeWidth={isCenter ? 2 : 1.5}
                    />
                    {/* ticker 라벨 */}
                    <text
                      x={x} y={y + (isCenter ? 4 : 3.5)}
                      textAnchor="middle"
                      fontSize={isCenter ? 7 : 6}
                      fontWeight="700"
                      fill={color}
                      fontFamily="'SF Mono', 'Fira Code', monospace"
                    >
                      {node.ticker}
                    </text>
                    {/* impact 수치 (중심 제외) */}
                    {!isCenter && (
                      <text
                        x={x} y={y + r + 9}
                        textAnchor="middle"
                        fontSize={5}
                        fill={color}
                        fillOpacity={0.8}
                        fontFamily="'SF Mono', 'Fira Code', monospace"
                      >
                        {node.impact >= 0 ? '+' : ''}{Math.round(node.impact * 100)}%
                      </text>
                    )}
                  </g>
                )
              })}
            </svg>
          </div>

          {/* 종목 리스트 */}
          <div className="w-[280px] shrink-0 flex flex-col overflow-hidden">
            <div className="h-9 px-4 flex items-center border-b border-border-subtle shrink-0">
              <span className="text-[11px] font-semibold text-text-secondary uppercase tracking-[0.12em]">
                영향 종목
              </span>
            </div>
            <div className="flex-1 overflow-y-auto">
              {nodes
                .filter((n) => n.id !== centerTicker)
                .sort((a, b) => Math.abs(b.impact) - Math.abs(a.impact))
                .map((node) => {
                  const color = impactColor(node.impact)
                  return (
                    <div
                      key={node.id}
                      className="px-4 py-2.5 border-b border-border-subtle last:border-0 flex flex-col gap-1"
                    >
                      <div className="flex items-center justify-between gap-2">
                        <div className="flex items-center gap-2 min-w-0">
                          <span
                            className="num text-[11px] font-bold shrink-0"
                            style={{ color }}
                          >
                            {node.ticker}
                          </span>
                          <span className="text-[10px] text-text-tertiary truncate">
                            {node.name}
                          </span>
                        </div>
                        <span
                          className="shrink-0 px-1.5 py-px rounded text-[9px] font-bold border"
                          style={{ color, background: `${color}18`, borderColor: `${color}55` }}
                        >
                          {impactLabel(node.impact)}
                        </span>
                      </div>
                      <div className="text-[10px] text-text-tertiary leading-snug">
                        {node.relation}
                      </div>
                      <div className="text-[10px] text-text-secondary leading-snug">
                        {node.comment}
                      </div>
                      {/* impact 바 */}
                      <div className="flex items-center gap-1.5 pt-0.5">
                        <div className="flex-1 h-[2px] rounded-full bg-surface-2">
                          <div
                            className="h-full rounded-full"
                            style={{
                              width: `${Math.abs(node.impact) * 100}%`,
                              background: color,
                            }}
                          />
                        </div>
                        <span className="num text-[9px] text-text-tertiary">
                          {node.impact >= 0 ? '+' : ''}{(node.impact * 100).toFixed(0)}
                        </span>
                      </div>
                    </div>
                  )
                })}
            </div>
          </div>
        </div>

        {/* 푸터 범례 */}
        <div className="h-9 px-5 flex items-center gap-4 border-t border-border-subtle shrink-0">
          <span className="text-[10px] text-text-disabled">파급 강도:</span>
          {[
            { color: '#10b981', label: '강 수혜' },
            { color: '#34d399', label: '수혜' },
            { color: '#fca5a5', label: '약 부정' },
            { color: '#f87171', label: '부정' },
          ].map(({ color, label }) => (
            <span key={label} className="flex items-center gap-1">
              <span className="w-2 h-2 rounded-full" style={{ background: color }} />
              <span className="text-[10px] text-text-tertiary">{label}</span>
            </span>
          ))}
        </div>
      </div>
    </Modal>
  )
}
