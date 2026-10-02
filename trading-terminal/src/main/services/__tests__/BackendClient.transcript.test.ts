import { beforeEach, describe, expect, it } from 'vitest'
import { kisHttpMock } from '../../../test/setup'
import { BackendClient } from '../BackendClient'

beforeEach(() => kisHttpMock.post.mockReset())

describe('transcript QA transport contract', () => {
  it('preserves selected identity and refusal while allowing the backend QA deadline', async () => {
    const request = { ticker: 'SMOKE', call_id: 'call-1', segment_sequences: [0], question: '매출 증가율은?' }
    const response = { available: false, refused: true, refusal_reason: 'timeout', evidence: [], citations: [] }
    kisHttpMock.post.mockResolvedValue({ data: response })

    expect(await BackendClient.askTranscript(request)).toBe(response)
    const [url, payload, config] = kisHttpMock.post.mock.calls[0]
    expect(url).toBe('/api/v1/transcript/ask')
    expect(payload).toEqual(request)
    // Backend can spend 30 seconds producing an explicit answer/refusal;
    // Electron must not replace it with an earlier generic transport failure.
    expect(config.timeout).toBeGreaterThan(30_000)
    expect(config.timeout).toBeLessThanOrEqual(35_000)
  })
})
