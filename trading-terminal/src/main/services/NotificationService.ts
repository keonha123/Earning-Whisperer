import { Notification } from 'electron'

export const NotificationService = {
  notifyWsDisconnected() {
    show('연결 끊김', '백엔드 서버 연결이 끊겼습니다. MANUAL 모드로 전환됩니다.')
  },

  notifyWsReconnected() {
    show('연결 복구됨', '백엔드 서버에 다시 연결되었습니다.')
  },

  notifyTradeExecuted(ticker: string, action: 'BUY' | 'SELL', qty: number, price: number | null) {
    const actionLabel = action === 'BUY' ? '매수' : '매도'
    const priceStr = price != null ? ` @ $${price.toFixed(2)}` : ''
    show(`${actionLabel} 체결 완료`, `${ticker} ${qty}주 체결${priceStr}`)
  },

  notifyTradeFailed(ticker: string, reason: string | null) {
    show(`주문 실패 — ${ticker}`, reason ?? '알 수 없는 오류')
  },
}

function show(title: string, body: string) {
  if (!Notification.isSupported()) return
  new Notification({ title, body }).show()
}
