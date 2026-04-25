"use client";

import { useRef } from "react";
import { m, useInView } from "framer-motion";
import { fadeUp, staggerContainer, defaultViewport } from "@/lib/animation-variants";

const STEPS = [
  {
    id: 1,
    label: "Data Pipeline",
    tech: "yt-dlp / Whisper",
    desc: "어닝콜 음성을 실시간 수집하고 텍스트로 변환합니다.",
    tag: "text_chunk",
    color: "blue",
    iconBg: "bg-blue-500/10",
    iconText: "text-blue-400",
    tagBg: "bg-blue-500/10 text-blue-300",
    icon: (
      <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z" />
      </svg>
    ),
  },
  {
    id: 2,
    label: "AI Engine",
    tech: "FinBERT / FastAPI",
    desc: "감성 분석 모델이 텍스트를 시계열 맥락까지 반영해 -1~1 점수로 평가합니다.",
    tag: "ai_score: 0.72",
    color: "purple",
    iconBg: "bg-accent-500/10",
    iconText: "text-accent-400",
    tagBg: "bg-accent-500/10 text-accent-300",
    icon: (
      <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
      </svg>
    ),
  },
  {
    id: 3,
    label: "Backend",
    tech: "Spring Boot / Redis",
    desc: "사용자별 룰 엔진으로 매매 신호를 평가하고 실시간 브로드캐스트합니다.",
    tag: "action: BUY",
    color: "green",
    live: true,
    iconBg: "bg-green-500/10",
    iconText: "text-green-400",
    tagBg: "bg-green-500/10 text-green-300",
    icon: (
      <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 12h14M5 12a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v4a2 2 0 01-2 2M5 12a2 2 0 00-2 2v4a2 2 0 002 2h14a2 2 0 002-2v-4a2 2 0 00-2-2m-2-4h.01M17 16h.01" />
      </svg>
    ),
  },
  {
    id: 4,
    label: "Trading Terminal",
    tech: "Electron / KIS API",
    desc: "신호를 수신한 로컬 PC가 증권사 API로 직접 주문을 실행합니다.",
    tag: "EXECUTED",
    color: "orange",
    iconBg: "bg-orange-500/10",
    iconText: "text-orange-400",
    tagBg: "bg-orange-500/10 text-orange-300",
    icon: (
      <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
      </svg>
    ),
  },
];

function ConnectorLine() {
  const ref = useRef(null);
  const isInView = useInView(ref, { once: true, margin: "-100px" });
  return (
    <div ref={ref} className="hidden items-center lg:flex">
      <svg width="60" height="20" viewBox="0 0 60 20">
        <m.line
          x1="0" y1="10" x2="60" y2="10"
          stroke="rgba(168,85,247,0.4)"
          strokeWidth="1"
          strokeDasharray="4 3"
          initial={{ pathLength: 0, opacity: 0 }}
          animate={isInView ? { pathLength: 1, opacity: 1 } : {}}
          transition={{ duration: 0.6, delay: 0.4, ease: "easeInOut" }}
        />
        <m.polygon
          points="54,6 60,10 54,14"
          fill="rgba(168,85,247,0.5)"
          initial={{ opacity: 0 }}
          animate={isInView ? { opacity: 1 } : {}}
          transition={{ duration: 0.3, delay: 0.9 }}
        />
      </svg>
    </div>
  );
}

export default function HowItWorksSection() {
  return (
    <section className="relative bg-gray-900 px-4 py-24 sm:py-32">
      {/* 상단 구분선 */}
      <div
        aria-hidden="true"
        className="absolute left-1/2 top-0 h-px w-3/4 -translate-x-1/2"
        style={{
          background: "linear-gradient(to right, transparent, rgba(168,85,247,0.5), transparent)",
        }}
      />

      <div className="mx-auto max-w-6xl">
        {/* 섹션 레이블 */}
        <m.div
          initial={{ opacity: 0, y: 16 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={defaultViewport}
          transition={{ duration: 0.5 }}
          className="mb-4 text-center"
        >
          <span className="text-xs font-semibold uppercase tracking-widest text-accent-400">
            How It Works
          </span>
        </m.div>

        <m.h2
          initial={{ opacity: 0, y: 16 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={defaultViewport}
          transition={{ duration: 0.5, delay: 0.1 }}
          className="mb-4 text-center text-3xl font-bold text-white sm:text-4xl"
        >
          음성에서 주문까지, 완전 자동
        </m.h2>
        <m.p
          initial={{ opacity: 0 }}
          whileInView={{ opacity: 1 }}
          viewport={defaultViewport}
          transition={{ duration: 0.5, delay: 0.2 }}
          className="mb-14 text-center text-gray-400"
        >
          4개 컴포넌트가 파이프라인처럼 연결되어 실시간으로 동작합니다.
        </m.p>

        {/* 플로우 다이어그램 */}
        <m.div
          variants={staggerContainer}
          initial="hidden"
          whileInView="visible"
          viewport={defaultViewport}
          className="flex flex-col items-stretch gap-4 lg:flex-row lg:items-start"
        >
          {STEPS.map((step, i) => (
            <div key={step.id} className="flex flex-1 flex-col items-center lg:flex-row">
              {/* 노드 카드 */}
              <m.div
                variants={fadeUp}
                className="w-full flex-1 rounded-xl border border-gray-700 bg-gray-800/50 p-5"
              >
                {/* 상단: 아이콘 + 라이브 */}
                <div className="mb-3 flex items-start justify-between">
                  <div className={`inline-flex h-9 w-9 items-center justify-center rounded-lg ${step.iconBg} ${step.iconText}`}>
                    {step.icon}
                  </div>
                  {step.live && (
                    <span className="inline-flex items-center gap-1 rounded-full bg-green-500/10 px-2 py-0.5 text-xs text-green-400">
                      <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-green-400" />
                      Live
                    </span>
                  )}
                </div>
                {/* 레이블 */}
                <p className="mb-0.5 text-sm font-semibold text-white">{step.label}</p>
                <p className="mb-3 font-mono text-xs text-gray-600">{step.tech}</p>
                <p className="mb-4 text-xs leading-relaxed text-gray-400">{step.desc}</p>
                {/* 데이터 태그 */}
                <span className={`inline-block rounded font-mono text-xs px-2 py-0.5 ${step.tagBg}`}>
                  {step.tag}
                </span>
              </m.div>

              {/* 커넥터 — 마지막 노드 제외 */}
              {i < STEPS.length - 1 && (
                <>
                  <ConnectorLine />
                  {/* 모바일 수직 화살표 */}
                  <div className="flex justify-center py-1 lg:hidden">
                    <svg className="h-6 w-6 rotate-90 text-accent-500/40" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M13 7l5 5m0 0l-5 5m5-5H6" />
                    </svg>
                  </div>
                </>
              )}
            </div>
          ))}
        </m.div>

        {/* 하단 포인트 */}
        <m.div
          initial={{ opacity: 0, y: 12 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={defaultViewport}
          transition={{ duration: 0.5, delay: 0.3 }}
          className="mt-10 flex flex-wrap justify-center gap-6"
        >
          <div className="flex items-center gap-2 text-sm text-gray-400">
            <svg className="h-4 w-4 text-green-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
            </svg>
            증권사 API 키는 로컬 PC에만 저장
          </div>
          <div className="flex items-center gap-2 text-sm text-gray-400">
            <svg className="h-4 w-4 text-accent-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
            </svg>
            음성 수집부터 주문 실행까지 수초 이내
          </div>
          <div className="flex items-center gap-2 text-sm text-gray-400">
            <svg className="h-4 w-4 text-blue-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
            </svg>
            60fps 실시간 WebSocket 업데이트
          </div>
        </m.div>
      </div>
    </section>
  );
}
