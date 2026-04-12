"use client";

import { Suspense, useEffect, useRef } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useAuthStore } from "@/store/authStore";
import { verifyOAuthState, getOAuthProvider, getRedirectUri } from "@/lib/oauthConfig";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8082";

function CallbackInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { setTokens } = useAuthStore();
  const calledRef = useRef(false);

  useEffect(() => {
    if (calledRef.current) return;
    calledRef.current = true;

    const code = searchParams.get("code");
    const state = searchParams.get("state");
    const error = searchParams.get("error");

    if (error || !code || !verifyOAuthState(state)) {
      router.replace("/auth?error=oauth_failed");
      return;
    }

    const provider = getOAuthProvider();
    const redirectUri = getRedirectUri(provider);

    (async () => {
      try {
        const res = await fetch(`${API_BASE}/api/v1/auth/oauth/callback`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "include",
          body: JSON.stringify({
            code,
            redirect_uri: redirectUri,
            provider,
          }),
        });

        if (!res.ok) {
          router.replace("/auth?error=oauth_failed");
          return;
        }

        const data = await res.json();
        setTokens(data.access_token, data.refresh_token);
        router.replace("/");
      } catch {
        router.replace("/auth?error=oauth_failed");
      } finally {
        sessionStorage.removeItem("oauth_provider");
      }
    })();
  }, [searchParams, router, setTokens]);

  return (
    <div className="min-h-screen bg-gray-950 flex items-center justify-center">
      <div className="text-gray-400 text-sm">로그인 처리 중...</div>
    </div>
  );
}

export default function OAuthCallbackPage() {
  return (
    <Suspense fallback={<div className="min-h-screen bg-gray-950" />}>
      <CallbackInner />
    </Suspense>
  );
}
