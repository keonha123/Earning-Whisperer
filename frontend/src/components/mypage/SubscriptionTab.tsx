"use client";

import { m } from "framer-motion";

const PRO_FEATURES = [
  "EMA 기반 BUY/SELL 매매 신호",
  "AUTO_PILOT 자동매매 모드",
  "포트폴리오 연동 신호 최적화",
  "Free 플랜 전체 포함",
];

const FREE_FEATURES = [
  "FinBERT Raw Score 실시간 수신",
  "데모룸 무제한 체험",
  "Trading Terminal 설치",
  "매매 계좌 연동",
];

interface SubscriptionTabProps {
  role: "FREE" | "PRO";
}

export default function SubscriptionTab({ role }: SubscriptionTabProps) {
  return (
    <m.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.2 }}
      className="space-y-4"
    >
      {/* 현재 플랜 */}
      <div className="rounded-xl border border-gray-800 bg-gray-900 p-5">
        <p className="mb-3 text-xs font-semibold uppercase tracking-widest text-gray-500">현재 플랜</p>
        <div className="flex items-center gap-3">
          {role === "PRO" ? (
            <>
              <span className="rounded-md bg-accent-600 px-2.5 py-1 text-sm font-bold uppercase tracking-wider text-white">Pro</span>
              <span className="font-mono text-sm text-gray-300">₩9,900 / 월</span>
            </>
          ) : (
            <>
              <span className="rounded-md border border-gray-600 px-2.5 py-1 text-sm font-medium uppercase tracking-wider text-gray-400">Free</span>
              <span className="font-mono text-sm text-gray-500">무료</span>
            </>
          )}
        </div>
      </div>

      {role === "FREE" ? (
        /* FREE → PRO 업그레이드 유도 */
        <div className="rounded-xl border border-accent-500/30 bg-gradient-to-b from-accent-500/5 to-gray-900/80 p-5">
          <div className="mb-4 flex items-center justify-between">
            <div>
              <p className="text-sm font-bold text-white">Pro 플랜으로 업그레이드</p>
              <p className="mt-0.5 font-mono text-lg font-bold text-white">₩9,900<span className="text-sm font-normal text-gray-500"> /월</span></p>
            </div>
            <span className="rounded-md bg-accent-500/20 px-2.5 py-0.5 text-xs font-semibold text-accent-300">추천</span>
          </div>
          <ul className="mb-5 space-y-2">
            {PRO_FEATURES.map((f) => (
              <li key={f} className="flex items-center gap-2 text-sm text-gray-300">
                <svg className="h-3.5 w-3.5 flex-shrink-0 text-accent-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 13l4 4L19 7" />
                </svg>
                {f}
              </li>
            ))}
          </ul>
          <button
            disabled
            className="relative w-full cursor-not-allowed rounded-lg bg-accent-600/40 py-2.5 text-sm font-semibold text-white/50"
          >
            결제하기
            <span className="absolute -right-2 -top-2 rounded-full bg-gray-700 px-2 py-0.5 text-[10px] font-bold text-gray-300">
              COMING SOON
            </span>
          </button>
          <p className="mt-2 text-center text-xs text-gray-600">Toss Payments 결제 연동 준비 중입니다</p>
        </div>
      ) : (
        /* PRO 사용자 — 혜택 목록 */
        <div className="rounded-xl border border-gray-800 bg-gray-900 p-5">
          <p className="mb-4 text-xs font-semibold uppercase tracking-widest text-gray-500">Pro 혜택</p>
          <ul className="space-y-2.5">
            {PRO_FEATURES.map((f) => (
              <li key={f} className="flex items-center gap-2 text-sm text-gray-300">
                <svg className="h-3.5 w-3.5 flex-shrink-0 text-accent-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 13l4 4L19 7" />
                </svg>
                {f}
              </li>
            ))}
          </ul>
          <div className="mt-4 rounded-lg border border-gray-800 bg-gray-800/50 px-4 py-3 text-xs text-gray-500">
            구독 취소 및 플랜 변경은 추후 지원될 예정입니다.
          </div>
        </div>
      )}

      {/* FREE 플랜 기능 요약 */}
      {role === "FREE" && (
        <div className="rounded-xl border border-gray-800 bg-gray-900/50 p-5">
          <p className="mb-3 text-xs font-semibold uppercase tracking-widest text-gray-500">현재 이용 가능</p>
          <ul className="space-y-2">
            {FREE_FEATURES.map((f) => (
              <li key={f} className="flex items-center gap-2 text-sm text-gray-400">
                <span className="h-1.5 w-1.5 flex-shrink-0 rounded-full bg-gray-600" />
                {f}
              </li>
            ))}
          </ul>
        </div>
      )}
    </m.div>
  );
}
