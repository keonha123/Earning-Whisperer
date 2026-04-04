import { useEffect } from 'react'
import { HashRouter, Routes, Route, Navigate } from 'react-router-dom'
import { ipc, IPC_CHANNELS } from './lib/ipc'
import { useConnectionStore } from './store/useConnectionStore'
import { useTradingStore } from './store/useTradingStore'
import { usePortfolioStore } from './store/usePortfolioStore'

import AuthPage from './pages/AuthPage'
import DashboardPage from './pages/DashboardPage'
import TradingRoomPage from './pages/TradingRoomPage'
import HistoryPage from './pages/HistoryPage'
import SettingsPage from './pages/SettingsPage'
import AppLayout from './components/layout/AppLayout'
import TradeConfirmDialog from './components/trading/TradeConfirmDialog'

function RequireAuth({ children }: { children: React.ReactNode }) {
  const isAuthenticated = useConnectionStore((s) => s.isAuthenticated)
  if (!isAuthenticated) return <Navigate to="/auth" replace />
  return <>{children}</>
}

export default function App() {
  const { setWsStatus, setKisTokenStatus, setAuthenticated } = useConnectionStore()
  const { forceManual, receiveSignal, updateSignalStatus, setLastExecutedTrade, pendingConfirm, setPendingConfirm } = useTradingStore()
  const { setBalance } = usePortfolioStore()

  useEffect(() => {
    const unsubs = [
      ipc.on(IPC_CHANNELS.WS_STATUS_CHANGED, (payload: any) => {
        setWsStatus(payload.status)
        if (payload.status === 'CONNECTED') {
          useConnectionStore.getState().clearForcedManual?.()
        }
      }),

      ipc.on(IPC_CHANNELS.MODE_FORCED_MANUAL, (payload: any) => {
        forceManual(payload.reason)
      }),

      ipc.on(IPC_CHANNELS.SIGNAL_RECEIVED, (payload: any) => {
        receiveSignal(payload)
      }),

      ipc.on(IPC_CHANNELS.TRADE_EXECUTED, (payload: any) => {
        setLastExecutedTrade(payload)
        updateSignalStatus(payload.tradeId, 'EXECUTED')
        setPendingConfirm(null)
      }),

      ipc.on(IPC_CHANNELS.TRADE_FAILED, (payload: any) => {
        setLastExecutedTrade(payload)
        updateSignalStatus(payload.tradeId, 'FAILED')
        setPendingConfirm(null)
      }),

      ipc.on(IPC_CHANNELS.KIS_TOKEN_REFRESHED, (payload: any) => {
        setKisTokenStatus(payload.isValid ? 'VALID' : 'EXPIRED')
      }),
    ]

    return () => unsubs.forEach((fn) => fn())
  }, [])

  return (
    <HashRouter>
      <Routes>
        <Route path="/auth" element={<AuthPage />} />
        <Route
          path="/*"
          element={
            <RequireAuth>
              <AppLayout>
                <Routes>
                  <Route path="/" element={<Navigate to="/dashboard" replace />} />
                  <Route path="/dashboard" element={<DashboardPage />} />
                  <Route path="/trading-room" element={<TradingRoomPage />} />
                  <Route path="/history" element={<HistoryPage />} />
                  <Route path="/settings" element={<SettingsPage />} />
                </Routes>
              </AppLayout>
            </RequireAuth>
          }
        />
      </Routes>

      {/* 전역 SEMI_AUTO 확인 다이얼로그 */}
      {pendingConfirm && (
        <TradeConfirmDialog
          signal={pendingConfirm}
          timeoutSeconds={30}
          onApprove={async () => {
            await ipc.invoke(IPC_CHANNELS.KIS_PLACE_ORDER, pendingConfirm)
          }}
          onReject={() => {
            updateSignalStatus(pendingConfirm.trade_id, 'REJECTED')
            setPendingConfirm(null)
          }}
          onTimeout={() => {
            updateSignalStatus(pendingConfirm.trade_id, 'IGNORED')
            setPendingConfirm(null)
          }}
        />
      )}
    </HashRouter>
  )
}
