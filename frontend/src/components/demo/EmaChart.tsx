"use client";

import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ReferenceLine,
  ResponsiveContainer,
} from "recharts";
import { EmaDataPoint } from "@/types/demo";

interface EmaChartProps {
  data: EmaDataPoint[];
  threshold?: number;
}

function formatTime(epoch: number): string {
  const d = new Date(epoch * 1000);
  return `${d.getMinutes().toString().padStart(2, "0")}:${d.getSeconds().toString().padStart(2, "0")}`;
}

export default function EmaChart({ data, threshold = 0.6 }: EmaChartProps) {
  return (
    <div className="bg-gray-900 rounded-xl p-4 space-y-2">
      <h3 className="text-sm font-semibold text-gray-400 uppercase tracking-wider">
        EMA Score 추이
      </h3>

      {data.length === 0 ? (
        <div className="flex items-center justify-center h-40 text-gray-600 text-sm">
          데이터 수신 대기 중...
        </div>
      ) : (
        <ResponsiveContainer width="100%" height={160}>
          <LineChart data={data} margin={{ top: 4, right: 8, left: -24, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
            <XAxis
              dataKey="time"
              tickFormatter={formatTime}
              tick={{ fontSize: 10, fill: "#9CA3AF" }}
              interval="preserveStartEnd"
            />
            <YAxis
              domain={[-1, 1]}
              tick={{ fontSize: 10, fill: "#9CA3AF" }}
              tickCount={5}
            />
            <Tooltip
              contentStyle={{ background: "#1F2937", border: "none", borderRadius: 8, fontSize: 12 }}
              labelFormatter={(v) => formatTime(v as number)}
              formatter={(value, name) => [
                typeof value === "number" ? value.toFixed(3) : value,
                name === "ema" ? "EMA" : "Raw",
              ]}
            />
            {/* BUY 임계선 */}
            <ReferenceLine y={threshold} stroke="#22C55E" strokeDasharray="4 4" />
            {/* SELL 임계선 */}
            <ReferenceLine y={-threshold} stroke="#EF4444" strokeDasharray="4 4" />
            {/* 0 기준선 */}
            <ReferenceLine y={0} stroke="#6B7280" />

            <Line
              type="monotone"
              dataKey="raw"
              stroke="#60A5FA"
              strokeWidth={1}
              dot={false}
              opacity={0.5}
            />
            <Line
              type="monotone"
              dataKey="ema"
              stroke="#A78BFA"
              strokeWidth={2}
              dot={false}
            />
          </LineChart>
        </ResponsiveContainer>
      )}

      <div className="flex gap-4 text-xs text-gray-500">
        <span className="flex items-center gap-1">
          <span className="inline-block w-4 h-0.5 bg-purple-400"></span> EMA
        </span>
        <span className="flex items-center gap-1">
          <span className="inline-block w-4 h-0.5 bg-blue-400 opacity-50"></span> Raw
        </span>
        <span className="flex items-center gap-1">
          <span className="inline-block w-4 h-0.5 bg-green-500"></span> BUY 임계({threshold})
        </span>
      </div>
    </div>
  );
}
