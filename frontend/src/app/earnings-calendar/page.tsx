"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuthStore } from "@/store/authStore";
import LandingNav from "@/components/landing/LandingNav";

const API_URL = process.env.NEXT_PUBLIC_API_URL;

interface EarningsEntry {
  ticker: string;
  companyName: string;
  scheduledAt: number;
  confirmed: boolean;
}

function formatDate(epochSec: number): string {
  return new Date(epochSec * 1000).toLocaleDateString("ko-KR", {
    year: "numeric",
    month: "short",
    day: "numeric",
    weekday: "short",
    timeZone: "Asia/Seoul",
  });
}

function daysFromNow(epochSec: number): number {
  return Math.ceil((epochSec * 1000 - Date.now()) / (1000 * 60 * 60 * 24));
}

function DaysLabel({ epochSec }: { epochSec: number }) {
  const days = daysFromNow(epochSec);
  if (days < 0) return <span className="text-xs text-gray-600">종료됨</span>;
  if (days === 0) return <span className="rounded-full bg-red-500/10 px-2 py-0.5 text-xs font-semibold text-red-400">오늘</span>;
  if (days <= 7) return <span className="rounded-full bg-accent-500/10 px-2 py-0.5 text-xs font-semibold text-accent-400">D-{days}</span>;
  return <span className="text-xs text-gray-500">D-{days}</span>;
}

export default function EarningsCalendarPage() {
  const router = useRouter();
  const { accessToken, isAuthenticated } = useAuthStore();
  const [entries, setEntries] = useState<EarningsEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!isAuthenticated || !accessToken) { router.replace("/auth"); return; }

    fetch(`${API_URL}/api/v1/earnings-calendar?days=90`, {
      headers: { Authorization: `Bearer ${accessToken}` },
    })
      .then((r) => { if (!r.ok) throw new Error(); return r.json(); })
      .then(setEntries)
      .catch(() => setError("어닝 일정을 불러올 수 없습니다."))
      .finally(() => setLoading(false));
  }, [isAuthenticated, accessToken]);

  if (!isAuthenticated) return null;

  return (
    <>
      <LandingNav />
      <main className="min-h-screen bg-gray-950 px-4 pt-20 pb-16">
        <div className="mx-auto max-w-3xl">
          <div className="mb-6">
            <h1 className="text-xl font-bold text-white">어닝 캘린더</h1>
            <p className="mt-0.5 text-xs text-gray-500">내 관심종목의 향후 90일 어닝콜 일정</p>
          </div>

          {error && (
            <div className="mb-4 rounded-xl border border-red-500/20 bg-red-500/5 px-4 py-3 text-sm text-red-400">
              {error}
            </div>
          )}

          {loading ? (
            <div className="space-y-2">
              {[...Array(6)].map((_, i) => (
                <div key={i} className="h-14 animate-pulse rounded-xl bg-gray-800" />
              ))}
            </div>
          ) : entries.length === 0 ? (
            <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-gray-800 py-16 text-center">
              <svg className="mb-3 h-8 w-8 text-gray-700" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
              </svg>
              <p className="text-sm text-gray-600">예정된 어닝콜이 없습니다</p>
              <p className="mt-1 text-xs text-gray-700">
                관심종목을 추가하거나 어닝 데이터가 아직 수집되지 않았을 수 있습니다
              </p>
            </div>
          ) : (
            <div className="space-y-2">
              {entries.map((entry) => (
                <div
                  key={`${entry.ticker}-${entry.scheduledAt}`}
                  className="flex items-center gap-4 rounded-xl border border-gray-800 bg-gray-900/50 px-4 py-3"
                >
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-sm font-bold text-white">{entry.ticker}</span>
                      {!entry.confirmed && (
                        <span className="rounded bg-gray-800 px-1.5 py-0.5 text-xs text-gray-500">예상</span>
                      )}
                    </div>
                    <p className="mt-0.5 truncate text-xs text-gray-500">{entry.companyName}</p>
                  </div>
                  <div className="text-right">
                    <p className="text-xs text-gray-400">{formatDate(entry.scheduledAt)}</p>
                    <div className="mt-0.5 flex justify-end">
                      <DaysLabel epochSec={entry.scheduledAt} />
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </main>
    </>
  );
}
