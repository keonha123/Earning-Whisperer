/* ============================================================================
 * DEV ONLY — do not use in production.
 *
 * SpeakerProfileModal 이 표시하는 발화자 프로필 더미 데이터.
 * Oracle Q4 FY2026 어닝콜 참가자 기준.
 *
 * matchKey 는 STT 트랜스크립트의 speaker 필드 소문자와 매칭한다.
 * ========================================================================== */

export interface SpeakerProfile {
  id: string
  /** STT speaker 필드 매칭키 (소문자). */
  matchKey: string
  name: string
  title: string
  tenure: string
  /** 한 줄 성향 요약. */
  style: string
  /** 화법 특성 태그. */
  traits: string[]
  /** 최근 가이던스 달성률 (%). */
  guidanceAccuracy: number
  /** 주요 발언 이력 (날짜 · 내용). */
  history: { date: string; quote: string }[]
  /** 투자자 유의사항. */
  watchpoints: string[]
}

export const speakerProfilesDevMock: readonly SpeakerProfile[] = [
  {
    id: 'hilary-maxson',
    matchKey: 'cfo · hilary maxson',
    name: 'Hilary Maxson',
    title: 'CFO · Executive VP',
    tenure: '2022년 합류 — 재임 3년',
    style: '수치 정밀형. 가이던스 범위를 명확히 제시하며 비용 구조와 마진 방어 논리 중심 발언.',
    traits: ['수치 정밀', 'CapEx 강조', '마진 포커스', '중립 톤'],
    guidanceAccuracy: 89,
    history: [
      { date: 'Q3 FY26', quote: '"매출 $18.1B — 가이던스 상단 부합, 인프라 성장 가속 지속"' },
      { date: 'Q2 FY26', quote: '"OCI 성장률 60%대 진입 — 데이터센터 용량 확충 가속"' },
      { date: 'Q1 FY26', quote: '"FY26 CapEx 대폭 확대 — AI 인프라 수요 선점 전략"' },
    ],
    watchpoints: [
      '총마진 하락 표현 시 CapEx 규모와 연계해 해석 필요',
      '"일회성 효과 제외" 발언 시 현금흐름 수치 재검증 권장',
      'FY27 CapEx $70B 언급 — 단기 수익성 희석 가능성 주시',
    ],
  },
  {
    id: 'clay-magouyrk',
    matchKey: 'ceo · clay magouyrk',
    name: 'Clay Magouyrk',
    title: 'EVP · Oracle Cloud Infrastructure (OCI)',
    tenure: '2019년 합류 — OCI 총괄 5년',
    style: '기술 성과 중심 발언. GPU 클러스터, 데이터센터 용량, AI 워크로드 계약 수치에 강함.',
    traits: ['인프라 전문', '기술 수치', 'CapEx 구조 설명', '성장 내러티브'],
    guidanceAccuracy: 0,
    history: [
      { date: 'Q3 FY26', quote: '"OCI GPU 클러스터 수요가 공급을 압도적으로 초과 중"' },
      { date: 'Q2 FY26', quote: '"AI 워크로드 인프라 계약, 연간 누적 $10B+ 돌파"' },
    ],
    watchpoints: [
      '"수요가 공급을 초과" 표현 반복 — 구체 수치 없으면 검증 어려움',
      'CapEx 투자 회수 시점(ROIC high-20s 언급) 주시 — 실현 시점 불확실',
    ],
  },
  {
    id: 'mike-sicilia',
    matchKey: 'ceo · mike sicilia',
    name: 'Mike Sicilia',
    title: 'EVP · Cloud and License Business',
    tenure: '2021년 합류 — 클라우드·라이선스 총괄',
    style: '제품 기능 및 고객 도입 사례 중심. AI Agent 활용 SaaS 성장 내러티브 주도.',
    traits: ['제품 중심', '고객 도입 사례', 'AI SaaS', '엔터프라이즈 포커스'],
    guidanceAccuracy: 0,
    history: [
      { date: 'Q3 FY26', quote: '"Fusion Apps에 AI Agent 통합 — 고객사 자동화 사용 사례 급증"' },
      { date: 'Q2 FY26', quote: '"NetSuite 고객 기반 클라우드 전환 속도 가속 중"' },
    ],
    watchpoints: [
      '고객 도입 사례 발언은 선별된 성공 사례 — 전체 전환율 추적 필요',
      'AI Agent 기능 수익화 시점 명시 없을 경우 미래 성장 주장 과장 가능성',
    ],
  },
  {
    id: 'ken-bond',
    matchKey: 'ir · ken bond',
    name: 'Ken Bond',
    title: 'IR · SVP 투자자관계',
    tenure: '2013년 합류 — IR 총괄 12년',
    style: '진행·전환 역할 중심. 정보 제공보다 세션 흐름 제어. 일정 안내·Q&A 전환 담당.',
    traits: ['진행 역할', '중립 톤', '일정 안내', '세션 관리'],
    guidanceAccuracy: 0,
    history: [
      { date: 'Q3 FY26', quote: '(진행) "다음 분기 실적 발표는 [일시]로 예정되어 있습니다."' },
      { date: 'Q4 FY26', quote: '(진행) "Investor Day는 10월 28일 라스베이거스에서 열릴 예정입니다."' },
    ],
    watchpoints: [
      '실질적 정보 포함 없음 — IR 발언 전후로 종료 신호 여부 판단',
      'Q&A 전환 시점 → 경영진 질문 회피·우회 반응 주목 필요',
    ],
  },
] as const
