/**
 * dev 환경변수 로딩.
 *
 * 반드시 `index.ts` 의 **첫 번째 import** 여야 한다.
 * `BackendClient`(BACKEND_URL)·`StompService`(BACKEND_URL)·`OAuthService`(OAUTH_LOOPBACK_PORT) 는
 * 모듈 최상위에서 `process.env.*` 를 읽는데, 번들러가 import 를 호이스팅하므로
 * `index.ts` 본문에서 dotenv 를 호출하면 이미 늦다(기본값 localhost:8082 로 굳는다).
 * 별도 모듈로 분리해 import 순서로 실행 시점을 보장한다.
 *
 * 우선순위: 프로젝트 루트의 .env.local > .env  (.env.local 은 git ignored)
 * 패키징 빌드는 .env 파일을 읽지 않는다 — 빌드 타임 주입은 별도 과제.
 */
import { app } from 'electron'
import { config as loadDotenv } from 'dotenv'
import { join } from 'path'

if (!app.isPackaged) {
  loadDotenv({ path: join(__dirname, '../../.env.local') })
  loadDotenv({ path: join(__dirname, '../../.env') })
}
