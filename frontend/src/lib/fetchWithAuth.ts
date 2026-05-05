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

  if (res.status === 401) {
    const newAt = await store.refresh();
    if (newAt) {
      headers.set("Authorization", `Bearer ${newAt}`);
      res = await fetch(input, { ...init, headers });
    }
  }

  return res;
}
