import { app, BrowserWindow, session, Tray, Menu, nativeImage } from 'electron'
import { join } from 'path'
import { mainState } from './store/mainState'
import { registerAuthHandlers } from './ipc/authHandlers'
import { registerVaultHandlers } from './ipc/vaultHandlers'
import { registerKisHandlers } from './ipc/kisHandlers'
import { registerSettingsHandlers } from './ipc/settingsHandlers'
import { registerWsHandlers } from './ipc/wsHandlers'

let mainWindow: BrowserWindow | null = null
let tray: Tray | null = null

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1200,
    height: 800,
    minWidth: 1024,
    minHeight: 680,
    titleBarStyle: 'hidden',
    backgroundColor: '#0a0c0f',
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      sandbox: true,
      preload: join(__dirname, '../preload/index.js'),
      webSecurity: true,
      allowRunningInsecureContent: false,
    },
  })

  // CSP 설정
  session.defaultSession.webRequest.onHeadersReceived((details, callback) => {
    callback({
      responseHeaders: {
        ...details.responseHeaders,
        'Content-Security-Policy': [
          "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:;",
        ],
      },
    })
  })

  if (process.env.NODE_ENV === 'development') {
    mainWindow.loadURL('http://localhost:5173')
    mainWindow.webContents.openDevTools()
  } else {
    mainWindow.loadFile(join(__dirname, '../renderer/index.html'))
  }

  // 창 닫기 → 트레이로 최소화
  mainWindow.on('close', (e) => {
    e.preventDefault()
    mainWindow?.hide()
  })
}

function createTray() {
  const icon = nativeImage.createFromPath(join(__dirname, '../../resources/icon.png'))
  tray = new Tray(icon.isEmpty() ? nativeImage.createEmpty() : icon)
  tray.setToolTip('EarningWhisperer Terminal')
  tray.setContextMenu(
    Menu.buildFromTemplate([
      { label: '열기', click: () => mainWindow?.show() },
      { type: 'separator' },
      { label: '종료', click: () => { mainWindow?.destroy(); app.quit() } },
    ]),
  )
  tray.on('double-click', () => mainWindow?.show())
}

function registerAllHandlers() {
  registerAuthHandlers()
  registerVaultHandlers()
  registerKisHandlers()
  registerSettingsHandlers()
  registerWsHandlers()
}

app.whenReady().then(() => {
  registerAllHandlers()
  createWindow()
  createTray()
})

app.on('window-all-closed', () => {
  // 트레이 상주 — 앱 종료 안 함
})

app.on('will-quit', () => {
  mainState.clear()
})

app.on('activate', () => {
  if (mainWindow?.isDestroyed()) {
    createWindow()
  } else {
    mainWindow?.show()
  }
})
