"use client";

interface TensionGaugeProps {
  rawScore: number; // -1.0 ~ 1.0
  emaScore: number; // -1.0 ~ 1.0
}

function scoreToPercent(score: number): number {
  return Math.round(((score + 1) / 2) * 100);
}

function scoreToColor(score: number): string {
  if (score >= 0.6) return "bg-green-500";
  if (score >= 0.3) return "bg-yellow-400";
  if (score >= 0) return "bg-yellow-600";
  if (score >= -0.3) return "bg-orange-500";
  return "bg-red-500";
}

function scoreToLabel(score: number): string {
  if (score >= 0.6) return "강한 매수 신호";
  if (score >= 0.3) return "긍정적";
  if (score >= 0) return "중립";
  if (score >= -0.3) return "부정적";
  return "강한 매도 신호";
}

export default function TensionGauge({ rawScore, emaScore }: TensionGaugeProps) {
  const rawPercent = scoreToPercent(rawScore);
  const emaPercent = scoreToPercent(emaScore);
  const emaColor = scoreToColor(emaScore);

  return (
    <div className="bg-gray-900 rounded-xl p-4 space-y-4">
      <h3 className="text-sm font-semibold text-gray-400 uppercase tracking-wider">
        AI 감성 지수
      </h3>

      {/* EMA Score — 메인 게이지 */}
      <div className="space-y-1">
        <div className="flex justify-between text-xs text-gray-400">
          <span>EMA Score</span>
          <span className="font-mono text-white">{emaScore.toFixed(3)}</span>
        </div>
        <div className="h-4 bg-gray-700 rounded-full overflow-hidden">
          <div
            className={`h-full rounded-full transition-all duration-700 ${emaColor}`}
            style={{ width: `${emaPercent}%` }}
          />
        </div>
        <p className="text-xs text-gray-300">{scoreToLabel(emaScore)}</p>
      </div>

      {/* Raw Score — 서브 게이지 */}
      <div className="space-y-1">
        <div className="flex justify-between text-xs text-gray-400">
          <span>Raw Score</span>
          <span className="font-mono text-white">{rawScore.toFixed(3)}</span>
        </div>
        <div className="h-2 bg-gray-700 rounded-full overflow-hidden">
          <div
            className="h-full bg-blue-400 rounded-full transition-all duration-300"
            style={{ width: `${rawPercent}%` }}
          />
        </div>
      </div>

      {/* 스케일 표시 */}
      <div className="flex justify-between text-xs text-gray-600">
        <span>-1.0 매도</span>
        <span>0</span>
        <span>+1.0 매수</span>
      </div>
    </div>
  );
}

