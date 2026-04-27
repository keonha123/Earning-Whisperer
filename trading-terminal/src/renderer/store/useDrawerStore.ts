import { create } from 'zustand'

interface DrawerState {
  /** 현재 열려있는 ticker. null = 닫힘. */
  openTicker: string | null

  /**
   * Drawer 를 ticker 로 연다.
   *
   * 보안:
   *  - ticker 는 [A-Z0-9.-]{1,10} 화이트리스트만 허용한다 (CompanyDrawer 가
   *    fixture lookup 키로도 사용되므로, 임의 입력으로 fixture 외 키를
   *    노출하거나 콘솔 오염을 일으키지 않도록 정규화).
   *  - 어긋난 입력은 silently no-op (throw 하지 않음 — UI 클릭 핸들러에서
   *    예측 불가능한 try/catch 를 강요하지 않기 위함).
   */
  open: (ticker: string) => void
  close: () => void
}

const TICKER_RE = /^[A-Z0-9.\-]{1,10}$/

export const useDrawerStore = create<DrawerState>((set) => ({
  openTicker: null,
  open: (ticker) => {
    // 시그니처는 string 이지만 외부 입력 (URL 파라미터, IPC 등) 에서 비-string 이
    // 흘러들어올 수 있다. .toUpperCase() 호출 전 타입 가드.
    if (typeof ticker !== 'string') return
    const normalized = ticker.toUpperCase().trim()
    if (!TICKER_RE.test(normalized)) {
      // prod 콘솔에 raw ticker 가 노출되지 않도록 DEV 빌드만 경고하고,
      // 길이만 노출 (raw 값은 노출하지 않음).
      if (import.meta.env.DEV) {
        // eslint-disable-next-line no-console
        console.warn('[useDrawerStore] invalid ticker, ignored:', { length: ticker.length })
      }
      return
    }
    set({ openTicker: normalized })
  },
  close: () => set({ openTicker: null }),
}))
