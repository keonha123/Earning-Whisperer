import { Notification } from 'electron'

export const NotificationService = {
  notifyWsReconnected() {
    show('연결 복구됨', '백엔드 서버에 다시 연결되었습니다.')
  },
}

function show(title: string, body: string) {
  if (!Notification.isSupported()) return
  new Notification({ title, body }).show()
}
