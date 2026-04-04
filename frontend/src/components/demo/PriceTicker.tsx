"use client";

interface PriceTickerProps {
  ticker: string;
  price: number;
  change: number;
  changePercent: number;
}

export default function PriceTicker({ ticker, price, change, changePercent }: PriceTickerProps) {
  const isPositive = change >= 0;
  const colorClass = isPositive ? "text-green-400" : "text-red-400";
  const sign = isPositive ? "+" : "";
  const connected = price !== 0;

  return (
    <div className="bg-gray-900 rounded-xl p-4 flex items-center justify-between">
      <div>
        <span className="text-sm font-bold text-white">{ticker}</span>
        <span className="ml-2 text-xs text-gray-500">모의 시세</span>
      </div>
      {/* 고정 높이 구조 유지 → CLS 방지 */}
      <div className="text-right">
        <p className="text-xl font-mono font-bold text-white">
          {connected ? `$${price.toFixed(2)}` : <span className="text-gray-600">---</span>}
        </p>
        <p className={`text-xs font-mono ${connected ? colorClass : "text-gray-700"}`}>
          {connected
            ? `${sign}${change.toFixed(2)} (${sign}${changePercent.toFixed(2)}%)`
            : "연결 대기..."}
        </p>
      </div>
    </div>
  );
}
