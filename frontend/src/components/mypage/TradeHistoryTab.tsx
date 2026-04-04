"use client";

import { m } from "framer-motion";

interface Trade {
  id: number;
  ticker: string;
  side: "BUY" | "SELL";
  orderQty: number;
  executedQty: number;
  status: "PENDING" | "EXECUTED" | "FAILED";
  createdAt: string;
}

interface TradeHistoryTabProps {
  trades: Trade[];
}

const STATUS_STYLE = {
  EXECUTED: "bg-green-500/10 text-green-400",
  FAILED: "bg-red-500/10 text-red-400",
  PENDING: "bg-yellow-500/10 text-yellow-400",
} as const;

const STATUS_LABEL = { EXECUTED: "체결", FAILED: "실패", PENDING: "대기" } as const;

function formatDate(iso: string) {
  return new Date(iso).toLocaleString("ko-KR", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export default function TradeHistoryTab({ trades }: TradeHistoryTabProps) {
  if (trades.length === 0) {
    return (
      <m.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        className="flex flex-col items-center justify-center py-24 text-center"
      >
        <div className="mb-3 flex h-12 w-12 items-center justify-center rounded-xl border border-gray-800 bg-gray-900">
          <svg className="h-5 w-5 text-gray-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
          </svg>
        </div>
        <p className="text-sm font-medium text-gray-500">아직 거래 내역이 없습니다</p>
        <p className="mt-1 text-xs text-gray-600">AUTO_PILOT 모드로 매매 신호를 실행하면 여기에 기록됩니다</p>
      </m.div>
    );
  }

  return (
    <m.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.2 }}>
      {/* 데스크톱 테이블 */}
      <div className="hidden overflow-hidden rounded-xl border border-gray-800 md:block">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-800 bg-gray-900/60">
              <th className="px-4 py-3 text-left font-mono text-xs font-medium uppercase tracking-wider text-gray-500">티커</th>
              <th className="px-4 py-3 text-left font-mono text-xs font-medium uppercase tracking-wider text-gray-500">방향</th>
              <th className="px-4 py-3 text-right font-mono text-xs font-medium uppercase tracking-wider text-gray-500">주문</th>
              <th className="px-4 py-3 text-right font-mono text-xs font-medium uppercase tracking-wider text-gray-500">체결</th>
              <th className="px-4 py-3 text-center font-mono text-xs font-medium uppercase tracking-wider text-gray-500">상태</th>
              <th className="px-4 py-3 text-right font-mono text-xs font-medium uppercase tracking-wider text-gray-500">일시</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-800/60">
            {trades.map((t) => (
              <tr key={t.id} className="transition-colors hover:bg-gray-800/30">
                <td className="px-4 py-3 font-mono font-bold text-white">{t.ticker}</td>
                <td className="px-4 py-3">
                  <span className={`font-mono text-xs font-bold ${t.side === "BUY" ? "text-green-400" : "text-red-400"}`}>
                    {t.side === "BUY" ? "▲ 매수" : "▼ 매도"}
                  </span>
                </td>
                <td className="px-4 py-3 text-right font-mono text-gray-300">{t.orderQty}</td>
                <td className="px-4 py-3 text-right font-mono text-gray-300">{t.executedQty}</td>
                <td className="px-4 py-3 text-center">
                  <span className={`inline-block rounded-md px-2 py-0.5 font-mono text-xs font-medium ${STATUS_STYLE[t.status]}`}>
                    {STATUS_LABEL[t.status]}
                  </span>
                </td>
                <td className="px-4 py-3 text-right font-mono text-xs text-gray-500">{formatDate(t.createdAt)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* 모바일 카드 */}
      <div className="space-y-3 md:hidden">
        {trades.map((t) => (
          <div key={t.id} className="rounded-xl border border-gray-800 bg-gray-900 p-4">
            <div className="mb-2 flex items-center justify-between">
              <span className="font-mono font-bold text-white">{t.ticker}</span>
              <span className={`inline-block rounded-md px-2 py-0.5 font-mono text-xs font-medium ${STATUS_STYLE[t.status]}`}>
                {STATUS_LABEL[t.status]}
              </span>
            </div>
            <div className="flex items-center justify-between text-xs">
              <span className={`font-mono font-bold ${t.side === "BUY" ? "text-green-400" : "text-red-400"}`}>
                {t.side === "BUY" ? "▲ 매수" : "▼ 매도"} {t.orderQty}주
              </span>
              <span className="font-mono text-gray-500">{formatDate(t.createdAt)}</span>
            </div>
          </div>
        ))}
      </div>
    </m.div>
  );
}
