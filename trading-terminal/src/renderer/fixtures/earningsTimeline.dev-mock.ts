/* ============================================================================
 * DEV ONLY — do not use in production.
 *
 * EarningsTimeline 컴포넌트가 표시하는 어닝콜 일정 더미값.
 * 타입 정의는 src/lib/types/earningsTimeline.ts 에서 관리한다.
 *
 * 사용 규칙:
 *   - import.meta.env.DEV === true 인 경로에서만 참조할 것.
 * ========================================================================== */

export type {
  EarningsGroupKind,
  EarningsEvent,
  EarningsLiveEvent,
  EarningsGroup,
} from '../../lib/types/earningsTimeline'
export type { EarningsTimelineData as EarningsTimelineFixture } from '../../lib/types/earningsTimeline'

export const earningsTimelineDevMock: EarningsTimelineFixture = {
  live: {
    ticker: 'NVDA',
    name: 'NVIDIA Corp.',
    timeLabel: '진행중',
    elapsed: '25:14',
    callLabel: 'Q3 FY25 Earnings Call',
  },
  groups: [
    {
      kind: 'today',
      label: '오늘',
      events: [
        {
          ticker: 'TSLA',
          name: 'Tesla Inc.',
          timeLabel: '오후 5:00 PM',
          whenLabel: '오후',
          clockLabel: '5:00 PM',
        },
        {
          ticker: 'AMZN',
          name: 'Amazon.com Inc.',
          timeLabel: '오후 5:00 PM',
          whenLabel: '오후',
          clockLabel: '5:00 PM',
        },
      ],
    },
    {
      kind: 'tomorrow',
      label: '내일',
      events: [
        {
          ticker: 'MSFT',
          name: 'Microsoft Corp.',
          timeLabel: '오전 6:30 AM',
          whenLabel: '오전',
          clockLabel: '6:30 AM',
        },
      ],
    },
    {
      kind: 'week',
      label: '이번 주',
      events: [
        {
          ticker: 'META',
          name: 'Meta Platforms',
          timeLabel: '금 오전 6:00 AM',
          whenLabel: '금 오전',
          clockLabel: '6:00 AM',
        },
        {
          ticker: 'GOOGL',
          name: 'Alphabet Inc.',
          timeLabel: '금 오전 7:00 AM',
          whenLabel: '금 오전',
          clockLabel: '7:00 AM',
        },
      ],
    },
  ],
} as const
