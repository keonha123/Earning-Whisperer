import { create } from "zustand";
import { persist, createJSONStorage } from "zustand/middleware";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8082";

/**
 * refresh_token 은 백엔드가 HttpOnly + SameSite=Strict 쿠키로 내려보내므로 JS 에서 보관하지 않는다.
 * 이 store 는 access_token 만 메모리/localStorage 에 보관. refresh / logout 은 credentials:'include' 로
 * 쿠키를 자동 첨부.
 *
 * isAuthenticated 는 access_token 보유 여부 + 페이지 새로고침 시 refresh 시도 결과로 갱신된다.
 */
interface AuthState {
  accessToken: string | null;
  isAuthenticated: boolean;
  setAccessToken: (accessToken: string) => void;
  clearTokens: () => void;
  /** AT 만료 시 HttpOnly refresh 쿠키로 갱신. 실패 시 로그아웃. */
  refresh: () => Promise<string | null>;
  logout: () => Promise<void>;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      accessToken: null,
      isAuthenticated: false,

      setAccessToken: (accessToken) =>
        set({ accessToken, isAuthenticated: true }),

      clearTokens: () => set({ accessToken: null, isAuthenticated: false }),

      refresh: async () => {
        try {
          const res = await fetch(`${API_BASE}/api/v1/auth/refresh`, {
            method: "POST",
            credentials: "include", // HttpOnly refresh_token 쿠키 자동 첨부
          });

          if (!res.ok) {
            set({ accessToken: null, isAuthenticated: false });
            return null;
          }

          const data = await res.json();
          set({ accessToken: data.access_token, isAuthenticated: true });
          return data.access_token;
        } catch {
          set({ accessToken: null, isAuthenticated: false });
          return null;
        }
      },

      logout: async () => {
        try {
          await fetch(`${API_BASE}/api/v1/auth/logout`, {
            method: "POST",
            credentials: "include",
          });
        } catch {
          // 서버 오류여도 클라이언트 측은 로그아웃 진행
        }
        set({ accessToken: null, isAuthenticated: false });
      },
    }),
    {
      name: "ew-auth",
      storage: createJSONStorage(() => localStorage),
      // refresh_token 은 더이상 store 에 있지 않으므로 access_token + isAuthenticated 만 persist.
      // (access_token 은 짧은 수명이라 페이지 새로고침 후엔 refresh() 로 즉시 회복.)
      partialize: (state) => ({
        accessToken: state.accessToken,
        isAuthenticated: state.isAuthenticated,
      }),
    }
  )
);
