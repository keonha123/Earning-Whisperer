import { useEffect, useState } from 'react'
import { ipc, IPC_CHANNELS } from '../lib/ipc'
import type { StockDetailResponsePayload } from '../../lib/types/stockDetail'

/**
 * useCompanyDetail — drawer 가 열린 ticker 의 상세 정보를 IPC 로 fetch.
 *
 * 동작:
 *  - ticker null → 모든 상태 초기화 + IPC 호출 안 함.
 *  - ticker 변경 → 새 fetch (이전 요청은 cancelled flag 로 무시).
 *  - main 캐시(30s/5s)에 hit 하면 즉시 반환.
 *
 * 캐시 정책:
 *  - renderer 측 별도 캐시 없음. main 의 캐시에 위임 (drawer 닫고 재오픈해도
 *    main 캐시가 30s/5s TTL 내면 백엔드 호출 없이 즉시 반환).
 *  - 가격은 별도 PRICES_UPDATE 가 push 하므로 stale 우려 낮음.
 */

export interface CompanyDetailState {
  data: StockDetailResponsePayload | null
  loading: boolean
  error: Error | null
}

const INITIAL_STATE: CompanyDetailState = {
  data: null,
  loading: false,
  error: null,
}

/**
 * IPC 호출 + 표준 에러 정규화. 단위 테스트가 hook 본체 (useEffect/useState)를 거치지 않고도
 * 핵심 로직 (예외 → Error 변환, 응답 통과) 을 검증할 수 있도록 분리.
 */
export async function fetchStockDetail(
  ticker: string,
): Promise<StockDetailResponsePayload> {
  try {
    const data = await ipc.invoke<StockDetailResponsePayload>(
      IPC_CHANNELS.STOCK_GET_DETAIL,
      { ticker },
    )
    return data
  } catch (err: unknown) {
    throw err instanceof Error ? err : new Error(String(err))
  }
}

export function useCompanyDetail(ticker: string | null): CompanyDetailState {
  const [state, setState] = useState<CompanyDetailState>(INITIAL_STATE)

  useEffect(() => {
    if (!ticker) {
      setState(INITIAL_STATE)
      return
    }

    let cancelled = false
    setState({ data: null, loading: true, error: null })

    fetchStockDetail(ticker)
      .then((data) => {
        if (!cancelled) setState({ data, loading: false, error: null })
      })
      .catch((err: Error) => {
        if (!cancelled) setState({ data: null, loading: false, error: err })
      })

    return () => {
      cancelled = true
    }
  }, [ticker])

  return state
}
