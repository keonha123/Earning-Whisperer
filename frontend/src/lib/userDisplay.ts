/**
 * 사용자 표시용 헬퍼.
 *
 * 카카오 개인앱은 이메일 권한이 없어, 백엔드가 카카오 사용자에게
 * sentinel 이메일(`kakao_{providerId}@earningwhisperer.local`)을 부여한다.
 * 이 sentinel 값을 마이페이지에 노출하지 않기 위해 provider 기준으로 분기한다.
 */

export type AuthProvider = "LOCAL" | "GOOGLE" | "KAKAO";

/**
 * 마이페이지/설정 화면에서 보여줄 이메일 표시 문자열을 반환한다.
 *
 * - KAKAO: "카카오 계정" (sentinel 이메일 숨김)
 * - GOOGLE / LOCAL / null / undefined: 원본 이메일
 */
export function getDisplayEmail(
  email: string,
  provider?: AuthProvider | null
): string {
  if (provider === "KAKAO") {
    return "카카오 계정";
  }
  return email;
}
