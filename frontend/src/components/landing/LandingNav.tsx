"use client";

import Link from "next/link";
import { useState, useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import { useAuthStore } from "@/store/authStore";

const GUEST_NAV_LINKS = [
  { label: "작동 원리", href: "/#how-it-works" },
  { label: "데모 체험", href: "/demo" },
  { label: "요금제", href: "/#pricing" },
  { label: "다운로드", href: "/download" },
];

const AUTH_NAV_LINKS = [
  { label: "어닝 캘린더", href: "/earnings-calendar" },
  { label: "워치리스트", href: "/watchlist" },
  { label: "다운로드", href: "/download" },
];

function UserDropdown({ onLogout }: { onLogout: () => void }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1.5 rounded-lg border border-gray-700 px-3.5 py-2 text-sm font-medium text-gray-300 transition-colors hover:border-gray-500 hover:text-white"
      >
        <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
        </svg>
        <svg
          className={`h-3 w-3 transition-transform ${open ? "rotate-180" : ""}`}
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {open && (
        <div className="absolute right-0 top-full mt-1.5 w-36 overflow-hidden rounded-lg border border-gray-800 bg-gray-900 py-1 shadow-xl">
          <Link
            href="/mypage"
            onClick={() => setOpen(false)}
            className="flex items-center gap-2 px-3 py-2 text-sm text-gray-300 transition-colors hover:bg-gray-800 hover:text-white"
          >
            <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5.121 17.804A13.937 13.937 0 0112 16c2.5 0 4.847.655 6.879 1.804M15 10a3 3 0 11-6 0 3 3 0 016 0z" />
            </svg>
            마이페이지
          </Link>
          <div className="my-1 border-t border-gray-800" />
          <button
            onClick={() => { setOpen(false); onLogout(); }}
            className="flex w-full items-center gap-2 px-3 py-2 text-sm text-red-400 transition-colors hover:bg-gray-800"
          >
            <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" />
            </svg>
            로그아웃
          </button>
        </div>
      )}
    </div>
  );
}

export default function LandingNav() {
  const [scrolled, setScrolled] = useState(false);
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const clearToken = useAuthStore((s) => s.clearToken);
  const router = useRouter();

  useEffect(() => {
    const handleScroll = () => setScrolled(window.scrollY > 20);
    window.addEventListener("scroll", handleScroll, { passive: true });
    return () => window.removeEventListener("scroll", handleScroll);
  }, []);

  function handleLogout() {
    clearToken();
    router.push("/");
  }

  const navLinks = isAuthenticated ? AUTH_NAV_LINKS : GUEST_NAV_LINKS;

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

        {/* 중앙 네비게이션 */}
        <ul className="hidden items-center gap-6 md:flex">
          {navLinks.map((link) => (
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

        {/* 우측 */}
        <div className="flex items-center gap-2">
          {isAuthenticated ? (
            <UserDropdown onLogout={handleLogout} />
          ) : (
            <>
              <Link
                href="/auth"
                className="rounded-lg border border-gray-700 px-3.5 py-2 text-sm font-medium text-gray-300 transition-colors hover:border-gray-500 hover:text-white"
              >
                로그인
              </Link>
              <Link
                href="/auth?mode=signup"
                className="rounded-lg bg-accent-600 px-3.5 py-2 text-sm font-semibold text-white transition-colors hover:bg-accent-500"
              >
                무료 시작
              </Link>
            </>
          )}
        </div>
      </nav>
    </header>
  );
}
