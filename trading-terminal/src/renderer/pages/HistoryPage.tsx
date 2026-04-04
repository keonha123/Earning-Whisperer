import { useEffect, useState } from 'react'
import { ipc, IPC_CHANNELS } from '../lib/ipc'

interface Trade {
  id: number
  ticker: string
  side: 'BUY' | 'SELL'
  orderQty: number
  executedQty: number
  executedPrice: number | null
  status: string
  createdAt: string // ISO 8601
}

export default function HistoryPage() {
  const [trades, setTrades] = useState<Trade[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    loadTrades()
  }, [])

  async function loadTrades() {
    setLoading(true)
    try {
      const data = await ipc.invoke<{ content: Trade[] }>(IPC_CHANNELS.TRADES_GET, { page: 0, size: 20 })
      setTrades(data.content ?? [])
    } catch (e) {
      console.error('거래 내역 조회 실패:', e)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <h2 className="text-md font-semibold text-text-primary">체결 내역</h2>
        <button className="btn-ghost text-sm px-3 py-1.5" onClick={loadTrades}>↻ 새로고침</button>
      </div>

      <div className="card p-0 overflow-hidden">
        <table className="w-full">
          <thead>
            <tr className="border-b border-[#2a3344]">
              {['일시', '종목', '매수/매도', '수량', '체결가', '상태'].map((h) => (
                <th key={h} className="text-left px-4 py-2.5 text-xs font-medium text-text-disabled uppercase tracking-wide">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {loading ? (
              Array.from({ length: 5 }).map((_, i) => (
                <tr key={i} className="border-b border-[#1e2738]">
                  {Array.from({ length: 6 }).map((_, j) => (
                    <td key={j} className="px-4 py-3">
                      <div className="h-4 bg-[#1c2330] rounded animate-pulse" />
                    </td>
                  ))}
                </tr>
              ))
            ) : trades.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-4 py-8 text-center text-text-disabled text-sm">
                  체결 내역이 없습니다
                </td>
              </tr>
            ) : (
              trades.map((t) => (
                <tr key={t.id} className="border-b border-[#1e2738] hover:bg-[#1c2330] transition-colors">
                  <td className="px-4 py-3 text-text-secondary text-xs num">
                    {new Date(t.createdAt).toLocaleString('ko-KR')}
                  </td>
                  <td className="px-4 py-3 font-medium text-text-primary num">{t.ticker}</td>
                  <td className="px-4 py-3">
                    <span className={t.side === 'BUY' ? 'badge-buy' : 'badge-sell'}>{t.side}</span>
                  </td>
                  <td className="px-4 py-3 num text-text-primary">{t.executedQty}</td>
                  <td className="px-4 py-3 num text-text-primary">${t.executedPrice?.toFixed(2) ?? '-'}</td>
                  <td className="px-4 py-3">
                    <span className={t.status === 'EXECUTED' ? 'badge-success' : 'badge-danger'}>
                      {t.status === 'EXECUTED' ? '체결' : '실패'}
                    </span>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
