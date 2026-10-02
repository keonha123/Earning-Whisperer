// 환경변수 로딩은 반드시 첫 import 여야 한다 (모듈 최상위 process.env 참조보다 먼저). 이유는 loadEnv.ts 참조.
import { missingPackagedEnv } from './loadEnv'
import { app, BrowserWindow, session, Tray, Menu, nativeImage, screen, dialog } from 'electron'
import keytar from 'keytar'
import { join } from 'path'

import { mainState } from './store/mainState'
import { registerAuthHandlers, teardownSession } from './ipc/authHandlers'
import { setRefreshFailedHandler } from './services/BackendClient'
import { registerVaultHandlers } from './ipc/vaultHandlers'
import { registerKisHandlers, reconcilePendingTrades } from './ipc/kisHandlers'
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
import { StompService } from './services/StompService'
import { KisWebSocketService } from './services/KisWebSocketService'

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
  kisLimiter.setRate(mainState.isPaperTrading ? 1.0 : 18)
}

let mainWindow: BrowserWindow | null = null
let tray: Tray | null = null
let isQuitting = false


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

  // 창 닫기 → 트레이로 최소화 (단, 앱 종료 중이면 그대로 닫히도록 통과시킨다 — macOS Cmd+Q 등)
  mainWindow.on('close', (e) => {
    if (isQuitting) return
    e.preventDefault()
    mainWindow?.hide()
  })
}

/** 트레이 아이콘 한 변 크기(px). 원본은 1024 라 줄여서 넘긴다. */
const TRAY_ICON_SIZE = 18

function createTray() {
  const icon = nativeImage.createFromPath(join(__dirname, '../../resources/icon.png'))
  // 1024px 원본을 그대로 넘기면 메뉴 바 높이에 맞춰 축소되면서 흐려진다.
  // 트레이 크기로 미리 줄여서 넘긴다.
  const trayIcon = icon.isEmpty()
    ? nativeImage.createEmpty()
    : icon.resize({ width: TRAY_ICON_SIZE, height: TRAY_ICON_SIZE })
  tray = new Tray(trayIcon)
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
  // 액세스 토큰 갱신이 최종 실패하면 (RT 만료, rotation 재사용 감지) 로그아웃과 같은
  // 정리를 태운다. 그러지 않으면 죽은 세션으로 폴러들이 계속 돌며 401 만 쌓는다.
  setRefreshFailedHandler(() => teardownSession())
  // KIS 실시간 체결통보가 오면 그 즉시 미체결 주문의 상태를 맞춘다. 통보 자체에는
  // 백엔드 tradeId 가 없으므로, ODNO 로 PENDING 을 찾아 확정하는 기존 경로를 재사용한다.
  KisWebSocketService.setFillNoticeHandler((fill) => {
    void reconcilePendingTrades().catch((e) =>
      console.warn(`[main] 체결통보 반영 실패 — ODNO=${fill.orderId}:`, e),
    )
  })
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
  warnIfPackagedEnvMissing()
  registerAllHandlers()
  createWindow()
  createTray()
})

/**
 * 패키징본에 환경변수가 주입되지 않았으면 알린다.
 *
 * 값이 없어도 앱은 뜬다 — `BACKEND_URL` 은 `localhost:8082` 로 떨어지고 로그인은
 * client ID 가 없다는 예외로 실패한다. 화면에는 "서버가 응답하지 않는다" 로만 보여서
 * 빌드가 잘못됐다는 사실이 드러나지 않는다. 그래서 기동 시 한 번 명시한다.
 *
 * 잘못된 인스톨러를 배포한 쪽에 원인을 알리는 목적이라 로그가 아니라 대화상자로 띄운다.
 * 설치본에는 콘솔이 없다.
 */
function warnIfPackagedEnvMissing() {
  if (missingPackagedEnv.length === 0) return
  const names = missingPackagedEnv.join(', ')
  console.error(`[main] 패키징 빌드에 환경변수가 주입되지 않았습니다: ${names}`)
  dialog.showErrorBox(
    '빌드 설정 오류',
    `이 설치본에는 다음 값이 들어 있지 않습니다.\n\n${names}\n\n` +
      '서버에 연결되지 않거나 로그인이 되지 않습니다. ' +
      '빌드한 사람에게 알려 주세요 — 빌드 전에 해당 환경변수를 설정해야 합니다.',
  )
}

app.on('window-all-closed', () => {
  // 트레이 상주 — 앱 종료 안 함
})

app.on('before-quit', () => {
  isQuitting = true
})

app.on('will-quit', () => {
  // OAuth 임시 서버가 살아있다면 강제 종료 (포트 누수 방지)
  OAuthService.shutdown()
  StompService.disconnect()
  KisWebSocketService.disconnect()
  kisLimiter.dispose()
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
