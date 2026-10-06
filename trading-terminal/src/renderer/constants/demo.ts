/**
 * 시연 재생 종목. 백엔드 시연 스크립트(backend/src/main/resources/data/demo-earnings-call.json)의
 * `ticker` 와 같아야 한다. 스크립트 종목을 바꾸면 이 값도 함께 바꾼다.
 *
 * 시연 진입점은 홈 하나뿐이고 이 종목으로 콜 화면을 연다. 다른 종목에서 재생하는 실수를 막기 위해서다.
 */
export const DEMO_TICKER = 'WMT'

/** 콜 화면을 열면서 시연 재생을 시작하라는 표시 (`/call?ticker=WMT&demo=start`). */
export const DEMO_START_PARAM = 'demo'
export const DEMO_START_VALUE = 'start'
