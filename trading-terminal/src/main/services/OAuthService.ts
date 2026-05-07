/**
 * OAuthService — Loopback Localhost Server (RFC 8252) 기반 OAuth 흐름.
 *
 * 흐름:
 *  1) Renderer → IPC(AUTH_OAUTH_START) → main
 *  2) main: PKCE(verifier/challenge) + state(CSRF) 생성, localhost:9000 임시 HTTP 서버 시작
 *  3) main: shell.openExternal(authUrl) 로 사용자의 기본 브라우저에서 provider 로그인
 *  4) provider → http://localhost:9000/auth/callback?code=...&state=... 리다이렉트
 *  5) main: state 검증 → 백엔드 POST /api/v1/auth/oauth/callback → JWT 수신
 *  6) main: mainState.setBackendToken(...), 사용자/설정/KIS 토큰 로드 → IPC 응답 반환
 *  7) 임시 서버 종료 (성공/실패/취소/타임아웃 모두)
 *
 * 보안:
 *  - PKCE: code_verifier(43~128 base64url), code_challenge = SHA256(verifier) base64url
 *  - state: 32B 랜덤 hex, 콜백에서 일치/만료(5분) 검증, 일회용
 *  - redirect_uri 는 항상 LOOPBACK_REDIRECT_URI 로 강제 (renderer 가 임의 URI 못 넣음)
 *  - verifier/state/JWT 는 메모리 전용. 디스크 저장 X
 *  - 응답 HTML 은 정적 문자열만 (XSS 방지)
 */

import { shell, BrowserWindow } from 'electron'
import http from 'http'
import crypto from 'crypto'
import { URL } from 'url'
import { mainState, TradingMode } from '../store/mainState'
import { BackendClient } from './BackendClient'
import { KisService } from './KisService'
import { start as startWatchlist } from '../ipc/watchlistHandlers'
import { start as startEarnings } from '../ipc/earningsHandlers'
import { start as startPricePoller } from './PricePoller'

export type OAuthProvider = 'google' | 'kakao'

const LOOPBACK_PORT = Number(process.env.OAUTH_LOOPBACK_PORT ?? 9000)
const LOOPBACK_HOST = '127.0.0.1'
const LOOPBACK_PATH = '/auth/callback'
// 백엔드 application-local.yml 의 allowed-redirect-uris 와 정확히 일치해야 함.
const LOOPBACK_REDIRECT_URI = `http://localhost:${LOOPBACK_PORT}${LOOPBACK_PATH}`

const FLOW_TIMEOUT_MS = 5 * 60 * 1000 // 5분

// provider 메타데이터. client_id 는 환경변수에서 주입한다 (하드코딩 금지).
const PROVIDERS: Record<OAuthProvider, { authUrl: string; scope: string; envClientId: string }> = {
  google: {
    authUrl: 'https://accounts.google.com/o/oauth2/v2/auth',
    scope: 'openid email profile',
    envClientId: 'OAUTH_GOOGLE_CLIENT_ID',
  },
  kakao: {
    authUrl: 'https://kauth.kakao.com/oauth/authorize',
    // 카카오 비즈앱 미전환 시 email 권한 거부될 수 있음 → 백엔드 sentinel 처리 (PR #35).
    scope: 'profile_nickname account_email',
    envClientId: 'OAUTH_KAKAO_CLIENT_ID',
  },
}

interface OAuthSuccess {
  user: { id: number; email: string; nickname: string; role: string }
  settings: unknown | null
}

/* -------------------------------------------------------------------------- */
/* 헬퍼                                                                        */
/* -------------------------------------------------------------------------- */

function base64UrlEncode(buf: Buffer): string {
  return buf.toString('base64').replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

function generateCodeVerifier(): string {
  // RFC 7636: 43~128 자 길이의 base64url. 32B → 약 43자.
  return base64UrlEncode(crypto.randomBytes(32))
}

function generateCodeChallenge(verifier: string): string {
  return base64UrlEncode(crypto.createHash('sha256').update(verifier).digest())
}

function generateState(): string {
  return crypto.randomBytes(32).toString('hex')
}

function getClientId(provider: OAuthProvider): string {
  const envName = PROVIDERS[provider].envClientId
  const value = process.env[envName]
  if (!value) {
    throw new Error(
      `[OAuth] 환경변수 ${envName} 미설정. .env.local 또는 electron-vite 환경변수로 주입하세요.`,
    )
  }
  return value
}

function buildAuthUrl(provider: OAuthProvider, state: string, codeChallenge: string): string {
  const { authUrl, scope } = PROVIDERS[provider]
  const params = new URLSearchParams({
    client_id: getClientId(provider),
    redirect_uri: LOOPBACK_REDIRECT_URI,
    response_type: 'code',
    scope,
    state,
    code_challenge: codeChallenge,
    code_challenge_method: 'S256',
  })
  if (provider === 'google') {
    // refresh_token 발급 + 매 로그인 시 동의 화면 (계정 전환 보장)
    params.set('access_type', 'offline')
    params.set('prompt', 'consent select_account')
  }
  return `${authUrl}?${params.toString()}`
}

function renderResultHtml(message: string): string {
  // 정적 문자열만 — 사용자 입력값을 렌더링하지 않음 (XSS 방지)
  return `<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><title>EarningWhisperer</title>
<style>
  body{margin:0;background:#0a0c0f;color:#e5e7eb;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
       display:flex;align-items:center;justify-content:center;min-height:100vh}
  .card{padding:32px 40px;border:1px solid #1f2937;border-radius:12px;background:#111827;text-align:center;max-width:420px}
  h1{margin:0 0 8px;font-size:18px;font-weight:600}
  p{margin:0;color:#9ca3af;font-size:14px}
</style></head>
<body><div class="card"><h1>${message}</h1><p>이 창은 닫아도 됩니다.</p></div></body></html>`
}

/* -------------------------------------------------------------------------- */
/* OAuthService (싱글턴)                                                       */
/* -------------------------------------------------------------------------- */

interface PendingFlow {
  provider: OAuthProvider
  state: string
  codeVerifier: string
  startedAt: number
  server: http.Server
  timeoutHandle: NodeJS.Timeout
  resolve: (value: OAuthSuccess) => void
  reject: (err: Error) => void
  /**
   * 첫 콜백이 백엔드 교환 단계에 진입하면 true.
   * 이후 들어오는 중복 콜백 (provider 가 같은 URL 재요청, 사용자 새로고침 등) 은
   * 410 으로 즉시 거부하여 일회용 OAuth code 의 race 재교환을 방지.
   */
  processing: boolean
}

class OAuthServiceImpl {
  private pending: PendingFlow | null = null

  /**
   * Renderer 에서 호출. 흐름 종료 시점까지 단일 Promise 로 결과 반환.
   * - 성공: { user, settings }
   * - 실패: throw Error
   */
  start(provider: OAuthProvider): Promise<OAuthSuccess> {
    if (this.pending) {
      return Promise.reject(new Error('이미 진행 중인 OAuth 요청이 있습니다.'))
    }

    return new Promise<OAuthSuccess>((resolve, reject) => {
      const state = generateState()
      const codeVerifier = generateCodeVerifier()
      const codeChallenge = generateCodeChallenge(codeVerifier)

      const server = http.createServer((req, res) => {
        this.handleRequest(req, res).catch((err) => {
          console.error('[OAuth] 콜백 처리 중 예외:', err)
        })
      })

      server.on('error', (err: NodeJS.ErrnoException) => {
        const detail =
          err.code === 'EADDRINUSE'
            ? `로컬 포트 ${LOOPBACK_PORT} 이 사용 중입니다. 다른 프로세스를 종료한 뒤 다시 시도하세요.`
            : err.message
        this.cleanup(new Error(detail))
      })

      const timeoutHandle = setTimeout(() => {
        this.cleanup(new Error('OAuth 인증 시간이 초과되었습니다 (5분).'))
      }, FLOW_TIMEOUT_MS)

      this.pending = {
        provider,
        state,
        codeVerifier,
        startedAt: Date.now(),
        server,
        timeoutHandle,
        resolve,
        reject,
        processing: false,
      }

      try {
        server.listen(LOOPBACK_PORT, LOOPBACK_HOST, () => {
          const authUrl = buildAuthUrl(provider, state, codeChallenge)
          shell.openExternal(authUrl).catch((err) => {
            this.cleanup(new Error(`외부 브라우저를 열 수 없습니다: ${err?.message ?? err}`))
          })
        })
      } catch (err) {
        // listen 동기 throw (드물지만 환경변수 누락 등) 대응
        this.cleanup(err instanceof Error ? err : new Error(String(err)))
      }
    })
  }

  /**
   * 앱 종료 시 임시 서버 강제 정리 (will-quit 훅에서 호출).
   */
  shutdown(): void {
    if (this.pending) {
      this.cleanup(new Error('애플리케이션 종료로 OAuth 흐름이 취소되었습니다.'))
    }
  }

  /* ------------------------------------------------------------------ */

  private async handleRequest(req: http.IncomingMessage, res: http.ServerResponse): Promise<void> {
    // OAuth provider 콜백은 항상 GET. 그 외 메서드는 attack surface 축소를 위해 즉시 거부.
    if (req.method !== 'GET') {
      res.writeHead(405, { Allow: 'GET' })
      res.end()
      return
    }
    if (!this.pending) {
      res.writeHead(410, { 'Content-Type': 'text/plain; charset=utf-8' })
      res.end('No pending OAuth flow')
      return
    }
    // 동일 흐름이 백엔드 교환 단계에 들어간 뒤 두 번째 콜백 (브라우저 새로고침, provider 재요청) 차단
    if (this.pending.processing) {
      res.writeHead(410, { 'Content-Type': 'text/plain; charset=utf-8' })
      res.end('Already processing')
      return
    }
    if (!req.url) {
      res.writeHead(400)
      res.end()
      return
    }

    const reqUrl = new URL(req.url, `http://${LOOPBACK_HOST}:${LOOPBACK_PORT}`)
    if (reqUrl.pathname !== LOOPBACK_PATH) {
      res.writeHead(404, { 'Content-Type': 'text/plain; charset=utf-8' })
      res.end('Not Found')
      return
    }

    const code = reqUrl.searchParams.get('code')
    const state = reqUrl.searchParams.get('state')
    const errorCode = reqUrl.searchParams.get('error')

    // provider 가 에러 반환 (사용자 거부 등)
    if (errorCode) {
      res.writeHead(400, { 'Content-Type': 'text/html; charset=utf-8' })
      res.end(renderResultHtml('로그인이 취소되었습니다'))
      this.cleanup(new Error(`OAuth 거부: ${errorCode}`))
      return
    }

    if (!code || !state) {
      res.writeHead(400, { 'Content-Type': 'text/html; charset=utf-8' })
      res.end(renderResultHtml('잘못된 콜백 요청입니다'))
      this.cleanup(new Error('OAuth 콜백에 code 또는 state 가 없습니다.'))
      return
    }

    if (state !== this.pending.state) {
      // CSRF 가능성 — 즉시 차단
      res.writeHead(400, { 'Content-Type': 'text/html; charset=utf-8' })
      res.end(renderResultHtml('보안 검증에 실패했습니다'))
      this.cleanup(new Error('OAuth state 불일치 (CSRF 의심).'))
      return
    }

    const provider = this.pending.provider
    const verifier = this.pending.codeVerifier
    // 일회용 OAuth code 의 race 재교환 차단: 이 지점 이후 들어오는 중복 콜백은 410 으로 거부됨.
    this.pending.processing = true

    try {
      // 백엔드 교환 (PKCE verifier 도 함께 전달 — 백엔드가 활용 가능 시 사용, 미사용이면 무시).
      const { token } = await BackendClient.oauthCallback({
        provider,
        code,
        redirectUri: LOOPBACK_REDIRECT_URI,
        codeVerifier: verifier,
      })
      mainState.setBackendToken(token)

      // 사용자 정보 (필수)
      const user = await BackendClient.getMe()

      // 설정 (선택 — 실패해도 진행)
      let settings: unknown = null
      try {
        const s = await BackendClient.getSettings()
        settings = s
        if (s.tradingMode) {
          mainState.setTradingMode(s.tradingMode as TradingMode)
        }
      } catch (e) {
        console.warn('[OAuth] 설정 로드 실패, 기본값 사용:', e instanceof Error ? e.message : e)
      }

      // KIS 토큰 복원 (선택)
      try {
        await KisService.loadSavedToken()
      } catch (e) {
        console.warn('[OAuth] KIS 토큰 복원 실패:', e instanceof Error ? e.message : e)
      }

      // 관심종목 5분 폴링 시작 (이미 동작 중이면 no-op).
      startWatchlist()
      // 어닝콜 타임라인 5분 폴링 시작.
      startEarnings()
      // 시세 폴링 시작 — ticker 들은 watchlist/holdings 통보로 채워진다.
      startPricePoller()

      res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' })
      res.end(renderResultHtml('로그인이 완료되었습니다'))

      // 메인 윈도우를 사용자 시야로 끌어오기 (UX)
      const win = BrowserWindow.getAllWindows().find((w) => !w.isDestroyed())
      win?.show()
      win?.focus()

      this.resolveFlow({ user, settings })
    } catch (err) {
      const message = err instanceof Error ? err.message : 'unknown'
      res.writeHead(500, { 'Content-Type': 'text/html; charset=utf-8' })
      res.end(renderResultHtml('로그인 처리 중 오류가 발생했습니다'))
      // user enumeration 방지: renderer 에 generic 메시지만 전달
      this.cleanup(new Error('OAuth 로그인에 실패했습니다.'))
      console.warn('[OAuth] 콜백 교환 실패:', message)
    }
  }

  private resolveFlow(value: OAuthSuccess): void {
    if (!this.pending) return
    const { resolve, server, timeoutHandle } = this.pending
    clearTimeout(timeoutHandle)
    this.pending = null
    server.close()
    resolve(value)
  }

  private cleanup(err: Error): void {
    if (!this.pending) return
    const { reject, server, timeoutHandle } = this.pending
    clearTimeout(timeoutHandle)
    this.pending = null
    server.close()
    reject(err)
  }
}

export const OAuthService = new OAuthServiceImpl()
