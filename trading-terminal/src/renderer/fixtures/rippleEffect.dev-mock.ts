/* ============================================================================
 * DEV ONLY — do not use in production.
 *
 * RippleEffectModal 이 표시하는 서플라이체인 파급효과 더미 데이터.
 * 중심 종목: ORCL (Oracle Q4 FY2026 어닝콜 기준).
 *
 * 레이아웃: 중심 노드(ORCL) + 1~2단계 연결 노드.
 * impact: 양수=긍정 파급(주가 상승 기대), 음수=부정.
 * relation: 서플라이체인 관계 유형.
 * ========================================================================== */

export interface RippleNode {
  id: string
  ticker: string
  name: string
  /** SVG 캔버스 기준 중심 좌표 (0–100 퍼센트 단위). */
  cx: number
  cy: number
  /** 파급 강도 (−1 ~ +1). 양수=긍정, 음수=부정. */
  impact: number
  /** 종목 간 관계. */
  relation: string
  /** 파급 코멘트 (툴팁 / 리스트). */
  comment: string
}

export interface RippleEdge {
  from: string
  to: string
}

/** ORCL 어닝콜 파급효과 목업 — 중심(ORCL) + 8개 연결 종목. */
export const rippleNodesDevMock: readonly RippleNode[] = [
  {
    id: 'ORCL',
    ticker: 'ORCL',
    name: 'Oracle Corp.',
    cx: 50,
    cy: 50,
    impact: 0.76,
    relation: '어닝콜 발원',
    comment: 'OCI +93% YoY, EPS +24%, RPO $6,380억 → 강한 성장성 확인',
  },
  // ── Tier 1: 직접 수혜 / 리스크 ──────────────────────────────────────────
  {
    id: 'NVDA',
    ticker: 'NVDA',
    name: 'NVIDIA Corp.',
    cx: 22,
    cy: 22,
    impact: 0.62,
    relation: 'GPU 공급사 (OCI AI 인프라)',
    comment: 'OCI AI 워크로드 93% 성장 → Oracle의 NVIDIA GPU 수요 확대 직접 수혜',
  },
  {
    id: 'AMZN',
    ticker: 'AMZN',
    name: 'Amazon (AWS)',
    cx: 78,
    cy: 22,
    impact: -0.55,
    relation: '클라우드 1위 경쟁사',
    comment: 'OCI 성장 가속으로 AWS 엔터프라이즈 고객 이탈 압박 — 시장점유율 경쟁 심화',
  },
  {
    id: 'MSFT',
    ticker: 'MSFT',
    name: 'Microsoft (Azure)',
    cx: 82,
    cy: 50,
    impact: -0.38,
    relation: '클라우드 2위 경쟁사',
    comment: 'Oracle DB 연동 엔터프라이즈 고객의 OCI 전환 가속 → Azure 수요 일부 잠식',
  },
  {
    id: 'GOOGL',
    ticker: 'GOOGL',
    name: 'Alphabet (GCP)',
    cx: 50,
    cy: 18,
    impact: -0.28,
    relation: '클라우드 3위 경쟁사',
    comment: 'AI 인프라 부문 OCI 성장이 GCP 고객 획득 경쟁을 심화시킴',
  },
  {
    id: 'CRM',
    ticker: 'CRM',
    name: 'Salesforce',
    cx: 78,
    cy: 78,
    impact: -0.32,
    relation: '엔터프라이즈 SaaS 경쟁사',
    comment: 'Oracle Cloud Apps +10% — AI Agent 기능 포함 SaaS 확대로 CRM 시장 경쟁 심화',
  },
  {
    id: 'SAP',
    ticker: 'SAP',
    name: 'SAP SE',
    cx: 50,
    cy: 82,
    impact: -0.20,
    relation: '엔터프라이즈 ERP 경쟁사',
    comment: 'Oracle Fusion Apps 성장이 SAP ERP 시장 점유율에 간접 압박',
  },
  // ── Tier 2: 간접 연관 ────────────────────────────────────────────────────
  {
    id: 'AMD',
    ticker: 'AMD',
    name: 'AMD',
    cx: 18,
    cy: 50,
    impact: 0.28,
    relation: '2차 GPU 공급사 (OCI)',
    comment: 'OCI AI 인프라 확대 시 AMD Instinct GPU 수요도 간접 수혜 가능',
  },
  {
    id: 'IBM',
    ticker: 'IBM',
    name: 'IBM',
    cx: 22,
    cy: 78,
    impact: -0.18,
    relation: '레거시 DB·하이브리드 클라우드 경쟁사',
    comment: 'Oracle DB 클라우드 전환 가속이 IBM DB2 엔터프라이즈 고객 기반에 압박',
  },
] as const

export const rippleEdgesDevMock: readonly RippleEdge[] = [
  { from: 'ORCL', to: 'NVDA' },
  { from: 'ORCL', to: 'AMZN' },
  { from: 'ORCL', to: 'MSFT' },
  { from: 'ORCL', to: 'GOOGL' },
  { from: 'ORCL', to: 'CRM' },
  { from: 'ORCL', to: 'SAP' },
  { from: 'ORCL', to: 'AMD' },
  { from: 'ORCL', to: 'IBM' },
] as const
