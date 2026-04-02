"use client";

import { m } from "framer-motion";
import { fadeUp, staggerContainer, defaultViewport } from "@/lib/animation-variants";

const PAIN_POINTS = [
  {
    number: "23분",
    unit: "평균 정보 지연",
    title: "개인 투자자는 항상 늦게 알게 됩니다",
    desc: "어닝콜이 끝나고 기사가 나오고, SNS에 퍼지고, 그때 확인합니다. 이미 시장은 움직였습니다.",
    icon: (
      <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
      </svg>
    ),
  },
  {
    number: "68%",
    unit: "감정적 판단 손실 비율",
    title: "실시간 음성을 들으며 냉정하게 판단하기 어렵습니다",
    desc: "CEO가 신중하게 말하는지, 자신감 있게 말하는지. 감성을 숫자로 만들어야 판단이 가능합니다.",
    icon: (
      <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.172 16.172a4 4 0 015.656 0M9 10h.01M15 10h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
      </svg>
    ),
  },
  {
    number: "4.2초",
    unit: "판단에서 실행까지 최적 시간",
    title: "판단이 맞아도 실행이 늦으면 소용없습니다",
    desc: "AI 신호가 생성되는 순간 로컬 PC가 직접 주문을 실행합니다. 사람 손이 필요 없습니다.",
    icon: (
      <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
      </svg>
    ),
  },
];

export default function PainPointSection() {
  return (
    <section className="relative bg-gray-950 px-4 py-24 sm:py-32">
      <div className="mx-auto max-w-5xl">
        {/* 섹션 레이블 */}
        <m.div
          initial={{ opacity: 0, y: 16 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={defaultViewport}
          transition={{ duration: 0.5 }}
          className="mb-4 text-center"
        >
          <span className="text-xs font-semibold uppercase tracking-widest text-accent-400">
            The Problem
          </span>
        </m.div>

        {/* 타이틀 */}
        <m.h2
          initial={{ opacity: 0, y: 16 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={defaultViewport}
          transition={{ duration: 0.5, delay: 0.1 }}
          className="mb-4 text-center text-3xl font-bold text-white sm:text-4xl"
        >
          개인 투자자가 겪는 정보 격차
        </m.h2>
        <m.p
          initial={{ opacity: 0 }}
          whileInView={{ opacity: 1 }}
          viewport={defaultViewport}
          transition={{ duration: 0.5, delay: 0.2 }}
          className="mb-14 text-center text-gray-400"
        >
          어닝콜은 분기 실적의 핵심입니다. 하지만 개인 투자자는 구조적으로 불리합니다.
        </m.p>

        {/* 카드 그리드 */}
        <m.div
          variants={staggerContainer}
          initial="hidden"
          whileInView="visible"
          viewport={defaultViewport}
          className="grid grid-cols-1 gap-5 md:grid-cols-3"
        >
          {PAIN_POINTS.map((point) => (
            <m.div
              key={point.number}
              variants={fadeUp}
              className="group rounded-xl border border-gray-800 bg-gray-900 p-6 transition-all hover:border-accent-500/40 hover:bg-gray-900/80"
            >
              {/* 아이콘 */}
              <div className="mb-4 inline-flex h-9 w-9 items-center justify-center rounded-lg bg-accent-500/10 text-accent-400">
                {point.icon}
              </div>
              {/* 숫자 */}
              <div className="mb-1 font-mono text-3xl font-bold text-white">
                {point.number}
              </div>
              <div className="mb-3 text-xs text-gray-500">{point.unit}</div>
              {/* 텍스트 */}
              <h3 className="mb-2 text-sm font-semibold text-white">{point.title}</h3>
              <p className="text-sm leading-relaxed text-gray-400">{point.desc}</p>
            </m.div>
          ))}
        </m.div>

        {/* 수렴 화살표 */}
        <m.div
          initial={{ opacity: 0, y: 10 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={defaultViewport}
          transition={{ duration: 0.5, delay: 0.4 }}
          className="mt-10 flex flex-col items-center gap-2"
        >
          <div className="h-8 w-px bg-gradient-to-b from-gray-700 to-accent-500" />
          <span className="rounded-full border border-accent-500/40 bg-accent-500/10 px-4 py-1.5 text-sm font-medium text-accent-300">
            EarningWhisperer가 해결합니다
          </span>
        </m.div>
      </div>
    </section>
  );
}
