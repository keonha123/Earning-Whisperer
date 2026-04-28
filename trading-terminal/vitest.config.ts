import { defineConfig } from 'vitest/config'
import { resolve } from 'path'

/**
 * Main 프로세스(Node.js 환경) 단위 테스트 전용 설정.
 * Renderer/Preload 테스트는 별도 환경이 필요하므로 추후 분리한다.
 */
export default defineConfig({
  test: {
    environment: 'node',
    globals: false,
    setupFiles: ['./src/test/setup.ts'],
    include: [
      'src/main/**/__tests__/**/*.test.ts',
      // PR-B: 순수 zustand store 단위 테스트는 node 환경으로 충분.
      'src/renderer/store/__tests__/**/*.test.ts',
      // PR-B: hook 의 순수 helper(toCamel/isValidPayload) 도 node 환경에서 실행 가능.
      'src/renderer/hooks/__tests__/**/*.test.ts',
    ],
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
