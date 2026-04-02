"use client";

import { useEffect, useRef } from "react";

interface SttTextFeedProps {
  currentText: string;
  textHistory: string[];
  ticker: string;
}

export default function SttTextFeed({ currentText, textHistory, ticker }: SttTextFeedProps) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [textHistory]);

  return (
    <div className="bg-gray-900 rounded-xl p-4 space-y-2 flex flex-col">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-gray-400 uppercase tracking-wider">
          어닝콜 실시간 STT
        </h3>
        <span className="text-xs font-mono text-green-400 bg-green-400/10 px-2 py-0.5 rounded">
          {ticker} LIVE
        </span>
      </div>

      <div className="flex-1 overflow-y-auto max-h-64 space-y-1 scrollbar-thin scrollbar-thumb-gray-700">
        {textHistory.length === 0 ? (
          <p className="text-gray-600 text-sm italic">연결 대기 중...</p>
        ) : (
          textHistory.map((text, i) => (
            <p
              key={i}
              className={`text-sm leading-relaxed ${
                i === textHistory.length - 1
                  ? "text-white"
                  : "text-gray-500"
              }`}
            >
              {text}
            </p>
          ))
        )}
        <div ref={bottomRef} />
      </div>

      {/* 현재 수신 중인 텍스트 강조 */}
      {currentText && (
        <div className="border-l-2 border-purple-500 pl-3 text-sm text-purple-300">
          {currentText}
        </div>
      )}
    </div>
  );
}
