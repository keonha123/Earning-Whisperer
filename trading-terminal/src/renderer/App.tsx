import { useEffect } from 'react'
import { HashRouter, Routes, Route, Navigate, useNavigate } from 'react-router-dom'
import { ipc, IPC_CHANNELS } from './lib/ipc'
import { useConnectionStore } from './store/useConnectionStore'
import { usePortfolioStore } from './store/usePortfolioStore'
import { useUserStore } from './store/useUserStore'
import { useAssistantStore } from './store/useAssistantStore'

import AuthPage from './pages/AuthPage'
import HomePage from './pages/HomePage'
import TradingRoomPage from './pages/TradingRoomPage'
import MarketPage from './pages/MarketPage'
import PortfolioPage from './pages/PortfolioPage'
import SettingsPage from './pages/SettingsPage'
import AppLayout from './components/layout/AppLayout'
import { AppToaster, setAuthExpiredHandler } from './components/common/Toast'

function RequireAuth({ children }: { children: React.ReactNode }) {
  const isAuthenticated = useConnectionStore((s) => s.isAuthenticated)
  if (!isAuthenticated) return <Navigate to="/auth" replace />
  return <>{children}</>
}

export default function App() {
  return (
    <HashRouter>
      <AppToaster />
      <AppRoutes />
    </HashRouter>
  )
}

function AppRoutes() {
  const { isAuthenticated, setWsStatus, setKisTokenStatus, setAuthenticated } = useConnectionStore()
  const { setBalance } = usePortfolioStore()
  const { clear } = useUserStore()
  const navigate = useNavigate()

  // 인증 상태 변화 시 WebSocket 연결/해제
  useEffect(() => {
    if (isAuthenticated) {
      ipc.invoke(IPC_CHANNELS.WS_CONNECT)
    } else {
      ipc.invoke(IPC_CHANNELS.WS_DISCONNECT)
      // 로그아웃 · 로그인 만료 · 사용자 전환 때 이전 사용자의 질의응답 대화가 남지 않게 비운다(진행 중이면 취소)
      useAssistantStore.getState().reset()
    }
  }, [isAuthenticated])

  // AUTH_EXPIRED 전역 핸들러 등록 — 호출 사이트가 onNavigate 를 주입하지 않은 9곳에서
  // 자동으로 토큰 폐기 + /auth 라우팅이 일어나도록 한다 (review F1).
  useEffect(() => {
    setAuthExpiredHandler(() => {
      setAuthenticated(false)
      clear()
      navigate('/auth')
    })
    return () => setAuthExpiredHandler(null)
  }, [setAuthenticated, clear, navigate])

  useEffect(() => {
    const unsubs = [
      ipc.on(IPC_CHANNELS.WS_STATUS_CHANGED, (payload: any) => {
        setWsStatus(payload.status)
      }),

      ipc.on(IPC_CHANNELS.SELF_PAPER_BALANCE_UPDATED, (payload: any) => {
        const { cash, holdings: newHoldings } = payload as {
          cash: number
          holdings: { ticker: string; qty: number }[]
        }
        const prev = usePortfolioStore.getState().holdings
        const merged = newHoldings.map((h) => {
          const existing = prev.find((p) => p.ticker === h.ticker)
          return {
            ticker: h.ticker,
            qty: h.qty,
            avgPrice: existing?.avgPrice ?? 0,
            currentPrice: existing?.currentPrice ?? 0,
          }
        })
        setBalance(cash, cash, merged)
      }),

      ipc.on(IPC_CHANNELS.KIS_TOKEN_REFRESHED, (payload: any) => {
        setKisTokenStatus(payload.isValid ? 'VALID' : 'EXPIRED')
      }),
    ]

    return () => unsubs.forEach((fn) => fn())
  }, [])

  return (
    <>
      <Routes>
        <Route path="/auth" element={<AuthPage />} />
        <Route
          path="/*"
          element={
            <RequireAuth>
              <AppLayout>
                <Routes>
                  <Route path="/" element={<Navigate to="/home" replace />} />
                  <Route path="/home" element={<HomePage />} />
                  <Route path="/stocks" element={<MarketPage />} />
                  <Route path="/call" element={<TradingRoomPage />} />
                  <Route path="/portfolio" element={<PortfolioPage />} />
                  <Route path="/settings" element={<SettingsPage />} />
                  <Route path="*" element={<Navigate to="/home" replace />} />
                </Routes>
              </AppLayout>
            </RequireAuth>
          }
        />
      </Routes>
    </>
  )
}
