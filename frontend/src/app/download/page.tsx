import Link from "next/link";
import LandingNav from "@/components/landing/LandingNav";

const FEATURES = [
  {
    icon: (
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M13 10V3L4 14h7v7l9-11h-7z" />
    ),
    title: "실시간 매매 신호 수신",
    desc: "백엔드 AI 분석 결과를 WebSocket으로 즉시 수신합니다.",
  },
  {
    icon: (
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
    ),
    title: "API 키 로컬 암호화 보관",
    desc: "KIS 증권사 키는 OS Credential Manager에만 저장됩니다. 서버에 전달되지 않습니다.",
  },
  {
    icon: (
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
    ),
    title: "3가지 매매 모드",
    desc: "MANUAL(수동 확인), 1-Click(클릭 한 번 승인), AUTO_PILOT(완전 자동) 중 선택 가능합니다.",
  },
  {
    icon: (
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
    ),
    title: "포트폴리오 실시간 동기화",
    desc: "실제 KIS 계좌 잔고를 조회하여 백엔드 장부와 자동으로 동기화합니다.",
  },
];

const OS_REQUIREMENTS = [
  { os: "Windows", version: "Windows 10 이상 (64-bit)", icon: "⊞" },
  { os: "macOS", version: "macOS 12 Monterey 이상", icon: "" },
];

export default function DownloadPage() {
  return (
    <>
      <LandingNav />
      <main className="min-h-screen bg-gray-950 px-4 pt-24 pb-20">
        <div className="mx-auto max-w-3xl">

          {/* 헤더 */}
          <div className="mb-12 text-center">
            <span className="mb-4 inline-flex items-center gap-1.5 rounded-full border border-accent-500/30 bg-accent-500/10 px-3 py-1 text-xs font-medium text-accent-300">
              Trading Terminal
            </span>
            <h1 className="mt-3 text-3xl font-bold text-white sm:text-4xl">
              로컬 PC에서 직접 실행하는<br />
              <span className="text-gray-400">AI 자동매매 에이전트</span>
            </h1>
            <p className="mt-4 text-sm leading-relaxed text-gray-500">
              증권사 API 키는 서버에 올라가지 않습니다.<br />
              Trading Terminal이 내 PC에서 직접 주문을 실행합니다.
            </p>
          </div>

          {/* 다운로드 카드 */}
          <div className="mb-10 overflow-hidden rounded-2xl border border-gray-800 bg-gray-900">
            {/* OS 선택 */}
            <div className="grid divide-x divide-gray-800 sm:grid-cols-2">
              {OS_REQUIREMENTS.map((item) => (
                <div key={item.os} className="flex flex-col items-center gap-3 p-8">
                  <span className="text-4xl">{item.icon}</span>
                  <div className="text-center">
                    <p className="font-semibold text-white">{item.os}</p>
                    <p className="mt-0.5 text-xs text-gray-500">{item.version}</p>
                  </div>
                  <div className="mt-2 flex w-full flex-col items-center gap-2">
                    <button
                      disabled
                      className="w-full cursor-not-allowed rounded-lg bg-gray-800 px-4 py-2.5 text-sm font-medium text-gray-500"
                    >
                      준비 중
                    </button>
                  </div>
                </div>
              ))}
            </div>

            {/* 보안 안내 */}
            <div className="border-t border-gray-800 bg-gray-900/50 px-6 py-4">
              <div className="flex items-start gap-2.5">
                <svg className="mt-0.5 h-4 w-4 flex-shrink-0 text-accent-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
                </svg>
                <p className="text-xs leading-relaxed text-gray-500">
                  보안을 위해 실제 증권사 API 키는 웹에 저장되지 않으며, PC에 설치된 Trading Terminal 내부에만 OS Credential Manager를 통해 암호화되어 보관됩니다.
                </p>
              </div>
            </div>
          </div>

          {/* 기능 목록 */}
          <div className="mb-10">
            <h2 className="mb-5 text-sm font-semibold uppercase tracking-widest text-gray-500">
              주요 기능
            </h2>
            <div className="grid gap-3 sm:grid-cols-2">
              {FEATURES.map((f, i) => (
                <div
                  key={i}
                  className="flex gap-3 rounded-xl border border-gray-800 bg-gray-900/50 p-4"
                >
                  <div className="mt-0.5 flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-lg bg-accent-500/10">
                    <svg className="h-4 w-4 text-accent-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      {f.icon}
                    </svg>
                  </div>
                  <div>
                    <p className="text-sm font-medium text-white">{f.title}</p>
                    <p className="mt-0.5 text-xs leading-relaxed text-gray-500">{f.desc}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* 하단 링크 */}
          <div className="text-center text-sm text-gray-600">
            <span>이미 계정이 있으신가요? </span>
            <Link href="/mypage" className="text-accent-400 hover:text-accent-300">
              마이페이지로 이동
            </Link>
          </div>

        </div>
      </main>
    </>
  );
}
