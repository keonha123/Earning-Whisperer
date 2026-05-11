"use client";

import { useEffect } from "react";
import { useDemoWebSocket } from "@/hooks/useDemoWebSocket";
import { useDemoStore } from "@/store/demoStore";
import TensionGauge from "@/components/demo/TensionGauge";
import EmaChart from "@/components/demo/EmaChart";
import SttTextFeed from "@/components/demo/SttTextFeed";
import SignalFeed from "@/components/demo/SignalFeed";
import PriceTicker from "@/components/demo/PriceTicker";
import CtaOverlay from "@/components/demo/CtaOverlay";
import LandingNav from "@/components/landing/LandingNav";

function ConnectionStatus({ connected }: { connected: boolean }) {
  return (
    <div className="flex items-center gap-2">
      <span
        className={`inline-block w-2 h-2 rounded-full ${
          connected ? "bg-green-400 animate-pulse" : "bg-red-500"
        }`}
      />
      <span className="text-xs text-gray-400">
        {connected ? "라이브 연결됨" : "연결 시도 중..."}
      </span>
    </div>
  );
}

function SessionEndBanner({ onDismiss }: { onDismiss: () => void }) {
  return (
    <div className="fixed top-16 left-1/2 -translate-x-1/2 z-50 bg-accent-900/90 border border-accent-500 rounded-lg px-6 py-3 flex items-center gap-4 shadow-lg">
      <p className="text-sm text-accent-200">어닝콜 세션 종료 — 5초 후 재시작</p>
      <button
        onClick={onDismiss}
        className="text-xs text-accent-400 hover:text-white transition-colors"
      >
        닫기
      </button>
    </div>
  );
}

export default function DemoPage() {
  useDemoWebSocket();

  const {
    connected,
    ticker,
    currentText,
    textHistory,
    aiScore,
    emaHistory,
    signals,
    isSessionEnd,
    currentPrice,
    priceChange,
    priceChangePercent,
    reset,
  } = useDemoStore();

  useEffect(() => {
    if (!isSessionEnd) return;
    const timer = setTimeout(() => {
      reset();
    }, 6000);
    return () => clearTimeout(timer);
  }, [isSessionEnd, reset]);

  return (
    <div className="min-h-screen bg-gray-950 text-white">
      <LandingNav />
      {isSessionEnd && <SessionEndBanner onDismiss={reset} />}

      {/* 연결 상태 서브헤더 */}
      <div className="border-b border-gray-800 px-6 py-2 flex items-center justify-between pt-[57px]">
        <p className="text-xs text-gray-500">라이브 AI 어닝콜 분석 데모</p>
        <ConnectionStatus connected={connected} />
      </div>

      <main className="max-w-6xl mx-auto px-4 py-6 space-y-4">
        <PriceTicker
          ticker={ticker}
          price={currentPrice}
          change={priceChange}
          changePercent={priceChangePercent}
        />

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <div className="space-y-4">
            <TensionGauge aiScore={aiScore} />
            <EmaChart data={emaHistory} />
          </div>
          <div className="space-y-4">
            <SttTextFeed
              currentText={currentText}
              textHistory={textHistory}
              ticker={ticker}
            />
            <SignalFeed signals={signals} />
          </div>
        </div>

        <CtaOverlay />
      </main>
    </div>
  );
}
