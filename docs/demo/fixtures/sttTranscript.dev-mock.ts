/* ============================================================================
 * DEV ONLY — do not use in production.
 *
 * STTScriptPanel 이 표시하는 어닝콜 STT 스크립트 더미 데이터.
 * 발췌: Oracle Q4 FY2026 어닝콜 공식 트랜스크립트 (요약/번안).
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
  /** "HH:MM:SS" 형식. 실제 어닝콜 진행 KST 절대시각. */
  timestamp: string
  /** 화자 라벨 (e.g. "CFO · Hilary Maxson"). */
  speaker: string
  /** 한 줄 텍스트. plain string 으로만 렌더 (XSS 방지 — innerHTML 금지). */
  text: string
  /**
   * AI 점수 (선택). −1 ~ +1 범위.
   * 이 라인이 점수 신호와 직접 매칭되는 경우만 채운다.
   */
  ai_score?: number
}

/**
 * 영상2용 — Oracle Q4 FY2026 어닝콜 후반 (06:59:00~07:05:00).
 *
 * 진입 시점: 콜 종료(07:05:00) 3분 전인 07:02:00.
 *
 * 구조:
 *   - 인덱스 0~5 (PRE_LOADED_STEPS=6): 진입 전 최근 3분간 내역. 즉시 표시.
 *   - 인덱스 6~12: 진입 후 20초 간격으로 순차 노출. 콜 종료까지 약 2.5분.
 */
export const PRE_LOADED_STEPS = 6

export const sttTranscriptDevMock: readonly TranscriptLine[] = [
  // ── 이미 올라온 라인 (인덱스 0~5, 06:59:00~07:01:30) ─────────────────────────
  {
    id: 'stt-001',
    timestamp: '06:59:00',
    speaker: 'Analyst · Kirk Materne',
    text: 'Bring Your Own Hardware와 선지급 계약의 비중이 앞으로 어떻게 변할지, 그리고 이 구조에서 Oracle의 차별 가치가 무엇인지 질문합니다.',
    ai_score: -0.02,
  },
  {
    id: 'stt-002',
    timestamp: '06:59:30',
    speaker: 'EVP OCI · Clay Magouyrk',
    text: '미래의 계약 비중을 정확히 예측하기는 어렵지만, AI 가속기와 고객 유형, 사업 구조가 빠르게 변하고 있다고 설명합니다.',
    ai_score: 0.00,
  },
  {
    id: 'stt-003',
    timestamp: '07:00:00',
    speaker: 'EVP OCI · Clay Magouyrk',
    text: 'Oracle은 단순히 자본을 대신 투입하는 역할뿐 아니라, 데이터센터를 설계하고 구축하며 보안과 네트워크, 클라우드 운영까지 함께 제공한다고 말합니다.',
    ai_score: 0.19,
  },
  {
    id: 'stt-004',
    timestamp: '07:00:30',
    speaker: 'EVP OCI · Clay Magouyrk',
    text: '가속기만 있다고 클라우드가 되는 것이 아니며, 범용 컴퓨트, 스토리지, 로드밸런서, 보안, ID 관리가 함께 필요하다고 설명합니다.',
    ai_score: 0.22,
  },
  {
    id: 'stt-005',
    timestamp: '07:01:00',
    speaker: 'EVP OCI · Clay Magouyrk',
    text: '대규모 클러스터 운영은 매우 복잡하며, Oracle은 이러한 클러스터를 지속적으로 유지·관리하는 능력을 제공한다는 점이 차별점이라고 말합니다.',
    ai_score: 0.18,
  },
  {
    id: 'stt-006',
    timestamp: '07:01:30',
    speaker: 'EVP OCI · Clay Magouyrk',
    text: '향후에도 BYOH, 선지급, Oracle 자본 투입 등 다양한 구조가 계속 진화할 것이며, 어느 한 방식으로 수렴되지 않을 것이라고 설명합니다.',
    ai_score: 0.05,
  },
  // ── 실시간 노출 라인 (인덱스 6~12, 20초 간격) ────────────────────────────────
  {
    id: 'stt-007',
    timestamp: '07:02:00',
    speaker: 'CFO · Hilary Maxson',
    text: 'BYOH와 선지급 구조의 마진이 기존 계약과 같거나 더 좋다고 다시 강조합니다. 이 구조가 Oracle의 수익성을 훼손하지 않는다는 점을 재확인합니다.',
    ai_score: 0.23,
  },
  {
    id: 'stt-008',
    timestamp: '07:02:30',
    speaker: 'CFO · Hilary Maxson',
    text: 'FY2027 순현금 기준 CapEx 700억 달러는 고객 선지급과 시점 차이 200억~250억 달러를 제외한 수치이며, 보고 기준 CapEx는 그 합계라고 설명합니다.',
    ai_score: -0.07,
  },
  {
    id: 'stt-009',
    timestamp: '07:03:00',
    speaker: 'CFO · Hilary Maxson',
    text: '고객에게 대금을 나중에 받는 일반 구조와 달리, 선지급 구조에서는 고객 자금을 먼저 받기 때문에 Oracle의 자금 조달 부담이 크게 줄어든다고 설명합니다.',
    ai_score: 0.16,
  },
  {
    id: 'stt-010',
    timestamp: '07:03:30',
    speaker: 'CFO · Hilary Maxson',
    text: '이러한 구조는 경제성 측면에서도 긍정적이며, 투입 자본 대비 수익률을 개선할 수 있다고 설명합니다. ROIC가 더 높아질 수 있다고 덧붙입니다.',
    ai_score: 0.14,
  },
  {
    id: 'stt-011',
    timestamp: '07:04:00',
    speaker: 'IR · Ken Bond',
    text: '질의응답이 종료됩니다. 다음 분기 Q1 FY2027 실적 발표는 9월 10일로 예정되어 있다고 안내합니다.',
    ai_score: 0.00,
  },
  {
    id: 'stt-012',
    timestamp: '07:04:30',
    speaker: 'IR · Ken Bond',
    text: 'Oracle Investor Day가 10월 28일 라스베이거스에서 AI World 컨퍼런스와 함께 열릴 예정이라고 안내합니다.',
    ai_score: 0.02,
  },
  {
    id: 'stt-013',
    timestamp: '07:05:00',
    speaker: 'Operator · Lisa',
    text: 'Oracle Q4 FY2026 실적 발표 컨퍼런스콜이 종료되었습니다. 참석해 주신 모든 분들께 감사드립니다.',
    ai_score: 0.00,
  },
] as const
