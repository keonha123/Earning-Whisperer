import Link from "next/link";

/* 데모룸 UI 목업 — 실제 스크린샷 준비 전 임시 시각화 */
function DemoMockup() {
  return (
    <div className="relative w-full overflow-hidden rounded-xl border border-gray-700/60 bg-gray-900 shadow-2xl shadow-black/50">
      {/* 브라우저 탑바 */}
      <div className="flex items-center gap-1.5 border-b border-gray-800 bg-gray-950 px-4 py-2.5">
        <span className="h-2.5 w-2.5 rounded-full bg-red-500/70" />
        <span className="h-2.5 w-2.5 rounded-full bg-yellow-500/70" />
        <span className="h-2.5 w-2.5 rounded-full bg-green-500/70" />
        <div className="ml-3 flex-1 rounded bg-gray-800 px-3 py-0.5 text-center text-xs text-gray-500">
          earningwhisperer.com/demo
        </div>
      </div>

      {/* 데모룸 내부 UI */}
      <div className="grid grid-cols-2 gap-3 p-4 sm:grid-cols-3">
        {/* 좌: 트랜스크립트 피드 */}
        <div className="col-span-2 space-y-2 sm:col-span-2">
          <div className="flex items-center gap-2">
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-red-400" />
            <span className="text-xs font-medium text-red-400">LIVE</span>
            <span className="text-xs text-gray-500">NVDA Q4 2024</span>
          </div>
          {[
            "...revenue for the quarter was $22.1 billion, up 265% from a year ago.",
            "Data Center revenue reached $18.4 billion, driven by strong AI demand.",
            "We expect Q1 FY2025 revenue to be approximately $24.0 billion...",
          ].map((line, i) => (
            <div key={i} className="rounded-md bg-gray-800/60 px-3 py-2">
              <p className="text-xs leading-relaxed text-gray-300">{line}</p>
            </div>
          ))}
          <div className="flex items-center gap-1.5 rounded-md bg-accent-500/10 px-3 py-2">
            <span className="inline-block h-1.5 w-3 animate-pulse rounded-full bg-accent-400" />
            <p className="text-xs text-accent-300/80">AI 분석 중...</p>
          </div>
        </div>

        {/* 우: 게이지 + EMA */}
        <div className="col-span-2 flex gap-3 sm:col-span-1 sm:flex-col">
          {/* 감성 게이지 */}
          <div className="flex-1 rounded-lg border border-gray-800 bg-gray-900/80 p-3">
            <p className="mb-2 text-xs text-gray-500">Sentiment Score</p>
            <div className="flex items-end gap-1">
              <span className="text-2xl font-bold text-accent-400">+0.78</span>
            </div>
            <div className="mt-2 h-1.5 w-full rounded-full bg-gray-800">
              <div
                className="h-full rounded-full bg-accent-500"
                style={{ width: "89%" }}
              />
            </div>
            <div className="mt-1 flex justify-between text-[10px] text-gray-600">
              <span>매도</span>
              <span>매수</span>
            </div>
          </div>

          {/* EMA 미니 차트 */}
          <div className="flex-1 rounded-lg border border-gray-800 bg-gray-900/80 p-3">
            <p className="mb-2 text-xs text-gray-500">EMA Trend</p>
            <svg viewBox="0 0 80 40" className="w-full" preserveAspectRatio="none">
              <polyline
                points="0,32 15,28 25,24 35,20 45,16 55,12 65,10 80,6"
                fill="none"
                stroke="var(--accent-500)"
                strokeWidth="1.5"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
            <div className="mt-1 flex items-center gap-1">
              <span className="rounded bg-accent-500/20 px-1.5 py-0.5 text-[10px] font-semibold text-accent-400">
                BUY
              </span>
              <span className="text-[10px] text-gray-500">신호 감지</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

export default function DemoTeaserSection() {
  return (
    <section className="relative bg-gray-950 py-20 px-4">
      {/* 배경 그라디언트 */}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0"
        style={{
          background:
            "radial-gradient(ellipse 60% 40% at 50% 100%, color-mix(in srgb, var(--accent-600) 8%, transparent), transparent)",
        }}
      />

      <div className="relative mx-auto max-w-4xl">
        {/* 헤더 */}
        <div className="mb-10 text-center">
          <span className="mb-3 inline-flex items-center gap-1.5 rounded-full border border-accent-500/30 bg-accent-500/10 px-3 py-1 text-xs font-medium text-accent-300">
            <span className="h-1.5 w-1.5 rounded-full bg-red-400 animate-pulse" />
            라이브 데모
          </span>
          <h2 className="mt-3 text-2xl font-bold text-white sm:text-3xl">
            실시간 어닝콜 AI 분석,
            <br />
            <span className="text-gray-400">직접 확인하세요</span>
          </h2>
          <p className="mt-3 text-sm text-gray-500">
            회원가입 없이 체험 가능합니다. 실제 어닝콜 데이터를 기반으로 AI가
            어떻게 판단하는지 보여드립니다.
          </p>
        </div>

        {/* 목업 UI */}
        <DemoMockup />

        {/* CTA */}
        <div className="mt-6 text-center">
          <Link
            href="/demo"
            className="inline-flex items-center gap-2 rounded-lg bg-accent-600 px-6 py-3 text-sm font-semibold text-white shadow-lg shadow-accent-500/20 transition-all hover:bg-accent-500"
          >
            지금 체험하기
            <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 7l5 5m0 0l-5 5m5-5H6" />
            </svg>
          </Link>
          <p className="mt-2 text-xs text-gray-600">로그인 불필요 · 무제한 체험</p>
        </div>
      </div>
    </section>
  );
}
