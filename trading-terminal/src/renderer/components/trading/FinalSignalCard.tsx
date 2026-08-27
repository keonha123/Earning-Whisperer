import { useState } from 'react'
import type { EarningsEvaluation } from '../../fixtures/earningsEvaluation.dev-mock'

type TradeAction = 'BUY' | 'HOLD' | 'SELL'
type ModalState = 'closed' | 'input' | 'sending' | 'done'
type OrderType = '시장가' | '지정가'

interface Props {
  signal: EarningsEvaluation['signal']
  buyScore: number
  sellScore: number
  strength: string
  rationale: string
  ticker: string
}

const ACTION_CONFIG: Record<TradeAction, { label: string; color: string }> = {
  BUY:  { label: '매수', color: '#10b981' },
  HOLD: { label: '관망', color: '#f59e0b' },
  SELL: { label: '매도', color: '#f87171' },
}

export default function FinalSignalCard({
  signal,
  buyScore,
  sellScore,
  strength,
  rationale,
  ticker,
}: Props) {
  const [selected, setSelected] = useState<TradeAction>(signal)
  const [modalState, setModalState] = useState<ModalState>('closed')
  const [pendingAction, setPendingAction] = useState<TradeAction>('BUY')
  const [orderType, setOrderType] = useState<OrderType>('시장가')
  const [quantity, setQuantity] = useState(1)

  function handleActionClick(action: TradeAction) {
    setSelected(action)
    if (action === 'HOLD') return
    setPendingAction(action)
    setOrderType('시장가')
    setQuantity(1)
    setModalState('input')
  }

  function handleSubmit() {
    setModalState('sending')
    setTimeout(() => setModalState('done'), 3000)
  }

  function handleClose() {
    setModalState('closed')
  }

  const signalConf = ACTION_CONFIG[signal]
  const orderConf = ACTION_CONFIG[pendingAction]

  return (
    <>
      <div className="flex flex-col border border-border-subtle rounded bg-surface-1">
        {/* 헤더 */}
        <div className="h-8 px-3 flex items-center border-b border-border-subtle shrink-0">
          <span
            className="w-1.5 h-1.5 rounded-sm mr-2 shrink-0"
            style={{ background: signalConf.color, boxShadow: `0 0 6px ${signalConf.color}80` }}
          />
          <span className="text-[10.5px] font-semibold text-text-secondary uppercase tracking-[0.1em]">
            최종 매매 시그널
          </span>
        </div>

        {/* 시그널 배지 + 매수/매도 스코어 */}
        <div className="px-3 pt-3 pb-2 flex items-start justify-between gap-2">
          <div className="flex flex-col gap-0.5">
            <span className="num text-[22px] font-bold leading-none" style={{ color: signalConf.color }}>
              {signalConf.label}
            </span>
            <span className="text-[9.5px] text-text-tertiary mt-0.5">{strength}</span>
          </div>

          <div className="flex flex-col gap-1 items-end pt-0.5">
            <div className="flex items-center gap-1.5">
              <span className="text-[9px] text-text-tertiary">매수</span>
              <span className="num text-[10px] font-semibold text-buy">{buyScore}</span>
            </div>
            <div className="w-20 h-[4px] rounded-full bg-surface-2 overflow-hidden">
              <div className="h-full rounded-full bg-buy" style={{ width: `${buyScore}%` }} />
            </div>
            <div className="flex items-center gap-1.5">
              <span className="text-[9px] text-text-tertiary">매도</span>
              <span className="num text-[10px] font-semibold text-sell">{sellScore}</span>
            </div>
          </div>
        </div>

        {/* 판단 문구 */}
        <div className="px-3 pb-3 text-[10px] text-text-secondary leading-[1.6] border-b border-border-subtle">
          {rationale}
        </div>

        {/* 매매 선택 버튼 */}
        <div className="px-3 py-2.5 flex gap-1.5">
          {(['BUY', 'HOLD', 'SELL'] as TradeAction[]).map((action) => {
            const conf = ACTION_CONFIG[action]
            const isSelected = selected === action
            return (
              <button
                key={action}
                type="button"
                onClick={() => handleActionClick(action)}
                className="flex-1 py-1.5 rounded text-[11px] font-bold border transition-all duration-150"
                style={
                  isSelected
                    ? { color: conf.color, borderColor: conf.color, background: `${conf.color}26` }
                    : { color: '#6b7280', borderColor: '#374151', background: 'transparent' }
                }
              >
                {conf.label}
              </button>
            )
          })}
        </div>
      </div>

      {/* 주문 모달 — fixed 오버레이 */}
      {modalState !== 'closed' && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
          <div className="w-80 bg-surface-0 border border-border-strong rounded-xl shadow-2xl overflow-hidden">

            {/* 주문 입력 */}
            {modalState === 'input' && (
              <>
                <div className="h-12 px-4 flex items-center justify-between border-b border-border-subtle">
                  <span className="text-[13px] font-semibold text-text-primary">
                    {ticker} {orderConf.label}
                  </span>
                  <button
                    type="button"
                    onClick={handleClose}
                    className="w-6 h-6 flex items-center justify-center rounded text-text-tertiary hover:text-text-primary hover:bg-surface-2 transition-colors"
                  >
                    ×
                  </button>
                </div>

                <div className="p-4 flex flex-col gap-5">
                  {/* 주문 유형 */}
                  <div className="flex flex-col gap-2">
                    <span className="text-[10px] text-text-tertiary uppercase tracking-[0.1em]">주문 유형</span>
                    <div className="flex gap-1.5">
                      {(['시장가', '지정가'] as OrderType[]).map((type) => (
                        <button
                          key={type}
                          type="button"
                          onClick={() => setOrderType(type)}
                          className="flex-1 py-2 rounded border text-[11px] font-medium transition-all"
                          style={
                            orderType === type
                              ? { color: orderConf.color, borderColor: orderConf.color, background: `${orderConf.color}18` }
                              : { color: '#6b7280', borderColor: '#374151', background: 'transparent' }
                          }
                        >
                          {type}
                        </button>
                      ))}
                    </div>
                  </div>

                  {/* 주문 수량 */}
                  <div className="flex flex-col gap-2">
                    <span className="text-[10px] text-text-tertiary uppercase tracking-[0.1em]">주문 수량</span>
                    <div className="flex items-center gap-2 bg-surface-1 border border-border-subtle rounded-lg px-3 py-2">
                      <button
                        type="button"
                        onClick={() => setQuantity((q) => Math.max(1, q - 1))}
                        className="w-6 h-6 flex items-center justify-center rounded text-text-secondary hover:text-text-primary hover:bg-surface-2 transition-colors text-[16px] leading-none"
                      >
                        −
                      </button>
                      <span className="flex-1 text-center num text-[15px] font-semibold text-text-primary">
                        {quantity}
                      </span>
                      <button
                        type="button"
                        onClick={() => setQuantity((q) => q + 1)}
                        className="w-6 h-6 flex items-center justify-center rounded text-text-secondary hover:text-text-primary hover:bg-surface-2 transition-colors text-[16px] leading-none"
                      >
                        +
                      </button>
                    </div>
                    <span className="text-[10px] text-text-tertiary">
                      {orderType === '시장가' ? '현재가로 즉시 집행' : '지정가 입력 후 집행'}
                    </span>
                  </div>
                </div>

                <div className="px-4 pb-4">
                  <button
                    type="button"
                    onClick={handleSubmit}
                    className="w-full py-2.5 rounded-lg text-[12px] font-bold transition-opacity hover:opacity-90"
                    style={{ background: orderConf.color, color: '#0b1017' }}
                  >
                    {orderConf.label} 주문 전송
                  </button>
                </div>
              </>
            )}

            {/* 전송 중 */}
            {modalState === 'sending' && (
              <div className="h-52 flex flex-col items-center justify-center gap-4">
                <div
                  className="w-10 h-10 rounded-full border-2 animate-spin"
                  style={{
                    borderTopColor: orderConf.color,
                    borderRightColor: 'transparent',
                    borderBottomColor: 'transparent',
                    borderLeftColor: 'transparent',
                  }}
                />
                <div className="flex flex-col items-center gap-1">
                  <span className="text-[13px] font-semibold text-text-primary">주문 전송 중...</span>
                  <span className="text-[10px] text-text-tertiary">거래소로 주문을 전달하고 있습니다</span>
                </div>
              </div>
            )}

            {/* 전송 완료 */}
            {modalState === 'done' && (
              <div className="h-52 flex flex-col items-center justify-center gap-4">
                <div
                  className="w-11 h-11 rounded-full flex items-center justify-center"
                  style={{ background: `${orderConf.color}20`, border: `1.5px solid ${orderConf.color}` }}
                >
                  <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
                    <path
                      d="M3.5 9.5l4 4 7-8"
                      stroke={orderConf.color}
                      strokeWidth="2.2"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    />
                  </svg>
                </div>
                <div className="flex flex-col items-center gap-1">
                  <span className="text-[14px] font-bold text-text-primary">주문 전송 완료</span>
                  <span className="text-[10px] text-text-tertiary text-center leading-relaxed">
                    거래소에 주문이 접수되었습니다<br />체결 결과는 별도로 확인하세요
                  </span>
                </div>
                <button
                  type="button"
                  onClick={handleClose}
                  className="px-5 py-1.5 rounded border border-border-subtle text-[11px] text-text-secondary hover:text-text-primary hover:border-border-strong transition-colors"
                >
                  닫기
                </button>
              </div>
            )}
          </div>
        </div>
      )}
    </>
  )
}
