export interface SseFrame {
  event: string
  data: string
}

/**
 * text/event-stream 을 조각 단위로 받아 프레임으로 나눈다.
 * 주석(':' 으로 시작, backend 하트비트)은 건너뛰고, 빈 줄로 끝나지 않은 마지막 프레임은 내보내지 않는다(SSE 규칙).
 */
export class SseParser {
  private buffer = ''
  private event: string | null = null
  private data: string[] | null = null

  push(chunk: string): SseFrame[] {
    this.buffer += chunk
    const frames: SseFrame[] = []
    let newline = this.buffer.indexOf('\n')
    while (newline >= 0) {
      let line = this.buffer.slice(0, newline)
      this.buffer = this.buffer.slice(newline + 1)
      if (line.endsWith('\r')) line = line.slice(0, -1)
      const frame = this.consume(line)
      if (frame) frames.push(frame)
      newline = this.buffer.indexOf('\n')
    }
    return frames
  }

  private consume(line: string): SseFrame | null {
    if (line === '') {
      if (this.event === null && this.data === null) return null
      const frame = { event: this.event ?? 'message', data: (this.data ?? []).join('\n') }
      this.event = null
      this.data = null
      return frame
    }
    if (line.startsWith(':')) return null
    const colon = line.indexOf(':')
    const field = colon < 0 ? line : line.slice(0, colon)
    let value = colon < 0 ? '' : line.slice(colon + 1)
    if (value.startsWith(' ')) value = value.slice(1)
    if (field === 'event') this.event = value
    else if (field === 'data') (this.data ??= []).push(value)
    return null
  }
}
