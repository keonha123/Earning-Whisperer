"use client";

import { m } from "framer-motion";
import { useRouter } from "next/navigation";
import { useAuthStore } from "@/store/authStore";

interface SettingsTabProps {
  email: string;
}

export default function SettingsTab({ email }: SettingsTabProps) {
  const clearTokens = useAuthStore((s) => s.clearTokens);
  const router = useRouter();

  const handleLogout = () => {
    clearTokens();
    router.push("/");
  };

  return (
    <m.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.2 }}
      className="space-y-4"
    >
      {/* 계정 정보 */}
      <div className="rounded-xl border border-gray-800 bg-gray-900 p-5">
        <p className="mb-4 text-xs font-semibold uppercase tracking-widest text-gray-500">계정 정보</p>
        <div className="space-y-3">
          <div>
            <p className="mb-1 text-xs text-gray-600">이메일</p>
            <p className="font-mono text-sm text-gray-300">{email}</p>
          </div>
        </div>
      </div>

      {/* 포트폴리오 설정 안내 */}
      <div className="rounded-xl border border-gray-800 bg-gray-900 p-5">
        <p className="mb-2 text-xs font-semibold uppercase tracking-widest text-gray-500">포트폴리오 설정</p>
        <p className="mb-4 text-sm text-gray-400">
          매수 비율, 쿨다운, EMA 임계값 등 매매 규칙은 로컬 PC에 설치된 Trading Terminal에서 설정합니다.
        </p>
        <div className="flex items-center gap-2 rounded-lg border border-gray-800 bg-gray-800/50 px-4 py-3">
          <svg className="h-4 w-4 flex-shrink-0 text-gray-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
          </svg>
          <p className="text-xs text-gray-500">Trading Terminal → 설정 탭에서 변경 가능합니다</p>
        </div>
      </div>

      {/* 로그아웃 */}
      <div className="rounded-xl border border-gray-800 bg-gray-900 p-5">
        <p className="mb-4 text-xs font-semibold uppercase tracking-widest text-gray-500">세션</p>
        <button
          onClick={handleLogout}
          className="flex items-center gap-2 rounded-lg border border-red-500/30 bg-red-500/5 px-4 py-2.5 text-sm font-medium text-red-400 transition-colors hover:border-red-500/50 hover:bg-red-500/10"
        >
          <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" />
          </svg>
          로그아웃
        </button>
      </div>
    </m.div>
  );
}
