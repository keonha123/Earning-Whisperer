import { useEffect, useMemo, useRef } from 'react'
import { ipc, IPC_CHANNELS } from '../lib/ipc'
import { locateTerms, type TermSpan } from '../lib/glossaryHighlight'
import { useGlossaryStore, type GlossaryStatus, type GlossaryTerm } from '../store/useGlossaryStore'
import {
  useTranscriptTranslationStore,
  type TranscriptTranslation,
} from '../store/useTranscriptTranslationStore'

export interface HighlightedTranslation extends TranscriptTranslation {
  /** 번역문 안의 용어 밑줄 위치. 시작 위치 순. 사전이 없으면 빈 배열. */
  spans: TermSpan[]
}

/**
 * useTranscriptTranslation — 자막 번역 + 용어 밑줄 사이드이펙트 훅 (#110 · #111).
 *
 * Backend STOMP /topic/transcript-translation/{ticker} 를 구독하고, 용어 사전을 받아 번역문마다
 * 밑줄 위치(spans)를 계산해 돌려준다. useTranscriptDiff 와 같은 구조이며 같은 ticker 를 따라간다.
 *
 * 화면은 spans 로 번역문을 잘라 밑줄을 긋고, 클릭 시 span.term 의 definitionKo · whyKo 를 보여 주면 된다.
 * 클릭할 때 네트워크 요청은 없다.
 *
 * <b>한 화면에서 한 번만 호출한다.</b> 구독에 참조 카운트가 없어, 같은 ticker 로 두 곳에서 부르면 한쪽이
 * unmount 될 때 다른 쪽 구독까지 끊긴다. 상위(예: TradingRoomPage)에서 부르고 결과를 props 로 내린다.
 *
 * @returns items 첫 sequence 순으로 정렬된 번역 문단. 같은 문단은 다시 렌더해도 같은 객체다.
 *          glossaryStatus 사전 조회 상태 — failed 여도 번역은 그대로 나오고 밑줄만 없다.
 */
export function useTranscriptTranslation(ticker: string | null): {
  items: readonly HighlightedTranslation[]
  callId: string | null
  glossaryStatus: GlossaryStatus
  clear: (ticker: string) => void
} {
  const upsertTranslation = useTranscriptTranslationStore((s) => s.upsertTranslation)
  const clear = useTranscriptTranslationStore((s) => s.clearTicker)
  const state = useTranscriptTranslationStore((s) => s.byTicker.get(ticker ?? ''))
  const loadGlossary = useGlossaryStore((s) => s.load)
  const glossaryStatus = useGlossaryStore((s) => s.status)
  const bySpelling = useGlossaryStore((s) => s.bySpelling)

  useEffect(() => {
    const unsubscribe = ipc.on(IPC_CHANNELS.TRANSCRIPT_TRANSLATION_RECEIVED, (payload: unknown) => {
      // 검증은 store 의 upsertTranslation 이 수행한다.
      upsertTranslation(payload)
    })
    return unsubscribe
    // upsertTranslation 은 zustand 가 동일 reference 보장.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // 처음 붙을 때, 그리고 사전 없이 번역이 도착할 때마다 사전을 요청한다. 받았거나 받는 중이거나
  // 실패 직후면 store 가 무시하므로 요청이 몰리지 않는다.
  const itemCount = state?.items.length ?? 0
  useEffect(() => {
    void loadGlossary()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [itemCount])

  useEffect(() => {
    if (!ticker) return
    void ipc.invoke(IPC_CHANNELS.TRANSCRIPT_TRANSLATION_SUBSCRIBE, { ticker })
    return () => {
      void ipc.invoke(IPC_CHANNELS.TRANSCRIPT_TRANSLATION_UNSUBSCRIBE, { ticker })
    }
  }, [ticker])

  // 문단 객체는 store 에서 바뀌지 않으므로, 사전이 그대로면 이전 계산을 재사용한다.
  // 새 번역 1건이 와도 나머지 문단은 같은 객체로 남아 React.memo 가 효과를 낸다.
  const cache = useRef<{
    bySpelling: ReadonlyMap<string, GlossaryTerm>
    byItem: WeakMap<TranscriptTranslation, HighlightedTranslation>
  }>({ bySpelling, byItem: new WeakMap() })
  if (cache.current.bySpelling !== bySpelling) {
    cache.current = { bySpelling, byItem: new WeakMap() }
  }
  const items = useMemo(() => {
    const { byItem } = cache.current
    return (state?.items ?? []).map((item) => {
      let highlighted = byItem.get(item)
      if (!highlighted) {
        highlighted = { ...item, spans: locateTerms(item.textKo, item.termsUsed, bySpelling) }
        byItem.set(item, highlighted)
      }
      return highlighted
    })
  }, [state, bySpelling])

  return {
    items,
    callId: state?.callId ?? null,
    glossaryStatus,
    clear,
  }
}
