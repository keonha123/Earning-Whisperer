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
  const { isAuthenticated, setWsStatus, setKisTokenStatus, setAuthenticated } = useConnectionStore()
  const { forceManual, receiveSignal, updateSignalStatus, setLastExecutedTrade, pendingConfirm, setPendingConfirm } = useTradingStore()
  const { setBalance } = usePortfolioStore()

  // 인증 상태 변화 시 WebSocket 연결/해제
  useEffect(() => {
    if (isAuthenticated) {
      ipc.invoke(IPC_CHANNELS.WS_CONNECT)
    } else {
      ipc.invoke(IPC_CHANNELS.WS_DISCONNECT)
    }
  }, [isAuthenticated])

  useEffect(() => {
    const unsubs = [
      ipc.on(IPC_CHANNELS.WS_STATUS_CHANGED, (payload: any) => {
        setWsStatus(payload.status)
        if (payload.status === 'CONNECTED') {
          useTradingStore.getState().clearForcedManual()
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
            try {
              await ipc.invoke(IPC_CHANNELS.KIS_PLACE_ORDER, pendingConfirm)
            } catch (e: any) {
              await ipc.invoke(IPC_CHANNELS.TRADE_CANCEL, {
                tradeId: pendingConfirm.trade_id,
                reason: e?.message ?? '주문 실행 실패',
              })
              updateSignalStatus(pendingConfirm.trade_id, 'FAILED')
              setPendingConfirm(null)
            }
          }}
          onReject={() => {
            ipc.invoke(IPC_CHANNELS.TRADE_CANCEL, {
              tradeId: pendingConfirm.trade_id,
              reason: '사용자 거절',
            })
            updateSignalStatus(pendingConfirm.trade_id, 'REJECTED')
            setPendingConfirm(null)
          }}
          onTimeout={() => {
            ipc.invoke(IPC_CHANNELS.TRADE_CANCEL, {
              tradeId: pendingConfirm.trade_id,
              reason: '승인 시간 초과',
            })
            updateSignalStatus(pendingConfirm.trade_id, 'IGNORED')
            setPendingConfirm(null)
          }}
        />
      )}
    </HashRouter>
  )
}
