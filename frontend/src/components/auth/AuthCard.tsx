"use client";

import { useState, useCallback } from "react";
import AuthTabSwitcher from "./AuthTabSwitcher";
import LoginForm from "./LoginForm";
import SignupForm from "./SignupForm";

type Tab = "login" | "signup";

interface AuthCardProps {
  activeTab: Tab;
  onTabChange: (tab: Tab) => void;
}

export default function AuthCard({ activeTab, onTabChange }: AuthCardProps) {
  // 폼 내부 loading 상태를 끌어올려 탭 스위처 비활성화에 사용
  const [isLoading, setIsLoading] = useState(false);

  const handleLoadingChange = useCallback((loading: boolean) => {
    setIsLoading(loading);
  }, []);

  const handleTabChange = useCallback(
    (tab: Tab) => {
      if (isLoading) return;
      onTabChange(tab);
    },
    [isLoading, onTabChange]
  );

  return (
    <div className="bg-gray-900 rounded-2xl p-8 w-full max-w-md space-y-6">
      {/* 모바일 전용 브랜드 헤더 */}
      <div className="lg:hidden">
        <h1 className="text-xl font-bold text-white">EarningWhisperer</h1>
        <p className="text-xs text-gray-500 mt-0.5">실시간 어닝콜 AI 분석 시스템</p>
      </div>

      {/* 타이틀 */}
      <div>
        <h2 className="text-2xl font-bold text-white">
          {activeTab === "login" ? "다시 만나서 반가워요" : "시작해볼까요?"}
        </h2>
        <p className="text-sm text-gray-400 mt-1">
          {activeTab === "login"
            ? "계정에 로그인하여 AI 신호를 확인하세요."
            : "무료 계정을 만들고 데모룸을 체험해보세요."}
        </p>
      </div>

      {/* 탭 스위처 — 로딩 중 비활성화 */}
      <AuthTabSwitcher
        activeTab={activeTab}
        onChange={handleTabChange}
        disabled={isLoading}
      />

      {/* 폼 */}
      {activeTab === "login" ? (
        <LoginForm onLoadingChange={handleLoadingChange} />
      ) : (
        <SignupForm
          onLoadingChange={handleLoadingChange}
          onSwitchToLogin={() => onTabChange("login")}
        />
      )}

      {/* 탭 전환 링크 */}
      <p className="text-sm text-gray-400 text-center">
        {activeTab === "login" ? (
          <>
            계정이 없으신가요?{" "}
            <button
              type="button"
              onClick={() => handleTabChange("signup")}
              disabled={isLoading}
              className="text-purple-400 hover:text-purple-300 font-medium transition-colors disabled:opacity-40"
            >
              회원가입
            </button>
          </>
        ) : (
          <>
            이미 계정이 있으신가요?{" "}
            <button
              type="button"
              onClick={() => handleTabChange("login")}
              disabled={isLoading}
              className="text-purple-400 hover:text-purple-300 font-medium transition-colors disabled:opacity-40"
            >
              로그인
            </button>
          </>
        )}
      </p>
    </div>
  );
}
