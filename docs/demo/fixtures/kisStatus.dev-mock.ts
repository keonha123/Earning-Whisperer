/* ============================================================================
 * DEV ONLY — do not use in production.
 *
 * 이 fixture 는 SettingsPage 의 KIS 연동 메타데이터 표시 영역(AppKey 마스킹,
 * 토큰 만료시간, 핑 지연 등)을 디자인 단계에서 시각화하기 위한 더미 데이터다.
 *
 * 사용 규칙:
 *   - import.meta.env.DEV === true 인 경로에서만 참조할 것.
 *   - prod 빌드에서는 어떤 식으로든 화면에 노출되어선 안 된다.
 *     (가짜 AppKey/지연 수치가 사용자에게 진짜처럼 보이는 사고를 방지)
 *
 * 추후 KisService 가 실제 메타데이터를 IPC 로 노출하면 이 파일은 제거 대상.
 *
 * TODO(별도 백엔드 PR):
 *   - appKey 마스킹은 KisService 측에서 처리
 *   - tokenExpiresIn 은 KIS_TOKEN_REFRESHED 이벤트에 expiresAt 포함되도록 확장
 *   - lastPingAgo / pingMs 는 WS 또는 KIS API latency 추적기 필요
 * ========================================================================== */

export const kisStatusDevMock = {
  appKey: 'P-a8***···***c2',
  registeredAt: '2026-03-14',
  tokenExpiresIn: '5시간 23분',
  autoRefresh: true,
  lastPingAgo: '2초 전',
  pingMs: 42,
} as const
