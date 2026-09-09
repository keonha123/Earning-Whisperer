/**
 * 종목 표시 메타데이터 — 회사명과 로고 색.
 *
 * 시세나 손익 같은 <b>데이터</b>가 아니라 표시용 상수다. 백엔드의 보유종목 응답은
 * ticker/수량/평단가만 주므로, 화면에 회사명을 띄우려면 어딘가 매핑이 필요하다.
 *
 * 원래 `fixtures/holdings.dev-mock.ts` 안에 가짜 시세와 섞여 있었다. 그 파일은
 * 보유종목이 없을 때 <b>가짜 보유 내역을 화면에 띄우는</b> 용도로도 쓰이고 있어서
 * 분리했다. 여기에는 가짜 숫자를 두지 않는다.
 *
 * 색은 디자인 캔버스의 `.lg-*` 클래스에서 가져온 값이다.
 * 목록에 없는 종목은 {@link CompanyLogo} 의 기본 색으로 떨어진다.
 *
 * 추후 백엔드에 종목 메타데이터 컬럼이 생기면 이 파일은 제거한다.
 */
export interface CompanyMeta {
  name: string
  logoBg: string
  logoFg: string
  logoLabel?: string
}

export const COMPANY_META: Readonly<Record<string, CompanyMeta>> = {
  ORCL: { name: 'Oracle Corp.', logoBg: '#1a1a3e', logoFg: '#a5b4fc', logoLabel: 'OR' },
  AAPL: { name: 'Apple Inc.', logoBg: '#1f2937', logoFg: '#e5e7eb', logoLabel: 'AA' },
  NVDA: { name: 'NVIDIA Corp.', logoBg: '#103a2b', logoFg: '#6ee7b7', logoLabel: 'NV' },
  MSFT: { name: 'Microsoft Corp.', logoBg: '#1e293b', logoFg: '#93c5fd', logoLabel: 'MS' },
  AMZN: { name: 'Amazon.com Inc.', logoBg: '#332617', logoFg: '#fcd34d', logoLabel: 'AM' },
  META: { name: 'Meta Platforms', logoBg: '#1e2b4a', logoFg: '#93c5fd', logoLabel: 'ME' },
  GOOGL: { name: 'Alphabet Inc.', logoBg: '#2a2320', logoFg: '#fdba74', logoLabel: 'GO' },
}
