"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useAuthStore } from "@/store/authStore";
import AuthLeftPanel from "@/components/auth/AuthLeftPanel";
import AuthCard from "@/components/auth/AuthCard";

type Tab = "login" | "signup";

// useSearchParams는 Suspense boundary 안에서만 사용 가능
function AuthPageInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { isAuthenticated } = useAuthStore();

  const initialTab: Tab =
    searchParams.get("mode") === "signup" ? "signup" : "login";
  const [activeTab, setActiveTab] = useState<Tab>(initialTab);

  useEffect(() => {
    if (isAuthenticated) {
      router.replace("/");
    }
  }, [isAuthenticated, router]);

  return (
    <div className="min-h-screen bg-gray-950 flex">
      <div className="hidden lg:flex lg:w-[45%]">
        <AuthLeftPanel />
      </div>
      <div className="flex-1 flex items-center justify-center px-4 py-6 sm:py-12">
        <AuthCard activeTab={activeTab} onTabChange={setActiveTab} />
      </div>
    </div>
  );
}

export default function AuthPage() {
  return (
    <Suspense fallback={<div className="min-h-screen bg-gray-950" />}>
      <AuthPageInner />
    </Suspense>
  );
}
