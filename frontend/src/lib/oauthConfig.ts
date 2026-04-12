const GOOGLE_CLIENT_ID = process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID || "";
const GOOGLE_REDIRECT_URI =
  process.env.NEXT_PUBLIC_GOOGLE_REDIRECT_URI || "http://localhost:3000/auth/callback";

const KAKAO_CLIENT_ID = process.env.NEXT_PUBLIC_KAKAO_CLIENT_ID || "";
const KAKAO_REDIRECT_URI =
  process.env.NEXT_PUBLIC_KAKAO_REDIRECT_URI || "http://localhost:3000/auth/callback";

/**
 * Google OAuth 인증 URL 생성.
 * state는 CSRF 방지용 — sessionStorage에 저장 후 callback에서 검증.
 */
export function buildGoogleAuthUrl(): string {
  const state = crypto.randomUUID();
  sessionStorage.setItem("oauth_state", state);
  sessionStorage.setItem("oauth_provider", "GOOGLE");

  const params = new URLSearchParams({
    client_id: GOOGLE_CLIENT_ID,
    redirect_uri: GOOGLE_REDIRECT_URI,
    response_type: "code",
    scope: "openid email profile",
    state,
    access_type: "offline",
    prompt: "consent",
  });

  return `https://accounts.google.com/o/oauth2/v2/auth?${params.toString()}`;
}

/**
 * Kakao OAuth 인증 URL 생성.
 */
export function buildKakaoAuthUrl(): string {
  const state = crypto.randomUUID();
  sessionStorage.setItem("oauth_state", state);
  sessionStorage.setItem("oauth_provider", "KAKAO");

  const params = new URLSearchParams({
    client_id: KAKAO_CLIENT_ID,
    redirect_uri: KAKAO_REDIRECT_URI,
    response_type: "code",
    scope: "account_email profile_nickname",
    state,
  });

  return `https://kauth.kakao.com/oauth/authorize?${params.toString()}`;
}

export function getGoogleRedirectUri(): string {
  return GOOGLE_REDIRECT_URI;
}

export function getKakaoRedirectUri(): string {
  return KAKAO_REDIRECT_URI;
}

/**
 * callback에서 저장된 provider를 반환.
 */
export function getOAuthProvider(): string {
  return sessionStorage.getItem("oauth_provider") || "GOOGLE";
}

/**
 * provider에 맞는 redirect_uri 반환.
 */
export function getRedirectUri(provider: string): string {
  switch (provider) {
    case "KAKAO":
      return KAKAO_REDIRECT_URI;
    default:
      return GOOGLE_REDIRECT_URI;
  }
}

/**
 * callback에서 state 검증 후 삭제.
 */
export function verifyOAuthState(state: string | null): boolean {
  if (!state) return false;
  const saved = sessionStorage.getItem("oauth_state");
  sessionStorage.removeItem("oauth_state");
  return saved === state;
}
