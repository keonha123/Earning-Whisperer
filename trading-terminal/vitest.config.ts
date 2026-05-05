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
    include: [
      'src/main/**/__tests__/**/*.test.ts',
      // PR-B: 순수 zustand store 단위 테스트는 node 환경으로 충분.
      'src/renderer/store/__tests__/**/*.test.ts',
      // PR-B: hook 의 순수 helper(toCamel/isValidPayload) 도 node 환경에서 실행 가능.
      'src/renderer/hooks/__tests__/**/*.test.ts',
      // Phase 5: CompanyDrawer 표시용 포맷팅 helper 단위 테스트
      // (컴포넌트 렌더는 jsdom 미설정으로 skip, 순수 함수만 검증).
      'src/renderer/lib/__tests__/**/*.test.ts',
      // PR-2b: Toast helper (showIpcErrorToast / makeToastId / CODE_CONFIG) 단위 테스트.
      // react-hot-toast 를 mock 해서 jsdom 없이도 호출 분기를 검증한다.
      'src/renderer/components/**/__tests__/**/*.test.ts',
      // A3 hotfix: pages 의 순수 helper 단위 테스트 (resolveSaveOrder /
      // composePartialFailureMessage / decideCardDelete 등). React 렌더는 검증하지 않고
      // 순수 함수 분기만 본다 — 컴포넌트 import 시 react/IPC 의존성 회피 위해 별도 helper 모듈 권장.
      'src/renderer/pages/**/__tests__/**/*.test.ts',
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
