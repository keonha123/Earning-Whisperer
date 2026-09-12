/**
 * 종목 상세 화면(CompanyDrawer)의 표시 모델.
 *
 * 값은 `STOCK_GET_DETAIL` IPC 로 백엔드에서 받는다. 타입만 여기 둔다 —
 * 원래 `fixtures/companyDetail.dev-mock.ts` 안에 더미 데이터와 함께 있어서,
 * 목업 파일을 지우면 컴포넌트가 같이 깨지는 구조였다.
 */

export interface EarningsHistoryRow {
  /** 분기 라벨 (예: "Q2 FY25"). */
  quarter: string
  epsEstimate: string
  epsActual: string
  /** 부호 포함 문자열 (예: "+17.2%", "−1.7%"). 색은 호출자가 부호로 결정. */
  surprisePercent: string
  priceReactionPercent: string
}

export interface ChartPoint {
  /** "MM-DD" 라벨. SVG 그리기용. */
  date: string
  /** 종가. */
  price: number
}
