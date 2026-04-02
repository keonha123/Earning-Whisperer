"use client";

import Link from "next/link";
import { m, useScroll, useTransform } from "framer-motion";
import { fadeUp, staggerContainer } from "@/lib/animation-variants";

function HeroBackground() {
  const { scrollY } = useScroll();
  const y = useTransform(scrollY, [0, 400], [0, -80]);

  return (
    <m.div
      style={{ y }}
      aria-hidden="true"
      className="pointer-events-none absolute inset-0 overflow-hidden"
    >
      {/* 중앙 방사형 글로우 */}
      <div
        className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 h-[700px] w-[700px] rounded-full"
        style={{
          background:
            "radial-gradient(circle, rgba(139,92,246,0.15) 0%, transparent 70%)",
        }}
      />
      {/* 좌상단 보조 글로우 */}
      <div className="absolute -left-40 -top-40 h-96 w-96 rounded-full bg-purple-600/[0.08] blur-3xl" />
      {/* 우하단 보조 글로우 */}
      <div className="absolute -bottom-20 -right-20 h-80 w-80 rounded-full bg-purple-500/[0.06] blur-3xl" />
      {/* 격자 패턴 */}
      <div
        className="absolute inset-0"
        style={{
          backgroundImage:
            "linear-gradient(rgba(255,255,255,0.02) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.02) 1px, transparent 1px)",
          backgroundSize: "64px 64px",
          maskImage: "linear-gradient(to bottom, transparent, black 20%, black 80%, transparent)",
        }}
      />
      {/* 파티클 dot */}
      <div className="absolute left-[15%] top-[25%] h-1 w-1 rounded-full bg-purple-400/40" />
      <div className="absolute right-[20%] top-[40%] h-1 w-1 rounded-full bg-purple-400/30" />
      <div className="absolute left-[60%] bottom-[30%] h-1.5 w-1.5 rounded-full bg-purple-300/20" />
    </m.div>
  );
}

export default function HeroSection() {
  return (
    <section className="relative flex min-h-screen items-center justify-center overflow-hidden bg-gray-950 px-4">
      <HeroBackground />

      <m.div
        variants={staggerContainer}
        initial="hidden"
        animate="visible"
        className="relative z-10 mx-auto max-w-3xl text-center"
      >
        {/* 배지 */}
        <m.div variants={fadeUp} className="mb-6 inline-flex items-center gap-2">
          <span className="inline-flex items-center gap-1.5 rounded-full border border-purple-500/30 bg-purple-500/10 px-3 py-1 text-xs font-medium text-purple-300">
            <span className="h-1.5 w-1.5 rounded-full bg-purple-400 animate-pulse" />
            AI-Powered Earnings Analysis
          </span>
        </m.div>

        {/* 헤드라인 */}
        <m.h1
          variants={fadeUp}
          className="mb-5 text-4xl font-bold leading-tight tracking-tight sm:text-5xl lg:text-6xl"
        >
          <span className="block text-white">어닝콜이 끝나기 전에</span>
          <span
            className="block"
            style={{
              backgroundImage: "linear-gradient(135deg, #c084fc, #a855f7, #7c3aed)",
              WebkitBackgroundClip: "text",
              WebkitTextFillColor: "transparent",
              backgroundClip: "text",
            }}
          >
            AI가 먼저 판단합니다
          </span>
        </m.h1>

        {/* 서브카피 */}
        <m.p
          variants={fadeUp}
          className="mb-8 text-base leading-relaxed text-gray-400 sm:text-lg"
        >
          실시간 음성 STT → FinBERT 감성 분석 → EMA 기반 매매 신호 자동 생성.
          <br className="hidden sm:block" />
          개인 투자자도 기관처럼 어닝콜을 활용할 수 있습니다.
        </m.p>

        {/* CTA 버튼 */}
        <m.div
          variants={fadeUp}
          className="flex flex-wrap items-center justify-center gap-3"
        >
          <Link
            href="/demo"
            className="inline-flex items-center gap-2 rounded-lg bg-purple-600 px-6 py-3 text-sm font-semibold text-white shadow-lg shadow-purple-500/30 transition-all hover:bg-purple-500 hover:shadow-purple-500/40"
          >
            데모 체험하기
            <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 7l5 5m0 0l-5 5m5-5H6" />
            </svg>
          </Link>
          <Link
            href="/auth?mode=signup"
            className="inline-flex items-center gap-2 rounded-lg border border-gray-700 px-6 py-3 text-sm font-semibold text-gray-300 transition-all hover:border-gray-500 hover:text-white"
          >
            무료 시작하기
          </Link>
        </m.div>

        {/* 스크롤 인디케이터 */}
        <m.div
          variants={fadeUp}
          className="mt-16 flex flex-col items-center gap-1 text-gray-600"
        >
          <span className="text-xs">스크롤</span>
          <m.div
            animate={{ y: [0, 6, 0] }}
            transition={{ duration: 1.5, repeat: Infinity, ease: "easeInOut" }}
          >
            <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
            </svg>
          </m.div>
        </m.div>
      </m.div>

      {/* 하단 페이드아웃 */}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute bottom-0 left-0 right-0 h-32"
        style={{ background: "linear-gradient(to bottom, transparent, #030712)" }}
      />
    </section>
  );
}
