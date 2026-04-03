"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { m } from "framer-motion";
import { useAuthStore } from "@/store/authStore";
import LandingNav from "@/components/landing/LandingNav";
import ProfileHeader from "@/components/mypage/ProfileHeader";
import TabNav, { MypageTab } from "@/components/mypage/TabNav";
import TradeHistoryTab from "@/components/mypage/TradeHistoryTab";
import SubscriptionTab from "@/components/mypage/SubscriptionTab";
import SettingsTab from "@/components/mypage/SettingsTab";

const API_URL = process.env.NEXT_PUBLIC_API_URL;

interface UserData {
  id: number;
  email: string;
  nickname: string;
  role: "FREE" | "PRO";
  createdAt: string;
}

interface Trade {
  id: number;
  ticker: string;
  side: "BUY" | "SELL";
  orderQty: number;
  executedQty: number;
  status: "PENDING" | "EXECUTED" | "FAILED";
  createdAt: string;
}

/* 스켈레톤 컴포넌트 */
function Skeleton({ className }: { className?: string }) {
  return <div className={`animate-pulse rounded-md bg-gray-800 ${className}`} />;
}

function PageSkeleton() {
  return (
    <div className="space-y-6">
      <div className="flex items-center gap-4">
        <Skeleton className="h-12 w-12 rounded-xl" />
        <div className="space-y-2">
          <Skeleton className="h-5 w-32" />
          <Skeleton className="h-4 w-48" />
        </div>
      </div>
      <Skeleton className="h-10 w-64" />
      <div className="space-y-3">
        {[...Array(5)].map((_, i) => (
          <Skeleton key={i} className="h-12 w-full" />
        ))}
      </div>
    </div>
  );
}

export default function MypagePage() {
  const router = useRouter();
  const { accessToken, isAuthenticated } = useAuthStore();
  const [tab, setTab] = useState<MypageTab>("trades");
  const [user, setUser] = useState<UserData | null>(null);
  const [trades, setTrades] = useState<Trade[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!isAuthenticated || !accessToken) {
      router.replace("/auth");
      return;
    }

    const headers = { Authorization: `Bearer ${accessToken}` };

    Promise.all([
      fetch(`${API_URL}/api/v1/users/me`, { headers }).then((r) => {
        if (!r.ok) throw new Error("사용자 정보를 불러올 수 없습니다");
        return r.json() as Promise<UserData>;
      }),
      fetch(`${API_URL}/api/v1/trades?page=0&size=20`, { headers }).then((r) => {
        if (!r.ok) throw new Error("거래 내역을 불러올 수 없습니다");
        return r.json();
      }),
    ])
      .then(([userData, tradesPage]) => {
        setUser(userData);
        setTrades(tradesPage.content ?? []);
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [isAuthenticated, accessToken, router]);

  if (!isAuthenticated) return null;

  return (
    <>
      <LandingNav />
    <main className="min-h-screen bg-gray-950 px-4 pt-20 pb-16">
      <div className="mx-auto max-w-3xl">
        {loading ? (
          <PageSkeleton />
        ) : error ? (
          <div className="rounded-xl border border-red-500/20 bg-red-500/5 p-6 text-center text-sm text-red-400">
            {error}
          </div>
        ) : user ? (
          <m.div
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.4 }}
            className="space-y-6"
          >
            <ProfileHeader
              nickname={user.nickname}
              email={user.email}
              role={user.role}
              createdAt={user.createdAt}
            />

            <div className="rounded-xl border border-gray-800 bg-gray-900/50">
              <TabNav active={tab} onChange={setTab} />
              <div className="p-5">
                {tab === "trades" && <TradeHistoryTab trades={trades} />}
                {tab === "subscription" && <SubscriptionTab role={user.role} />}
                {tab === "settings" && <SettingsTab email={user.email} />}
              </div>
            </div>
          </m.div>
        ) : null}
      </div>
    </main>
    </>
  );
}
