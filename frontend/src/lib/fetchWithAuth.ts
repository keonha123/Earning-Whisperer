import { useAuthStore } from "@/store/authStore";

/**
 * 인증이 필요한 API 호출 래퍼.
 * - AT 를 Authorization 헤더에 자동 첨부
 * - 401 응답 시 HttpOnly refresh 쿠키로 갱신 후 1회 재시도
 * - 갱신 실패 시 로그아웃 처리
 *
 * refresh_token 은 store 에 없으므로 store.refresh() 가 자체적으로 credentials:'include' 로 호출.
 */
export async function fetchWithAuth(
  input: RequestInfo | URL,
  init?: RequestInit
): Promise<Response> {
  const store = useAuthStore.getState();
  const at = store.accessToken;

  const headers = new Headers(init?.headers);
  if (at) headers.set("Authorization", `Bearer ${at}`);

  let res = await fetch(input, { ...init, headers });

  // 애초에 액세스 토큰이 없었다면 갱신할 것도 없다 — 비로그인 상태의 요청이다.
  // 백엔드가 인증 실패를 403 으로 돌려주던 동안에는 이 분기가 아예 안 돌아서 드러나지
  // 않았지만, 401 로 바로잡은 뒤로는 비로그인 요청마다 갱신 시도 → 실패 → 로그아웃이
  // 일어난다.
  if (res.status === 401 && at) {
    const newAt = await store.refresh();
    if (newAt) {
      headers.set("Authorization", `Bearer ${newAt}`);
      res = await fetch(input, { ...init, headers });
    }
  }

  return res;
}
