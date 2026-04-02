import { create } from "zustand";
import { persist, createJSONStorage } from "zustand/middleware";

interface AuthState {
  accessToken: string | null;
  isAuthenticated: boolean;
  setToken: (token: string) => void;
  clearToken: () => void;
}

// zustand persist: SSR hydration mismatch 없이 localStorage 자동 동기화
export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      accessToken: null,
      isAuthenticated: false,
      setToken: (token) => set({ accessToken: token, isAuthenticated: true }),
      clearToken: () => set({ accessToken: null, isAuthenticated: false }),
    }),
    {
      name: "ew-auth",
      storage: createJSONStorage(() => localStorage),
    }
  )
);
