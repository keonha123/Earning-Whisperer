import { useEffect, useState } from 'react'
import { ipc, IPC_CHANNELS } from '../lib/ipc'
import Pagination from '../components/common/Pagination'

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

const PAGE_SIZE = 20

export default function HistoryPage() {
  const [trades, setTrades] = useState<Trade[]>([])
  const [loading, setLoading] = useState(true)
  const [page, setPage] = useState(0)
  const [totalPages, setTotalPages] = useState(0)

  useEffect(() => {
    loadTrades(0)
  }, [])

  async function loadTrades(p: number) {
    setLoading(true)
    try {
      const data = await ipc.invoke<{ content: Trade[]; totalPages: number }>(
        IPC_CHANNELS.TRADES_GET,
        { page: p, size: PAGE_SIZE }
      )
      setTrades(data.content ?? [])
      setTotalPages(data.totalPages ?? 0)
    } catch (e) {
      console.error('거래 내역 조회 실패:', e)
    } finally {
      setLoading(false)
    }
  }

  function handlePageChange(p: number) {
    setPage(p)
    loadTrades(p)
  }

  // 현재 페이지 기준 집계 (페이지네이션으로 인해 전체 수는 알 수 없음)
  const buyCount = trades.filter((t) => t.side === 'BUY').length
  const sellCount = trades.filter((t) => t.side === 'SELL').length

  return (
    <div className="flex flex-col gap-3 h-full">
      {/* 요약 + 헤더 */}
      <div className="flex items-center justify-between shrink-0">
        <div className="flex items-center gap-4">
          <span className="text-sm font-semibold text-text-primary">체결 내역</span>
          <div className="flex items-center gap-2">
            <SummaryChip label="BUY" value={buyCount} color="text-buy" />
            <SummaryChip label="SELL" value={sellCount} color="text-sell" />
          </div>
        </div>
        <button
          className="flex items-center gap-1.5 text-xs text-text-disabled hover:text-text-primary
                     transition-colors duration-100 px-2 py-1 rounded hover:bg-[#1c2330]"
          onClick={() => loadTrades(page)}
        >
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none"
               stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M21 2v6h-6" />
            <path d="M3 12a9 9 0 0115-6.7L21 8" />
            <path d="M3 22v-6h6" />
            <path d="M21 12a9 9 0 01-15 6.7L3 16" />
          </svg>
          새로고침
        </button>
      </div>

      {/* 테이블 카드 */}
      <div className="card p-0 overflow-hidden flex flex-col flex-1 min-h-0">
        <div className="overflow-y-auto flex-1">
          <table className="w-full">
            <thead className="sticky top-0 z-10 bg-[#161b22]">
              <tr className="border-b border-[#2a3344]">
                {[
                  { label: '일시',   cls: 'w-36' },
                  { label: '종목',   cls: 'w-20' },
                  { label: '방향',   cls: 'w-20' },
                  { label: '수량',   cls: 'w-16 text-right' },
                  { label: '체결가', cls: 'w-24 text-right' },
                  { label: '상태',   cls: 'w-20' },
                ].map(({ label, cls }) => (
                  <th
                    key={label}
                    className={`px-4 py-2.5 text-left text-[10px] font-semibold
                               text-text-disabled uppercase tracking-widest ${cls}`}
                  >
                    {label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {loading ? (
                Array.from({ length: 8 }).map((_, i) => (
                  <tr key={i} className="border-b border-[#1e2738]">
                    {Array.from({ length: 6 }).map((_, j) => (
                      <td key={j} className="px-4 py-3">
                        <div className={`h-3.5 bg-[#1c2330] rounded animate-pulse
                                        ${j === 0 ? 'w-28' : j === 1 ? 'w-12' : 'w-16'}`} />
                      </td>
                    ))}
                  </tr>
                ))
              ) : trades.length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-4 py-12 text-center text-text-disabled text-xs">
                    체결 내역이 없습니다
                  </td>
                </tr>
              ) : (
                trades.map((t) => (
                  <tr
                    key={t.id}
                    className="table-row-accent border-b border-[#1e2738] hover:bg-[#1c2330] transition-colors duration-100"
                  >
                    <td className="px-4 py-3 num text-xs text-text-secondary">
                      {new Date(t.createdAt).toLocaleString('ko-KR')}
                    </td>
                    <td className="px-4 py-3 num text-sm font-semibold text-text-primary">
                      {t.ticker}
                    </td>
                    <td className="px-4 py-3">
                      <span className={`inline-flex items-center gap-1 text-xs font-semibold
                                      ${t.side === 'BUY' ? 'text-buy' : 'text-sell'}`}>
                        <span>{t.side === 'BUY' ? '▲' : '▼'}</span>
                        {t.side}
                      </span>
                    </td>
                    <td className="px-4 py-3 num text-sm text-text-primary text-right">
                      {t.executedQty}
                    </td>
                    <td className="px-4 py-3 num text-sm text-text-primary text-right">
                      {t.executedPrice != null ? `$${t.executedPrice.toFixed(2)}` : '-'}
                    </td>
                    <td className="px-4 py-3">
                      <StatusBadge status={t.status} />
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        {/* 페이지네이션 */}
        <div className="shrink-0 border-t border-[#1e2738]">
          <Pagination page={page} totalPages={totalPages} onPageChange={handlePageChange} />
        </div>
      </div>
    </div>
  )
}

function SummaryChip({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <div className="flex items-center gap-1.5 bg-[#161b22] border border-[#2a3344] rounded px-2.5 py-1">
      <span className="text-[10px] text-text-disabled">{label}</span>
      <span className={`num text-xs font-semibold ${color}`}>{value}</span>
    </div>
  )
}

function StatusBadge({ status }: { status: string }) {
  if (status === 'EXECUTED') {
    return (
      <span className="inline-flex items-center gap-1 text-xs font-medium text-buy">
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none"
             stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
          <polyline points="20 6 9 17 4 12" />
        </svg>
        체결
      </span>
    )
  }
  if (status === 'PENDING') {
    return (
      <span className="inline-flex items-center gap-1 text-xs font-medium text-connecting">
        <span className="w-2 h-2 rounded-full bg-connecting animate-pulse" />
        대기
      </span>
    )
  }
  return (
    <span className="inline-flex items-center gap-1 text-xs font-medium text-sell">
      <svg width="12" height="12" viewBox="0 0 24 24" fill="none"
           stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
        <line x1="18" y1="6" x2="6" y2="18" />
        <line x1="6" y1="6" x2="18" y2="18" />
      </svg>
      실패
    </span>
  )
}
