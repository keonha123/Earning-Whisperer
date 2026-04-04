"use client";

import { useState, useEffect } from "react";

const THEMES = [
  { id: "purple", label: "보라", color: "#a855f7" },
  { id: "blue",   label: "파랑", color: "#3b82f6" },
  { id: "teal",   label: "청록", color: "#14b8a6" },
  { id: "emerald",label: "에메랄드", color: "#10b981" },
  { id: "amber",  label: "앰버", color: "#f59e0b" },
] as const;

type ThemeId = (typeof THEMES)[number]["id"];

export default function ThemeSwitcher() {
  const [current, setCurrent] = useState<ThemeId>("purple");
  const [open, setOpen] = useState(false);

  useEffect(() => {
    const root = document.documentElement;
    if (current === "purple") {
      root.removeAttribute("data-theme");
    } else {
      root.setAttribute("data-theme", current);
    }
  }, [current]);

  const active = THEMES.find((t) => t.id === current)!;

  return (
    <div className="fixed bottom-6 right-6 z-50 flex flex-col items-end gap-2">
      {/* 테마 선택 팔레트 */}
      {open && (
        <div className="flex flex-col gap-1.5 rounded-xl border border-gray-700 bg-gray-900/95 p-2 shadow-xl backdrop-blur-sm">
          <p className="mb-1 px-1 text-[10px] font-semibold uppercase tracking-wider text-gray-500">
            Accent Color
          </p>
          {THEMES.map((theme) => (
            <button
              key={theme.id}
              onClick={() => setCurrent(theme.id)}
              className="flex items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-left text-xs text-gray-300 transition-colors hover:bg-gray-800"
            >
              <span
                className="h-3.5 w-3.5 flex-shrink-0 rounded-full"
                style={{
                  backgroundColor: theme.color,
                  boxShadow: current === theme.id ? `0 0 0 2px #1f2937, 0 0 0 3.5px ${theme.color}` : "none",
                }}
              />
              <span className={current === theme.id ? "font-semibold text-white" : ""}>
                {theme.label}
              </span>
              {current === theme.id && (
                <svg className="ml-auto h-3 w-3 text-white" fill="currentColor" viewBox="0 0 12 12">
                  <path d="M10 3L5 8.5 2 5.5" stroke="currentColor" strokeWidth="1.5" fill="none" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              )}
            </button>
          ))}
        </div>
      )}

      {/* 토글 버튼 */}
      <button
        onClick={() => setOpen((v) => !v)}
        title="테마 색상 전환"
        className="flex h-10 w-10 items-center justify-center rounded-full border border-gray-700 bg-gray-900/90 shadow-lg backdrop-blur-sm transition-all hover:border-gray-500"
        style={{ boxShadow: `0 0 12px ${active.color}33` }}
      >
        <span
          className="h-4 w-4 rounded-full"
          style={{ backgroundColor: active.color }}
        />
      </button>
    </div>
  );
}
