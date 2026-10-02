/**
 * 환경변수 로딩.
 *
 * 반드시 `index.ts` 의 **첫 번째 import** 여야 한다.
 * `BackendClient`(BACKEND_URL)·`StompService`(BACKEND_URL)·`OAuthService`(OAUTH_LOOPBACK_PORT) 는
 * 모듈 최상위에서 `process.env.*` 를 읽는데, 번들러가 import 를 호이스팅하므로
 * `index.ts` 본문에서 로딩을 호출하면 이미 늦다(기본값 localhost:8082 로 굳는다).
 * 별도 모듈로 분리해 import 순서로 실행 시점을 보장한다.
 *
 * ## dev
 *
 * 프로젝트 루트의 파일을 `dotenv` 로 읽는다. 우선순위는 `.env.local` > `.env` 이고
 * `.env.local` 은 git ignored 다.
 *
 * ## 패키징 빌드
 *
 * `.env` 파일이 앱 안에 없다. 그래서 빌드 시점에 `electron.vite.config.ts` 의 `define` 으로
 * 값을 번들에 문자열로 넣고, 여기서 `process.env` 에 채운다.
 *
 * 읽는 쪽을 고치지 않고 `process.env` 에 채우는 이유는 `OAuthService` 가 client ID 를
 * `process.env[변수명]` 으로 동적 접근하기 때문이다. `define` 은 `process.env.NAME` 같은
 * 정적 표기만 치환하므로 그 지점은 치환되지 않는다. 값을 런타임 환경에 넣어 두면 정적·동적
 * 접근이 모두 그대로 동작한다.
 *
 * 이미 설정된 값은 덮지 않는다 — 실행 환경에서 넘긴 값이 빌드에 박힌 값보다 우선한다.
 * `BACKEND_URL` 은 앱의 신뢰 기점이라 이 우선순위가 변조 경로로 보일 수 있다. 그래도
 * 그대로 둔 이유는, 프로세스 환경을 심을 수 있는 쪽이면 서명 없는 `app.asar` 교체로
 * 이미 같은 결과를 낼 수 있어 새로 생기는 권한이 없기 때문이다. 디버깅 편의를 택했다.
 * 코드 서명을 도입하면 이 판단을 다시 봐야 한다.
 */
import { app } from 'electron'
import { config as loadDotenv } from 'dotenv'
import { join } from 'path'

/**
 * 빌드 시점에 주입되는 값. `electron.vite.config.ts` 의 `define` 이 채운다.
 * dev 빌드에서는 빈 객체다.
 */
declare const __BUILD_ENV__: Record<string, string>

/**
 * 패키징본에 반드시 있어야 하는 변수.
 *
 * `OAUTH_LOOPBACK_PORT` 는 기본값 9000 이 있어 제외한다. `BACKEND_URL` 은 기본값
 * `localhost:8082` 가 있지만, 그 기본값으로 패키징본이 돌면 서버에 붙지 못한 채
 * 화면만 뜬다 — 그래서 필수로 본다.
 */
const REQUIRED_IN_PACKAGED = ['BACKEND_URL', 'OAUTH_GOOGLE_CLIENT_ID', 'OAUTH_KAKAO_CLIENT_ID']

/**
 * 패키징본에서 주입되지 않은 필수 변수 목록.
 *
 * 값이 없어도 앱은 뜬다(`?? 'http://localhost:8082'` 폴백). 데이터만 들어오지 않아서
 * 원인을 찾기 어렵다. 그래서 목록을 남겨 두고 `index.ts` 가 기동 시 화면으로 알린다.
 */
export const missingPackagedEnv: string[] = []

if (app.isPackaged) {
  const injected = typeof __BUILD_ENV__ === 'undefined' ? {} : __BUILD_ENV__
  for (const [key, value] of Object.entries(injected)) {
    if (value && process.env[key] === undefined) {
      process.env[key] = value
    }
  }
  missingPackagedEnv.push(...REQUIRED_IN_PACKAGED.filter((key) => !process.env[key]))
} else {
  loadDotenv({ path: join(__dirname, '../../.env.local') })
  loadDotenv({ path: join(__dirname, '../../.env') })
}
