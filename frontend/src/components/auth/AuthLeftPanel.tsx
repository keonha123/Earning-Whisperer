"use client";

function FeatureItem({ icon, title, desc }: { icon: React.ReactNode; title: string; desc: string }) {
  return (
    <div className="flex items-start gap-3">
      <div className="flex-shrink-0 w-8 h-8 rounded-lg bg-purple-600/20 flex items-center justify-center text-purple-400">
        {icon}
      </div>
      <div>
        <p className="text-sm font-medium text-white">{title}</p>
        <p className="text-xs text-gray-500 mt-0.5">{desc}</p>
      </div>
    </div>
  );
}

function DecorativeChart() {
  // 가짜 EMA 라인 SVG
  const points = [10, 40, 30, 55, 45, 70, 60, 80, 72, 88];
  const w = 280;
  const h = 80;
  const step = w / (points.length - 1);
  const d = points
    .map((p, i) => `${i === 0 ? "M" : "L"} ${i * step} ${h - (p / 100) * h}`)
    .join(" ");

  return (
    <div className="mt-8 opacity-30">
      <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`}>
        <defs>
          <linearGradient id="ema-grad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#a78bfa" stopOpacity="0.4" />
            <stop offset="100%" stopColor="#a78bfa" stopOpacity="0" />
          </linearGradient>
        </defs>
        <path d={d + ` L ${w} ${h} L 0 ${h} Z`} fill="url(#ema-grad)" />
        <path d={d} fill="none" stroke="#a78bfa" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      <p className="text-xs text-gray-700 mt-1">EMA Score 시뮬레이션</p>
    </div>
  );
}

export default function AuthLeftPanel() {
  return (
    <div className="hidden lg:flex flex-col justify-center px-12 py-16 border-r border-gray-800 bg-gray-950">
      <div className="max-w-sm">
        <h1 className="text-3xl font-bold text-white">EarningWhisperer</h1>
        <p className="mt-2 text-base text-gray-400">
          실시간 어닝콜 AI 분석 및 모의 자동매매 시스템
        </p>

        <div className="mt-10 space-y-5">
          <FeatureItem
            icon={
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
              </svg>
            }
            title="실시간 어닝콜 AI 분석"
            desc="음성 STT → FinBERT 감성 분석 → 즉시 신호 생성"
          />
          <FeatureItem
            icon={
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
              </svg>
            }
            title="EMA 기반 매매 신호"
            desc="노이즈를 걸러낸 지수이동평균으로 정밀한 BUY/SELL 판단"
          />
          <FeatureItem
            icon={
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
              </svg>
            }
            title="로컬 Trading Terminal"
            desc="API 키는 PC에만 저장 — 실주문은 내 컴퓨터에서 직접 실행"
          />
        </div>

        <DecorativeChart />
      </div>
    </div>
  );
}
