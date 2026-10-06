/** 포트폴리오 화면의 금액 · 등락 표기 (docs/design/design-system.md 문구 규칙). */

export function usd(v: number): string {
  return `$${Math.abs(v).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

/** 부호 붙은 금액. 음수는 하이픈 대신 마이너스 기호를 쓴다. */
export function signedUsd(v: number): string {
  if (v === 0) return usd(0)
  return `${v > 0 ? '+' : '−'}${usd(v)}`
}

export function signedPct(v: number): string {
  if (v === 0) return '0.00%'
  return `${v > 0 ? '+' : '−'}${Math.abs(v).toFixed(2)}%`
}

/** 등락 글자 색. 가격 방향에만 쓰고 0 은 무채색으로 둔다. */
export function directionClass(v: number): string {
  return v > 0 ? 'text-up' : v < 0 ? 'text-down' : 'text-ink-3'
}

/** 색만으로 뜻을 구분하지 않도록 붙이는 기호. */
export function directionMark(v: number): string {
  return v > 0 ? '▲' : v < 0 ? '▼' : ''
}
