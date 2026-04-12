import { create } from "zustand";
import { persist, createJSONStorage } from "zustand/middleware";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8082";

interface AuthState {
  accessToken: string | null;
  refreshToken: string | null;
  isAuthenticated: boolean;
  setTokens: (accessToken: string, refreshToken: string) => void;
  clearTokens: () => void;
  /** AT 만료 시 RT로 갱신. 실패 시 로그아웃. */
  refresh: () => Promise<string | null>;
  logout: () => Promise<void>;
}

// zustand persist: SSR hydration mismatch 없이 localStorage 자동 동기화
export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
      accessToken: null,
      refreshToken: null,
      isAuthenticated: false,

      setTokens: (accessToken, refreshToken) =>
        set({ accessToken, refreshToken, isAuthenticated: true }),

      clearTokens: () =>
        set({ accessToken: null, refreshToken: null, isAuthenticated: false }),

      refresh: async () => {
        const rt = get().refreshToken;
        if (!rt) {
          get().clearTokens();
          return null;
        }
        try {
          const res = await fetch(`${API_BASE}/api/v1/auth/refresh`, {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              "X-Refresh-Token": rt,
            },
            credentials: "include",
          });

          if (!res.ok) {
            get().clearTokens();
            return null;
          }

          const data = await res.json();
          set({
            accessToken: data.access_token,
            refreshToken: data.refresh_token,
            isAuthenticated: true,
          });
          return data.access_token;
        } catch {
          get().clearTokens();
          return null;
        }
      },

      logout: async () => {
        const rt = get().refreshToken;
        if (rt) {
          try {
            await fetch(`${API_BASE}/api/v1/auth/logout`, {
              method: "POST",
              headers: { "X-Refresh-Token": rt },
              credentials: "include",
            });
          } catch {
            // 서버 오류여도 클라이언트 측은 로그아웃 진행
          }
        }
        get().clearTokens();
      },
    }),
    {
      name: "ew-auth",
      storage: createJSONStorage(() => localStorage),
    }
  )
);
