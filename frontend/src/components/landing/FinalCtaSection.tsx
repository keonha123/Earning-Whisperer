"use client";

import Link from "next/link";
import { m } from "framer-motion";
import { defaultViewport } from "@/lib/animation-variants";

const PLANS = [
  {
    name: "Free",
    price: "₩0",
    period: "영구 무료",
    features: ["실시간 AI 신호 열람", "데모룸 무제한 체험", "EMA 차트 & 감성 분석"],
    cta: "무료 시작",
    href: "/auth?mode=signup",
    highlight: false,
  },
  {
    name: "Pro",
    price: "₩29,900",
    period: "/월",
    features: ["Free 플랜 전체 포함", "Trading Terminal 다운로드", "AUTO_PILOT 자동매매 모드", "우선 기술 지원"],
    cta: "Pro 시작하기",
    href: "/auth?mode=signup",
    highlight: true,
  },
];

export default function FinalCtaSection() {
  return (
    <section className="relative bg-gray-950 px-4 py-24 sm:py-32">
      {/* 배경 글로우 */}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute left-1/2 top-1/2 h-[500px] w-[500px] -translate-x-1/2 -translate-y-1/2 rounded-full"
        style={{
          background: "radial-gradient(circle, rgba(139,92,246,0.08) 0%, transparent 70%)",
        }}
      />

      <div className="relative mx-auto max-w-4xl">
        {/* 섹션 레이블 */}
        <m.div
          initial={{ opacity: 0, y: 16 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={defaultViewport}
          transition={{ duration: 0.5 }}
          className="mb-4 text-center"
        >
          <span className="text-xs font-semibold uppercase tracking-widest text-purple-400">
            Get Started
          </span>
        </m.div>

        <m.h2
          initial={{ opacity: 0, y: 16 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={defaultViewport}
          transition={{ duration: 0.5, delay: 0.1 }}
          className="mb-4 text-center text-3xl font-bold text-white sm:text-4xl"
        >
          지금 바로 체험해보세요
        </m.h2>
        <m.p
          initial={{ opacity: 0 }}
          whileInView={{ opacity: 1 }}
          viewport={defaultViewport}
          transition={{ duration: 0.5, delay: 0.2 }}
          className="mb-12 text-center text-gray-400"
        >
          데모룸에서 AI 분석을 먼저 확인하고, 준비가 되면 Trading Terminal을 활성화하세요.
        </m.p>

        {/* 플랜 카드 */}
        <m.div
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={defaultViewport}
          transition={{ duration: 0.6, delay: 0.2 }}
          className="mb-10 grid grid-cols-1 gap-4 sm:grid-cols-2"
        >
          {PLANS.map((plan) => (
            <div
              key={plan.name}
              className={`rounded-xl p-6 ${
                plan.highlight
                  ? "border border-purple-500/40 bg-gradient-to-b from-purple-500/10 to-gray-900/80"
                  : "border border-gray-800 bg-gray-900"
              }`}
            >
              {plan.highlight && (
                <span className="mb-3 inline-block rounded-full bg-purple-500/20 px-2.5 py-0.5 text-xs font-semibold text-purple-300">
                  추천
                </span>
              )}
              <div className="mb-1 text-lg font-bold text-white">{plan.name}</div>
              <div className="mb-4 flex items-baseline gap-1">
                <span className="font-mono text-2xl font-bold text-white">{plan.price}</span>
                <span className="text-sm text-gray-500">{plan.period}</span>
              </div>
              <ul className="mb-6 space-y-2">
                {plan.features.map((f) => (
                  <li key={f} className="flex items-center gap-2 text-sm text-gray-300">
                    <svg className="h-3.5 w-3.5 flex-shrink-0 text-purple-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 13l4 4L19 7" />
                    </svg>
                    {f}
                  </li>
                ))}
              </ul>
              <Link
                href={plan.href}
                className={`block w-full rounded-lg py-2.5 text-center text-sm font-semibold transition-colors ${
                  plan.highlight
                    ? "bg-purple-600 text-white hover:bg-purple-500"
                    : "border border-gray-700 text-gray-300 hover:border-gray-500 hover:text-white"
                }`}
              >
                {plan.cta}
              </Link>
            </div>
          ))}
        </m.div>

        {/* 데모 체험 CTA */}
        <m.div
          initial={{ opacity: 0 }}
          whileInView={{ opacity: 1 }}
          viewport={defaultViewport}
          transition={{ duration: 0.5, delay: 0.3 }}
          className="mb-10 text-center"
        >
          <Link
            href="/demo"
            className="inline-flex items-center gap-2 text-sm text-gray-400 transition-colors hover:text-purple-300"
          >
            <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z" />
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            먼저 데모룸에서 무료로 체험하기
          </Link>
        </m.div>

        {/* 보안 안내 문구 — Frontend CLAUDE.md 필수 요구사항 */}
        <m.div
          initial={{ opacity: 0 }}
          whileInView={{ opacity: 1 }}
          viewport={defaultViewport}
          transition={{ duration: 0.5, delay: 0.4 }}
          className="rounded-lg border border-gray-800 bg-gray-900/50 px-5 py-4 text-center"
        >
          <div className="mb-1 flex items-center justify-center gap-1.5 text-xs font-medium text-gray-400">
            <svg className="h-3.5 w-3.5 text-green-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
            </svg>
            보안 안내
          </div>
          <p className="text-xs leading-relaxed text-gray-500">
            보안을 위해 실제 증권사 API 키는 웹에 저장되지 않으며,
            PC에 설치된 로컬 에이전트 앱 내부에만 암호화되어 보관됩니다.
          </p>
        </m.div>
      </div>
    </section>
  );
}
