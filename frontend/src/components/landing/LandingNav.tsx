"use client";

import Link from "next/link";
import { useState, useEffect } from "react";
import { useAuthStore } from "@/store/authStore";

const NAV_LINKS = [
  { label: "작동 원리", href: "#how-it-works" },
  { label: "데모 체험", href: "/demo" },
  { label: "요금제", href: "#pricing" },
];

export default function LandingNav() {
  const [scrolled, setScrolled] = useState(false);
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);

  useEffect(() => {
    const handleScroll = () => setScrolled(window.scrollY > 20);
    window.addEventListener("scroll", handleScroll, { passive: true });
    return () => window.removeEventListener("scroll", handleScroll);
  }, []);

  return (
    <header
      className={`fixed inset-x-0 top-0 z-40 transition-all duration-300 ${
        scrolled
          ? "border-b border-gray-800/60 bg-gray-950/90 backdrop-blur-md"
          : "bg-transparent"
      }`}
    >
      <nav className="mx-auto flex max-w-6xl items-center justify-between px-4 py-3 sm:py-4">
        {/* 로고 */}
        <Link href="/" className="flex items-center gap-2 text-sm font-bold text-white">
          <span
            className="flex h-6 w-6 items-center justify-center rounded-md bg-accent-600 text-xs font-black text-white"
            aria-hidden="true"
          >
            EW
          </span>
          EarningWhisperer
        </Link>

        {/* 중앙 네비게이션 링크 */}
        <ul className="hidden items-center gap-6 md:flex">
          {NAV_LINKS.map((link) => (
            <li key={link.href}>
              <Link
                href={link.href}
                className="text-sm text-gray-400 transition-colors hover:text-white"
              >
                {link.label}
              </Link>
            </li>
          ))}
        </ul>

        {/* 우측 CTA */}
        <div className="flex items-center gap-2">
          {isAuthenticated ? (
            <Link
              href="/mypage"
              className="rounded-lg border border-gray-700 px-3.5 py-2 text-sm font-medium text-gray-300 transition-colors hover:border-gray-500 hover:text-white"
            >
              마이페이지
            </Link>
          ) : (
            <Link
              href="/auth"
              className="rounded-lg border border-gray-700 px-3.5 py-2 text-sm font-medium text-gray-300 transition-colors hover:border-gray-500 hover:text-white"
            >
              로그인
            </Link>
          )}
          <Link
            href="/auth?mode=signup"
            className="rounded-lg bg-accent-600 px-3.5 py-2 text-sm font-semibold text-white transition-colors hover:bg-accent-500"
          >
            무료 시작
          </Link>
        </div>
      </nav>
    </header>
  );
}
