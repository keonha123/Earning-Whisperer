"use client";

import { SignalEntry } from "@/types/demo";

interface SignalFeedProps {
  signals: SignalEntry[];
}

function ActionBadge({ action }: { action: "BUY" | "SELL" | "HOLD" }) {
  const styles = {
    BUY: "bg-green-500/20 text-green-400 border-green-500/30",
    SELL: "bg-red-500/20 text-red-400 border-red-500/30",
    HOLD: "bg-gray-500/20 text-gray-400 border-gray-500/30",
  };
  return (
    <span className={`text-xs font-bold px-2 py-0.5 rounded border ${styles[action]}`}>
      {action}
    </span>
  );
}

function formatTime(epoch: number): string {
  const d = new Date(epoch * 1000);
  return `${d.getHours().toString().padStart(2, "0")}:${d.getMinutes().toString().padStart(2, "0")}:${d.getSeconds().toString().padStart(2, "0")}`;
}

export default function SignalFeed({ signals }: SignalFeedProps) {
  return (
    <div className="bg-gray-900 rounded-xl p-4 space-y-2">
      <h3 className="text-sm font-semibold text-gray-400 uppercase tracking-wider">
        신호 이력
      </h3>

      {signals.length === 0 ? (
        <p className="text-gray-600 text-sm italic">신호 대기 중...</p>
      ) : (
        <div className="space-y-2 max-h-48 overflow-y-auto">
          {signals.map((signal, i) => (
            <div
              key={i}
              className="flex items-start gap-3 p-2 rounded-lg bg-gray-800/50"
            >
              <div className="flex-shrink-0 pt-0.5">
                <ActionBadge action={signal.action} />
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-xs text-gray-300 leading-relaxed">{signal.rationale}</p>
                <div className="flex items-center gap-2 mt-1">
                  <span className="text-xs text-gray-600 font-mono">
                    EMA: {signal.emaScore.toFixed(3)}
                  </span>
                  <span className="text-xs text-gray-700">
                    {formatTime(signal.timestamp)}
                  </span>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
