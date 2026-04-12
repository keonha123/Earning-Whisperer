const GOOGLE_CLIENT_ID = process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID || "";
const GOOGLE_REDIRECT_URI =
  process.env.NEXT_PUBLIC_GOOGLE_REDIRECT_URI || "http://localhost:3000/auth/callback";

/**
 * Google OAuth 인증 URL 생성.
 * state는 CSRF 방지용 — sessionStorage에 저장 후 callback에서 검증.
 */
export function buildGoogleAuthUrl(): string {
  const state = crypto.randomUUID();
  sessionStorage.setItem("oauth_state", state);

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

export function getGoogleRedirectUri(): string {
  return GOOGLE_REDIRECT_URI;
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
