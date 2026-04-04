"use client";

import { useEffect, useState, useRef } from "react";
import { useRouter } from "next/navigation";
import { useAuthStore } from "@/store/authStore";
import LandingNav from "@/components/landing/LandingNav";

const API_URL = process.env.NEXT_PUBLIC_API_URL;

interface Stock {
  ticker: string;
  companyName: string;
  sector: string;
}

interface WatchlistItem extends Stock {}

function useDebounce<T>(value: T, delay: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(timer);
  }, [value, delay]);
  return debounced;
}

function SearchBar({
  onAdd,
  headers,
}: {
  onAdd: (ticker: string) => void;
  headers: Record<string, string>;
}) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<Stock[]>([]);
  const [open, setOpen] = useState(false);
  const debouncedQuery = useDebounce(query, 300);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!debouncedQuery.trim()) { setResults([]); return; }
    fetch(`${API_URL}/api/v1/watchlist/search?q=${encodeURIComponent(debouncedQuery)}`, { headers })
      .then((r) => r.json())
      .then(setResults)
      .catch(() => setResults([]));
  }, [debouncedQuery]);

  useEffect(() => {
    function handler(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  return (
    <div ref={ref} className="relative">
      <div className="flex items-center gap-2 rounded-xl border border-gray-700 bg-gray-900 px-4 py-2.5">
        <svg className="h-4 w-4 flex-shrink-0 text-gray-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
        </svg>
        <input
          value={query}
          onChange={(e) => { setQuery(e.target.value); setOpen(true); }}
          onFocus={() => setOpen(true)}
          placeholder="종목명 또는 심볼 검색 (예: NVDA, Apple)"
          className="flex-1 bg-transparent text-sm text-white placeholder-gray-500 outline-none"
        />
        {query && (
          <button onClick={() => { setQuery(""); setResults([]); }} className="text-gray-600 hover:text-gray-400">
            <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        )}
      </div>

      {open && results.length > 0 && (
        <div className="absolute left-0 right-0 top-full z-20 mt-1 overflow-hidden rounded-xl border border-gray-800 bg-gray-900 shadow-xl">
          {results.map((s) => (
            <button
              key={s.ticker}
              onClick={() => { onAdd(s.ticker); setQuery(""); setResults([]); setOpen(false); }}
              className="flex w-full items-center justify-between px-4 py-2.5 text-left transition-colors hover:bg-gray-800"
            >
              <div>
                <span className="text-sm font-semibold text-white">{s.ticker}</span>
                <span className="ml-2 text-xs text-gray-400">{s.companyName}</span>
              </div>
              <span className="rounded bg-gray-800 px-2 py-0.5 text-xs text-gray-500">{s.sector}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function WatchlistRow({
  item,
  onRemove,
}: {
  item: WatchlistItem;
  onRemove: (ticker: string) => void;
}) {
  return (
    <div className="flex items-center gap-4 rounded-xl border border-gray-800 bg-gray-900/50 px-4 py-3 transition-colors hover:border-gray-700 hover:bg-gray-900">
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="font-mono text-sm font-bold text-white">{item.ticker}</span>
          <span className="rounded bg-gray-800 px-1.5 py-0.5 text-xs text-gray-500">{item.sector}</span>
        </div>
        <p className="mt-0.5 truncate text-xs text-gray-500">{item.companyName}</p>
      </div>

      {/* 주가·어닝 일정은 Data Pipeline 연동 후 추가 예정 */}
      <div className="hidden text-xs text-gray-600 sm:block">—</div>

      <button
        onClick={() => onRemove(item.ticker)}
        className="flex-shrink-0 rounded-lg p-1.5 text-gray-600 transition-colors hover:bg-gray-800 hover:text-red-400"
        title="관심종목 삭제"
      >
        <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
        </svg>
      </button>
    </div>
  );
}

export default function WatchlistPage() {
  const router = useRouter();
  const { accessToken, isAuthenticated } = useAuthStore();
  const [items, setItems] = useState<WatchlistItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const headers = { Authorization: `Bearer ${accessToken}` };

  useEffect(() => {
    if (!isAuthenticated || !accessToken) { router.replace("/auth"); return; }

    fetch(`${API_URL}/api/v1/watchlist`, { headers })
      .then((r) => { if (!r.ok) throw new Error(); return r.json(); })
      .then(setItems)
      .catch(() => setError("관심종목을 불러올 수 없습니다."))
      .finally(() => setLoading(false));
  }, [isAuthenticated, accessToken]);

  async function handleAdd(ticker: string) {
    const r = await fetch(`${API_URL}/api/v1/watchlist`, {
      method: "POST",
      headers: { ...headers, "Content-Type": "application/json" },
      body: JSON.stringify({ ticker }),
    });
    if (!r.ok) {
      const body = await r.json().catch(() => ({}));
      setError(body.error ?? "추가에 실패했습니다.");
      return;
    }
    const item = await r.json();
    setItems((prev) => [item, ...prev]);
    setError(null);
  }

  async function handleRemove(ticker: string) {
    const r = await fetch(`${API_URL}/api/v1/watchlist/${ticker}`, {
      method: "DELETE",
      headers,
    });
    if (r.ok) setItems((prev) => prev.filter((i) => i.ticker !== ticker));
  }

  if (!isAuthenticated) return null;

  return (
    <>
      <LandingNav />
      <main className="min-h-screen bg-gray-950 px-4 pt-20 pb-16">
        <div className="mx-auto max-w-3xl">
          <div className="mb-6 flex items-center justify-between">
            <div>
              <h1 className="text-xl font-bold text-white">관심종목</h1>
              <p className="mt-0.5 text-xs text-gray-500">S&P 500 종목을 검색하여 추가하세요</p>
            </div>
            <span className="rounded-full border border-gray-800 px-2.5 py-1 text-xs text-gray-500">
              {items.length}개
            </span>
          </div>

          <div className="mb-4">
            <SearchBar onAdd={handleAdd} headers={headers} />
          </div>

          {error && (
            <div className="mb-4 rounded-xl border border-red-500/20 bg-red-500/5 px-4 py-3 text-sm text-red-400">
              {error}
            </div>
          )}

          {loading ? (
            <div className="space-y-2">
              {[...Array(5)].map((_, i) => (
                <div key={i} className="h-14 animate-pulse rounded-xl bg-gray-800" />
              ))}
            </div>
          ) : items.length === 0 ? (
            <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-gray-800 py-16 text-center">
              <svg className="mb-3 h-8 w-8 text-gray-700" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M11.049 2.927c.3-.921 1.603-.921 1.902 0l1.519 4.674a1 1 0 00.95.69h4.915c.969 0 1.371 1.24.588 1.81l-3.976 2.888a1 1 0 00-.363 1.118l1.518 4.674c.3.922-.755 1.688-1.538 1.118l-3.976-2.888a1 1 0 00-1.176 0l-3.976 2.888c-.783.57-1.838-.197-1.538-1.118l1.518-4.674a1 1 0 00-.363-1.118l-3.976-2.888c-.784-.57-.38-1.81.588-1.81h4.914a1 1 0 00.951-.69l1.519-4.674z" />
              </svg>
              <p className="text-sm text-gray-600">관심종목이 없습니다</p>
              <p className="mt-1 text-xs text-gray-700">위 검색창에서 종목을 추가해보세요</p>
            </div>
          ) : (
            <div className="space-y-2">
              {items.map((item) => (
                <WatchlistRow key={item.ticker} item={item} onRemove={handleRemove} />
              ))}
            </div>
          )}
        </div>
      </main>
    </>
  );
}
