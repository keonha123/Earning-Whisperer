import { create } from 'zustand'
import { ipc, IPC_CHANNELS } from '../lib/ipc'

/**
 * 어닝콜 용어 사전 클라이언트 상태 (#111).
 *
 * Backend GET /api/v1/glossary (Contract 7.9) 를 세션당 한 번 받아 둔다. 용어를 누를 때마다
 * 조회하지 않는다 — 정의는 고정 내용이고, 클릭 시 네트워크 요청이 없어야 즉시 뜬다.
 *
 * 사전 조회에 실패해도 자막 · 번역은 그대로 보여야 한다. 실패하면 빈 사전으로 두고(밑줄만 없음)
 * RETRY_INTERVAL_MS 가 지난 뒤의 load() 에서 다시 시도한다. 토큰 만료(AUTH_EXPIRED)도 여기서는 실패로만
 * 다룬다 — 재로그인 안내는 다른 IPC 호출이 맡는다.
 */

/** 실패 후 다시 조회하기까지의 최소 간격. 번역이 올 때마다 부르므로 요청이 몰리지 않게 둔다. */
export const RETRY_INTERVAL_MS = 30_000

export interface GlossaryTerm {
  /** 대표 표기 (영문). */
  term: string
  /** 같은 용어의 다른 표기 (복수형 · 약어 등). */
  aliases: string[]
  /** 번역문에 고정된 한국어 표기. 밑줄 위치를 찾을 때 쓴다. */
  ko: string
  /** 뜻. 없으면 번역 고정에만 쓰는 용어라 밑줄을 긋지 않는다. */
  definitionKo: string | null
  /** 왜 중요한가. definitionKo 와 짝으로 온다. */
  whyKo: string | null
  category: string
}

export type GlossaryStatus = 'idle' | 'loading' | 'ready' | 'failed'

interface GlossaryState {
  status: GlossaryStatus
  version: number
  terms: GlossaryTerm[]
  /** 소문자 표기(term + aliases) → 용어. 번역의 terms_used(원문 표기)로 찾을 때 쓴다. */
  bySpelling: Map<string, GlossaryTerm>
  /** 마지막 조회 시작 시각 (Date.now()). 재시도 간격 판단용. */
  lastAttemptAt: number

  /**
   * 아직 받지 않았으면 조회한다. 진행 중이거나 받았으면, 또는 실패한 지 RETRY_INTERVAL_MS 가 지나지 않았으면
   * 아무것도 하지 않는다.
   */
  load: () => Promise<void>

  /** snake_case 응답을 검증해 반영한다. 형식이 틀리면 false. load 가 쓰고, 테스트에서도 직접 부른다. */
  setGlossary: (raw: unknown) => boolean
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

function nonBlank(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value.trim() : null
}

function toTerm(raw: unknown): GlossaryTerm | null {
  if (!isRecord(raw)) return null
  const term = nonBlank(raw.term)
  const ko = nonBlank(raw.ko)
  if (!term || !ko) return null
  const aliases = Array.isArray(raw.aliases)
    ? raw.aliases.map(nonBlank).filter((a): a is string => a !== null)
    : []
  const definitionKo = nonBlank(raw.definition_ko)
  const whyKo = nonBlank(raw.why_ko)
  return {
    term,
    aliases,
    ko,
    // 둘 중 하나만 있으면 팝오버가 반쪽으로 뜬다. 짝이 맞을 때만 정의로 쓴다.
    definitionKo: definitionKo && whyKo ? definitionKo : null,
    whyKo: definitionKo && whyKo ? whyKo : null,
    category: nonBlank(raw.category) ?? '',
  }
}

export const useGlossaryStore = create<GlossaryState>((set, get) => ({
  status: 'idle',
  version: 0,
  terms: [],
  bySpelling: new Map(),
  lastAttemptAt: 0,

  load: async () => {
    const { status, lastAttemptAt } = get()
    if (status === 'loading' || status === 'ready') return
    if (status === 'failed' && Date.now() - lastAttemptAt < RETRY_INTERVAL_MS) return
    set({ status: 'loading', lastAttemptAt: Date.now() })
    try {
      const raw = await ipc.invoke(IPC_CHANNELS.GLOSSARY_GET)
      if (!get().setGlossary(raw)) set({ status: 'failed' })
    } catch (e) {
      console.error('[useGlossaryStore] 용어 사전 조회 실패:', e)
      set({ status: 'failed' })
    }
  },

  setGlossary: (raw) => {
    if (!isRecord(raw) || !Array.isArray(raw.terms)) return false
    const terms = raw.terms.map(toTerm).filter((t): t is GlossaryTerm => t !== null)
    if (terms.length === 0) return false
    const bySpelling = new Map<string, GlossaryTerm>()
    for (const term of terms) {
      for (const spelling of [term.term, ...term.aliases]) {
        const key = spelling.toLowerCase()
        if (!bySpelling.has(key)) bySpelling.set(key, term)
      }
    }
    set({
      status: 'ready',
      version: typeof raw.version === 'number' ? raw.version : 0,
      terms,
      bySpelling,
    })
    return true
  },
}))
