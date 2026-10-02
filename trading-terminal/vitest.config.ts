import { defineConfig } from 'vitest/config'
import { resolve } from 'path'

/**
 * Main 프로세스(Node.js 환경) 단위 테스트 전용 설정.
 * Renderer/Preload 테스트는 별도 환경이 필요하므로 추후 분리한다.
 *
 * esbuild.jsx = 'automatic': tsconfig 가 jsx=preserve 라 vite 가 JSX 변환을 거부하는 문제를
 * 우회. 본 vitest 설정은 PR-2b 의 Toast.tsx 를 import 할 때만 영향 — 실제 main/preload
 * 빌드는 electron.vite.config 의 react() 플러그인이 별도로 처리한다.
 */
export default defineConfig({
  oxc: {
    jsx: { runtime: 'automatic' },
  },
  test: {
    environment: 'node',
    globals: false,
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/__tests__/**/*.test.ts'],
    clearMocks: true,
    restoreMocks: true,
  },
  resolve: {
    alias: {
      '@main': resolve(__dirname, 'src/main'),
      '@test': resolve(__dirname, 'src/test'),
    },
  },
})
