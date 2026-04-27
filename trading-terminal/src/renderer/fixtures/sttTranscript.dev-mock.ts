/* ============================================================================
 * DEV ONLY — do not use in production.
 *
 * STTScriptPanel 이 표시하는 어닝콜 STT 스크립트 더미 데이터.
 * 발췌: NVIDIA Q3 FY2025 어닝콜 공식 트랜스크립트 (요약/번안).
 *
 * 사용 규칙:
 *   - import.meta.env.DEV === true 인 경로에서만 참조할 것.
 *   - prod 빌드에서는 STTScriptPanel 이 placeholder ("실시간 데이터 동기화 중")
 *     을 표시하고 본 fixture 가 화면에 도달하지 않아야 한다.
 *
 * 추후 백엔드 PR:
 *   - StompService 에 `/user/{userId}/queue/transcript` 채널 추가 예정.
 *   - 그 때 본 fixture 는 제거되고 IPC 스트림으로 대체.
 * ========================================================================== */

export interface TranscriptLine {
  /** 안정적 React key. fixture 내 unique. */
  id: string
  /** "mm:ss" 형식. 어닝콜 시작 시각 기준 경과 시간 표시용. */
  timestamp: string
  /** 화자 라벨 (e.g. "Jensen Huang (CEO)"). */
  speaker: string
  /** 한 줄 텍스트. plain string 으로만 렌더 (XSS 방지 — innerHTML 금지). */
  text: string
  /**
   * AI 점수 (선택). −1 ~ +1 범위.
   * 이 라인이 점수 신호와 직접 매칭되는 경우만 채운다.
   */
  ai_score?: number
}

export const sttTranscriptDevMock: readonly TranscriptLine[] = [
  {
    id: 'stt-001',
    timestamp: '00:42',
    speaker: 'CFO · Colette Kress',
    text:
      'Data Center revenue reached a record $30.8B, up 112% year-over-year, driven by Hopper and early Blackwell shipments to hyperscalers.',
    ai_score: 0.62,
  },
  {
    id: 'stt-002',
    timestamp: '01:05',
    speaker: 'CFO · Colette Kress',
    text:
      'We delivered record total revenue of $35.1B, exceeding our outlook of $32.5B. Gross margin expanded 220 bps sequentially.',
    ai_score: 0.71,
  },
  {
    id: 'stt-003',
    timestamp: '01:28',
    speaker: 'CFO · Colette Kress',
    text:
      'Networking grew 20% sequentially. Supply of Blackwell in Q4 is being described by customers as constrained into calendar 2025 on a systems basis.',
  },
  {
    id: 'stt-004',
    timestamp: '01:51',
    speaker: 'CEO · Jensen Huang',
    text:
      'Guidance for Q4 revenue raised to $42.0B ± 2%, with Blackwell ramp contributing meaningfully. We expect sequential gross margin to step up to mid-70s.',
    ai_score: 0.78,
  },
  {
    id: 'stt-005',
    timestamp: '02:14',
    speaker: 'CEO · Jensen Huang',
    text:
      'Sovereign AI infrastructure projects in Europe, Middle East, and APAC are now in the hundreds of MW commitments. Demand significantly outstrips supply.',
  },
  {
    id: 'stt-006',
    timestamp: '02:37',
    speaker: 'Q&A · Stacy Rasgon (Bernstein)',
    text:
      '블랙웰 공급 제약은 언제까지 지속될까요? 그리고 호퍼 수요는 안정적으로 유지되고 있는지 궁금합니다.',
  },
  {
    id: 'stt-007',
    timestamp: '02:59',
    speaker: 'CEO · Jensen Huang',
    text:
      'Blackwell supply tightness will persist for several quarters. Hopper demand remains very strong — we are shipping both in parallel through 2025.',
    ai_score: 0.66,
  },
  {
    id: 'stt-008',
    timestamp: '03:22',
    speaker: 'Q&A · Vivek Arya (BofA)',
    text:
      '데이터센터 매출 중 추론 (inference) 비중과 향후 성장 동력에 대해 코멘트 부탁드립니다.',
  },
  {
    id: 'stt-009',
    timestamp: '03:48',
    speaker: 'CEO · Jensen Huang',
    text:
      'Inference now represents over 40% of Data Center revenue, up from ~30% a year ago. Reasoning models are driving a step-function increase in compute per query.',
    ai_score: 0.74,
  },
  {
    id: 'stt-010',
    timestamp: '04:11',
    speaker: 'CEO · Jensen Huang',
    text:
      'We see 2025 as an inflection year — Blackwell ramp, sovereign AI, and enterprise adoption all converging. Long-term TAM remains at multi-trillion scale.',
    ai_score: 0.82,
  },
  {
    id: 'stt-011',
    timestamp: '04:35',
    speaker: 'CFO · Colette Kress',
    text:
      'Operating expenses guided up mid-30% YoY in Q4 — investment in R&D, expanding our software stack and enterprise GTM remain priorities.',
  },
  {
    id: 'stt-012',
    timestamp: '04:58',
    speaker: 'CEO · Jensen Huang',
    text:
      'Closing remarks: We are at the beginning of a new industrial revolution. AI factories will become the foundation of every modern enterprise.',
    ai_score: 0.69,
  },
] as const
