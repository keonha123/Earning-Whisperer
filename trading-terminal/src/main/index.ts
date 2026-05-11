import { app, BrowserWindow, session, Tray, Menu, nativeImage, screen } from 'electron'
import { config as loadDotenv } from 'dotenv'
import keytar from 'keytar'
import { join } from 'path'

// dev 환경변수 로딩 — Electron main 은 Vite 의 `.env.local` 자동 주입을 받지 않으므로
// 앱 모듈이 `process.env.*` 를 참조하기 전에 dotenv 로 명시 로딩한다.
// 우선순위: 프로젝트 루트의 .env.local > .env. (.env.local 은 git ignored)
// prod 빌드는 electron-builder 가 packaging 시 환경변수를 inline 하므로 영향 없음.
if (!app.isPackaged) {
  loadDotenv({ path: join(__dirname, '../../.env.local') })
  loadDotenv({ path: join(__dirname, '../../.env') })
}

import { mainState } from './store/mainState'
import { registerAuthHandlers } from './ipc/authHandlers'
import { registerVaultHandlers } from './ipc/vaultHandlers'
import { registerKisHandlers } from './ipc/kisHandlers'
import { registerSettingsHandlers } from './ipc/settingsHandlers'
import { registerWsHandlers } from './ipc/wsHandlers'
import { registerMarketHandlers } from './ipc/marketHandlers'
import { registerWatchlistHandlers, stop as stopWatchlist } from './ipc/watchlistHandlers'
import { registerPricesHandlers } from './ipc/pricesHandlers'
import { registerStockDetailHandlers } from './ipc/stockDetailHandlers'
import { registerEarningsHandlers, stop as stopEarnings } from './ipc/earningsHandlers'
import { registerStockListHandlers } from './ipc/stockListHandlers'
import { stop as stopPricePoller } from './services/PricePoller'
import { OAuthService } from './services/OAuthService'
import { kisLimiter } from './services/KisRateLimiter'
import { migrateLegacyKeysIfNeeded } from './services/KisService'

const KEYTAR_SERVICE = 'EarningWhisperer'
const PAPER_TRADING_KEY = 'kis-isPaperTrading'

/**
 * keytar에서 paper/real 플래그 복원. 값 없으면 디폴트 true(모의) 유지.
 * 복원 후 KisRateLimiter rate를 모드에 맞게 동기화 (모의 1.5, 실전 18 req/s).
 */
async function restorePaperTradingFlag(): Promise<void> {
  try {
    const saved = await keytar.getPassword(KEYTAR_SERVICE, PAPER_TRADING_KEY)
    if (saved === '0') mainState.setPaperTrading(false)
    else if (saved === '1') mainState.setPaperTrading(true)
  } catch (e) {
    console.warn('[main] paper-trading 플래그 복원 실패 (디폴트 true 유지):', e)
  }
  kisLimiter.setRate(mainState.isPaperTrading ? 1.5 : 18)
}

let mainWindow: BrowserWindow | null = null
let tray: Tray | null = null


function createWindow() {
  const { width: sw, height: sh } = screen.getPrimaryDisplay().workAreaSize
  const w = Math.min(1200, sw)
  const h = Math.min(800, sh)
  const x = Math.floor((sw - w) / 2)
  const y = Math.floor((sh - h) / 2)

  mainWindow = new BrowserWindow({
    width: w,
    height: h,
    x,
    y,
    minWidth: 1024,
    minHeight: 680,
    titleBarStyle: process.platform === 'darwin' ? 'hidden' : 'default',
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

  // CSP 설정 (프로덕션만)
  if (!process.env['ELECTRON_RENDERER_URL']) {
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
  }

  if (process.env['ELECTRON_RENDERER_URL']) {
    mainWindow.loadURL(process.env['ELECTRON_RENDERER_URL'])
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
  registerMarketHandlers()
  registerWatchlistHandlers()
  registerPricesHandlers()
  registerStockDetailHandlers()
  registerEarningsHandlers()
  registerStockListHandlers()
}

app.whenReady().then(async () => {
  // legacy 단일 키 → paper 키 이전을 restorePaperTradingFlag/issueToken 이전에 완료
  // (race 시 잘못된 모드 키에 토큰이 박힐 수 있음). 실패는 console.warn 후 진행.
  try {
    await migrateLegacyKeysIfNeeded()
  } catch (e) {
    console.warn('[main] legacy 키 마이그레이션 실패 (무시):', e)
  }
  await restorePaperTradingFlag()
  registerAllHandlers()
  createWindow()
  createTray()
})

app.on('window-all-closed', () => {
  // 트레이 상주 — 앱 종료 안 함
})

app.on('will-quit', () => {
  // OAuth 임시 서버가 살아있다면 강제 종료 (포트 누수 방지)
  OAuthService.shutdown()
  stopWatchlist()
  stopEarnings()
  stopPricePoller()
  mainState.clear()
})

app.on('activate', () => {
  if (mainWindow?.isDestroyed()) {
    createWindow()
  } else {
    mainWindow?.show()
  }
})
