import { resolve } from 'path'
import { defineConfig, externalizeDepsPlugin } from 'electron-vite'
import react from '@vitejs/plugin-react'
import { config as loadDotenv } from 'dotenv'

/**
 * 패키징본에 넣어야 하는 환경변수.
 *
 * 패키징된 앱에는 `.env` 파일이 없다. 그래서 빌드 시점의 값을 번들에 문자열로 넣고,
 * 런타임에 `src/main/loadEnv.ts` 가 `process.env` 로 채운다.
 *
 * `OAUTH_LOOPBACK_PORT` 는 기본값 9000 이 있어 넣지 않아도 동작한다. 백엔드의
 * `allowed-redirect-uris` 와 어긋날 때만 지정한다.
 *
 * **renderer 에는 추가하지 않는다.** 이 값은 main 설정의 `define` 에만 넣는다.
 * renderer 는 `contextIsolation`·`sandbox` 로 격리된 XSS 표면이라, 거기에 값을
 * 노출하면 그 격리의 의미가 줄어든다.
 */
const PACKAGED_ENV_KEYS = [
  'BACKEND_URL',
  'OAUTH_GOOGLE_CLIENT_ID',
  'OAUTH_KAKAO_CLIENT_ID',
  'OAUTH_LOOPBACK_PORT',
]

/**
 * 패키징본에 넣을 수 없는 이름.
 *
 * 비밀값은 백엔드만 보유한다. 위 목록에 그런 이름이 섞이면 빌드를 세운다 —
 * 번들에 박힌 값은 설치본을 뜯으면 그대로 읽히므로 되돌릴 방법이 없다.
 */
const FORBIDDEN_KEY_PATTERN = /SECRET|PASSWORD|PASSWD|CREDENTIAL|PRIVATE|TOKEN|_KEY$|APIKEY/i

/** 평문 HTTP 를 허용할 호스트. 로컬 개발용이다. */
const LOCAL_HOST_PATTERN = /^https?:\/\/(localhost|127\.0\.0\.1)([:/]|$)/

/** 평문 백엔드로 빌드하려면 이 환경변수를 명시해야 한다. */
const ALLOW_INSECURE_FLAG = 'EW_ALLOW_INSECURE_BACKEND'

/**
 * 빌드 시점 환경변수를 모은다.
 *
 * 우선순위는 **셸 환경 > `.env.production.local` > `.env.production`** 이다.
 *
 * `.env.*` 는 git ignored 라 값이 저장소에 남지 않는다. OAuth client ID 를 저장소에
 * 두지 않기로 정해져 있어서, 빌드하는 사람이 빌드 시점에 넣는 방식을 쓴다.
 *
 * `dotenv` 에 `processEnv` 를 따로 주는 이유는 `config()` 가 **파일의 모든 키를**
 * `process.env` 에 쓰기 때문이다. 아래 화이트리스트는 번들에 들어가는 값만 거르므로,
 * 그냥 두면 파일에 있는 다른 값까지 빌드 프로세스와 그 자식들(electron-builder,
 * 서명 도구, npm 훅)이 상속한다.
 *
 * 경로를 `__dirname` 기준으로 고정하는 이유는 `resolve()` 를 인자 하나로 쓰면 기준이
 * 현재 작업 디렉터리가 되기 때문이다. 저장소 루트에서 빌드하면 루트의 `.env.production`
 * 을 읽게 되는데, 그 자리는 백엔드 계열 비밀이 놓이는 위치다.
 */
function collectBuildEnv(): Record<string, string> {
  for (const key of PACKAGED_ENV_KEYS) {
    if (FORBIDDEN_KEY_PATTERN.test(key)) {
      throw new Error(
        `[build] ${key} 는 패키징본에 넣을 수 없습니다. 비밀값은 백엔드만 보유합니다.`,
      )
    }
  }

  const fileEnv: Record<string, string> = {}
  loadDotenv({ path: resolve(__dirname, '.env.production.local'), processEnv: fileEnv })
  loadDotenv({ path: resolve(__dirname, '.env.production'), processEnv: fileEnv })

  const collected: Record<string, string> = {}
  for (const key of PACKAGED_ENV_KEYS) {
    const value = process.env[key] ?? fileEnv[key]
    if (value) collected[key] = value
  }

  assertBackendUrlIsSafe(collected.BACKEND_URL)
  return collected
}

/**
 * 평문 백엔드 주소로 조용히 빌드되는 것을 막는다.
 *
 * 이 변경 전에는 패키징본의 주소가 `localhost` 로 굳어서 원격 평문 통신이 일어날 수
 * 없었다. 주입이 되면서 처음으로 가능해진다. 백엔드 요청에는 모두
 * `Authorization: Bearer` 가 실리고 STOMP 도 `ws://` 로 붙으므로, 평문이면 같은 망에서
 * 세션을 가져갈 수 있다.
 *
 * HTTPS 도입은 별개 작업이라(#120) 여기서 강제하지 않는다. 대신 시연용으로 평문을 쓸
 * 때는 의도를 명시하게 한다 — 실수로 평문 인스톨러가 나가는 경로만 막는 것이 목적이다.
 */
function assertBackendUrlIsSafe(backendUrl: string | undefined): void {
  if (!backendUrl) return
  if (/^https:/i.test(backendUrl) || LOCAL_HOST_PATTERN.test(backendUrl)) return

  if (process.env[ALLOW_INSECURE_FLAG] !== '1') {
    throw new Error(
      `[build] BACKEND_URL 이 평문입니다: ${backendUrl}\n` +
        `HTTPS 도입(#120) 전 시연용 빌드라면 ${ALLOW_INSECURE_FLAG}=1 을 함께 지정하세요.`,
    )
  }
  console.warn(
    `[build] 평문 BACKEND_URL 로 빌드합니다 — 시연 한정이며 팀 밖으로 배포하지 않습니다: ${backendUrl}`,
  )
}

export default defineConfig({
  main: {
    plugins: [externalizeDepsPlugin()],
    define: {
      // dev 빌드에서는 빈 객체가 들어간다. loadEnv.ts 가 dotenv 로 읽으므로 문제없다.
      __BUILD_ENV__: JSON.stringify(collectBuildEnv()),
    },
    resolve: {
      alias: {
        '@main': resolve('src/main'),
      },
    },
  },
  preload: {
    plugins: [externalizeDepsPlugin()],
  },
  renderer: {
    resolve: {
      alias: {
        '@renderer': resolve('src/renderer'),
        '@': resolve('src/renderer'),
      },
    },
    plugins: [react()],
  },
})
