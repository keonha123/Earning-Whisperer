import { describe, it, expect, beforeEach, vi } from 'vitest'

const invoke = vi.fn()
vi.mock('../../lib/ipc', async () => {
  const { IPC_CHANNELS } = await import('../../../lib/ipcChannels')
  return { ipc: { invoke: (...args: unknown[]) => invoke(...args), on: vi.fn() }, IPC_CHANNELS }
})

import { useGlossaryStore, RETRY_INTERVAL_MS } from '../useGlossaryStore'
import { IPC_CHANNELS } from '../../../lib/ipcChannels'

function makeGlossary() {
  return {
    version: 2,
    terms: [
      {
        term: 'comp sales',
        aliases: ['comps', 'comparable sales'],
        ko: '기존점 매출',
        definition_ko: '1년 이상 영업한 매장의 매출 증가율입니다.',
        why_ko: '기존 매장 장사가 잘되는지 보여 줍니다.',
        category: 'retail',
      },
      { term: 'eCommerce', aliases: ['e-commerce'], ko: '이커머스', category: 'retail' },
    ],
  }
}

function reset() {
  useGlossaryStore.setState({ status: 'idle', version: 0, terms: [], bySpelling: new Map(), lastAttemptAt: 0 })
}

describe('useGlossaryStore', () => {
  beforeEach(() => {
    reset()
    invoke.mockReset()
  })

  it('snake_case 응답을 camelCase 로 바꾸고 표기별 색인을 만든다', () => {
    expect(useGlossaryStore.getState().setGlossary(makeGlossary())).toBe(true)

    const state = useGlossaryStore.getState()
    expect(state.status).toBe('ready')
    expect(state.version).toBe(2)
    expect(state.bySpelling.get('comps')?.term).toBe('comp sales')
    expect(state.bySpelling.get('comp sales')?.definitionKo).toContain('1년 이상')
    expect(state.bySpelling.get('e-commerce')?.definitionKo).toBeNull()
  })

  it('정의와 이유 중 하나만 있으면 정의가 없는 것으로 본다', () => {
    const raw = makeGlossary()
    delete (raw.terms[0] as Record<string, unknown>).why_ko
    useGlossaryStore.getState().setGlossary(raw)

    expect(useGlossaryStore.getState().bySpelling.get('comp sales')?.definitionKo).toBeNull()
  })

  it('term · ko 가 비었거나 형식이 틀린 항목은 버린다', () => {
    useGlossaryStore.getState().setGlossary({
      version: 2,
      terms: [{ term: ' ', ko: '빈 표기' }, { term: 'guidance' }, 'oops', makeGlossary().terms[0]],
    })

    expect(useGlossaryStore.getState().terms.map((t) => t.term)).toEqual(['comp sales'])
  })

  it('쓸 수 있는 용어가 없으면 반영하지 않는다', () => {
    expect(useGlossaryStore.getState().setGlossary({ version: 2, terms: [] })).toBe(false)
    expect(useGlossaryStore.getState().setGlossary(null)).toBe(false)
    expect(useGlossaryStore.getState().status).toBe('idle')
  })

  it('load 는 사전을 한 번만 조회한다', async () => {
    invoke.mockResolvedValue(makeGlossary())

    await useGlossaryStore.getState().load()
    await useGlossaryStore.getState().load()

    expect(invoke).toHaveBeenCalledTimes(1)
    expect(invoke).toHaveBeenCalledWith(IPC_CHANNELS.GLOSSARY_GET)
    expect(useGlossaryStore.getState().status).toBe('ready')
  })

  it('동시에 여러 번 불러도 한 번만 조회한다', async () => {
    invoke.mockResolvedValue(makeGlossary())

    await Promise.all([useGlossaryStore.getState().load(), useGlossaryStore.getState().load()])

    expect(invoke).toHaveBeenCalledTimes(1)
  })

  it('실패하면 failed 로 두고, 재시도 간격이 지난 뒤에만 다시 조회한다', async () => {
    let now = 1_000_000
    const clock = vi.spyOn(Date, 'now').mockImplementation(() => now)
    vi.spyOn(console, 'error').mockImplementation(() => {})
    invoke
      .mockResolvedValueOnce(null)
      .mockRejectedValueOnce(new Error('AUTH_EXPIRED'))
      .mockResolvedValueOnce(makeGlossary())

    await useGlossaryStore.getState().load()
    expect(useGlossaryStore.getState().status).toBe('failed')

    now += RETRY_INTERVAL_MS - 1
    await useGlossaryStore.getState().load()
    expect(invoke).toHaveBeenCalledTimes(1)

    now += 1
    await useGlossaryStore.getState().load()
    expect(useGlossaryStore.getState().status).toBe('failed')
    expect(invoke).toHaveBeenCalledTimes(2)

    now += RETRY_INTERVAL_MS
    await useGlossaryStore.getState().load()
    expect(useGlossaryStore.getState().status).toBe('ready')
    clock.mockRestore()
  })
})
