"use client";

import Link from "next/link";

export default function CtaOverlay() {
  return (
    <div className="relative mt-6">
      {/* 블러 레이어 */}
      <div className="absolute inset-0 backdrop-blur-md bg-gray-950/60 rounded-xl z-10 flex flex-col items-center justify-center gap-4 p-6">
        <p className="text-sm text-gray-400 text-center">
          실제 Trading Terminal에서 자동 매매 신호를 받으려면
        </p>
        <h3 className="text-xl font-bold text-white text-center">
          지금 무료로 시작하세요
        </h3>
        <div className="flex gap-3 flex-wrap justify-center">
          <Link
            href="/auth?mode=signup"
            className="px-6 py-2.5 bg-purple-600 hover:bg-purple-500 text-white font-semibold rounded-lg text-sm transition-colors"
          >
            회원가입
          </Link>
          <Link
            href="/auth"
            className="px-6 py-2.5 border border-gray-600 hover:border-gray-400 text-gray-300 hover:text-white font-semibold rounded-lg text-sm transition-colors"
          >
            로그인
          </Link>
        </div>
        <p className="text-xs text-gray-600 text-center">
          Free 플랜: 실시간 AI 신호 열람 · Pro 플랜: 자동매매 Trading Terminal
        </p>
      </div>

      {/* 블러 뒤에 있는 더미 콘텐츠 (블러 효과용) */}
      <div className="bg-gray-900 rounded-xl p-4 space-y-3 select-none min-h-[200px]" aria-hidden>
        <div className="h-4 bg-gray-700 rounded w-3/4"></div>
        <div className="h-4 bg-gray-700 rounded w-1/2"></div>
        <div className="h-4 bg-gray-700 rounded w-2/3"></div>
        <div className="h-10 bg-gray-700 rounded mt-2"></div>
      </div>
    </div>
  );
}
