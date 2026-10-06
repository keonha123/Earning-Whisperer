import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'
import STTScriptPanel from '../STTScriptPanel'
vi.mock('react-router-dom', () => ({ useNavigate: () => vi.fn() }))
describe('batched translation display', () => {
  it('keeps completed-call questions available while another call is live', () => {
    const transcript = ['ended', 'live'].map(callId => ({ id: callId, timestamp: '00:00', speaker: 'CFO', text: callId, callId, ticker: 'WMT', sequence: 1 }))
    const html = renderToStaticMarkup(createElement(STTScriptPanel, { transcript, isLive: true, endedCallIds: new Set(['ended']) }))
    expect(html.match(/이 발언에 질문하기/g)).toHaveLength(1)
    expect(html.match(/재생이 끝난 뒤 질문할 수 있습니다/g)).toHaveLength(1)
  })
  it('marks covered originals and renders the combined translation only once', () => {
    const transcript = [1, 2].map(sequence => ({ id: String(sequence), timestamp: '00:00', speaker: 'CFO', text: `Original ${sequence}`, sequence, translationSequences: [1, 2], textKo: sequence === 2 ? '묶음 한국어 번역' : undefined }))
    const html = renderToStaticMarkup(createElement(STTScriptPanel, { transcript, isLive: false }))
    expect(html).toContain('아래 묶음 번역에 포함')
    expect(html).toContain('발언 1, 2 묶음 번역')
    expect(html.match(/묶음 한국어 번역/g)).toHaveLength(1)
    expect(html).not.toContain('한국어 번역 대기 또는 사용 불가')
    expect(html).toContain('Original 1')
    expect(html).toContain('Original 2')
  })
})
