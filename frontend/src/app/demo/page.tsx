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
    <div className="fixed top-4 left-1/2 -translate-x-1/2 z-50 bg-purple-900/90 border border-purple-500 rounded-lg px-6 py-3 flex items-center gap-4 shadow-lg">
      <p className="text-sm text-purple-200">어닝콜 세션 종료 — 5초 후 재시작</p>
      <button
        onClick={onDismiss}
        className="text-xs text-purple-400 hover:text-white transition-colors"
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
    rawScore,
    emaScore,
    emaHistory,
    signals,
    isSessionEnd,
    currentPrice,
    priceChange,
    priceChangePercent,
    reset,
  } = useDemoStore();

  // 세션 종료 시 자동으로 배너 숨기기 (5초 후)
  useEffect(() => {
    if (!isSessionEnd) return;
    const timer = setTimeout(() => {
      reset();
    }, 6000);
    return () => clearTimeout(timer);
  }, [isSessionEnd, reset]);

  return (
    <div className="min-h-screen bg-gray-950 text-white">
      {isSessionEnd && <SessionEndBanner onDismiss={reset} />}

      {/* 헤더 */}
      <header className="border-b border-gray-800 px-6 py-4 flex items-center justify-between">
        <div>
          <h1 className="text-lg font-bold">EarningWhisperer</h1>
          <p className="text-xs text-gray-500">라이브 AI 어닝콜 분석 데모</p>
        </div>
        <ConnectionStatus connected={connected} />
      </header>

      <main className="max-w-6xl mx-auto px-4 py-6 space-y-4">
        {/* 상단: 주가 티커 */}
        <PriceTicker
          ticker={ticker}
          price={currentPrice}
          change={priceChange}
          changePercent={priceChangePercent}
        />

        {/* 중단: 두 컬럼 레이아웃 */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {/* 좌측: 감성 게이지 + EMA 차트 */}
          <div className="space-y-4">
            <TensionGauge rawScore={rawScore} emaScore={emaScore} />
            <EmaChart data={emaHistory} />
          </div>

          {/* 우측: STT 피드 + 신호 이력 */}
          <div className="space-y-4">
            <SttTextFeed
              currentText={currentText}
              textHistory={textHistory}
              ticker={ticker}
            />
            <SignalFeed signals={signals} />
          </div>
        </div>

        {/* 하단: CTA 블러 레이어 */}
        <CtaOverlay />
      </main>
    </div>
  );
}
