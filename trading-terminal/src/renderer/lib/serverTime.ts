/**
 * 백엔드 시각 문자열을 Date 로 읽는다.
 *
 * 백엔드는 LocalDateTime 을 시간대 표기 없이("2026-10-06T19:10:33") 내려주고, 서버는 UTC 로
 * 돈다. 이 문자열을 그대로 new Date() 에 넣으면 로컬 시각으로 해석돼 한국에서는 9시간 늦게
 * 보인다. 시간대 표기(Z 또는 ±hh:mm)가 없는 날짜·시각 문자열은 UTC 로 읽는다.
 */
const ZONELESS_DATETIME = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?$/

export function parseServerTime(value: string | number): Date {
  if (typeof value === 'string' && ZONELESS_DATETIME.test(value)) {
    return new Date(`${value}Z`)
  }
  return new Date(value)
}
