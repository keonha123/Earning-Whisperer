import { useEffect } from 'react'
import { HashRouter, Routes, Route, Navigate, useNavigate } from 'react-router-dom'
import { ipc, IPC_CHANNELS } from './lib/ipc'
import { useConnectionStore } from './store/useConnectionStore'
import { useTradingStore } from './store/useTradingStore'
import { usePortfolioStore } from './store/usePortfolioStore'
import { useUserStore } from './store/useUserStore'
import { isIpcError } from '../lib/types/ipcError'

import AuthPage from './pages/AuthPage'
import DashboardPage from './pages/DashboardPage'
import TradingRoomPage from './pages/TradingRoomPage'
import MarketPage from './pages/MarketPage'
import HistoryPage from './pages/HistoryPage'
import SettingsPage from './pages/SettingsPage'
import AppLayout from './components/layout/AppLayout'
import TradeConfirmDialog from './components/trading/TradeConfirmDialog'
import { AppToaster, setAuthExpiredHandler, showIpcErrorToast } from './components/common/Toast'

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
  const { forceManual, receiveSignal, updateSignalStatus, setLastExecutedTrade, pendingConfirm, setPendingConfirm } = useTradingStore()
  const { setBalance } = usePortfolioStore()
  const { clear } = useUserStore()
  const navigate = useNavigate()

  // 인증 상태 변화 시 WebSocket 연결/해제
  useEffect(() => {
    if (isAuthenticated) {
      ipc.invoke(IPC_CHANNELS.WS_CONNECT)
    } else {
      ipc.invoke(IPC_CHANNELS.WS_DISCONNECT)
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
                  <Route path="/" element={<Navigate to="/dashboard" replace />} />
                  <Route path="/dashboard" element={<DashboardPage />} />
                  <Route path="/market" element={<MarketPage />} />
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
            } catch (e: unknown) {
              // IpcError 코드별 사용자 알림 (PR-2b).
              // AUTH_EXPIRED 의 경우 toast "다시 로그인" 클릭 시 인증 상태 초기화 + 라우팅.
              showIpcErrorToast(e, {
                onNavigate:
                  isIpcError(e) && e.code === 'AUTH_EXPIRED'
                    ? () => {
                        setAuthenticated(false)
                        clear()
                        navigate('/auth')
                      }
                    : undefined,
              })
              const reason =
                e instanceof Error ? e.message : '주문 실행 실패'
              // TRADE_CANCEL 자체 실패도 사용자에게 노출 — store 가 PENDING 으로 멈추는 silent fail 방지 (review F2).
              try {
                await ipc.invoke(IPC_CHANNELS.TRADE_CANCEL, {
                  tradeId: pendingConfirm.trade_id,
                  reason,
                })
              } catch (cancelErr: unknown) {
                showIpcErrorToast(cancelErr)
              }
              updateSignalStatus(pendingConfirm.trade_id, 'FAILED')
              setPendingConfirm(null)
            }
          }}
          onReject={() => {
            // fire-and-forget cancel 실패도 사용자에게 노출 (review F2).
            ipc
              .invoke(IPC_CHANNELS.TRADE_CANCEL, {
                tradeId: pendingConfirm.trade_id,
                reason: '사용자 거절',
              })
              .catch(showIpcErrorToast)
            updateSignalStatus(pendingConfirm.trade_id, 'REJECTED')
            setPendingConfirm(null)
          }}
          onTimeout={() => {
            ipc
              .invoke(IPC_CHANNELS.TRADE_CANCEL, {
                tradeId: pendingConfirm.trade_id,
                reason: '승인 시간 초과',
              })
              .catch(showIpcErrorToast)
            updateSignalStatus(pendingConfirm.trade_id, 'IGNORED')
            setPendingConfirm(null)
          }}
        />
      )}
    </>
  )
}
