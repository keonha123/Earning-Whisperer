"use client";

import { useState, FormEvent, useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import { useAuthStore } from "@/store/authStore";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8082";
const EMAIL_REGEX = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

function mapApiError(status: number): string {
  switch (status) {
    case 401: return "이메일 또는 비밀번호가 올바르지 않습니다.";
    case 409: return "이미 사용 중인 이메일입니다.";
    case 422: return "입력값을 확인해주세요.";
    default:  return "오류가 발생했습니다. 다시 시도해주세요.";
  }
}

interface FormErrors {
  email?: string;
  password?: string;
}

interface UseLoginFormOptions {
  onLoadingChange?: (loading: boolean) => void;
}

export function useLoginForm({ onLoadingChange }: UseLoginFormOptions = {}) {
  const router = useRouter();
  const { setTokens } = useAuthStore();
  const abortRef = useRef<AbortController | null>(null);

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [errors, setErrors] = useState<FormErrors>({});
  const [apiError, setApiError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  // unmount 시 진행 중인 요청 취소
  useEffect(() => {
    return () => {
      abortRef.current?.abort();
    };
  }, []);

  function setLoading(value: boolean) {
    setIsLoading(value);
    onLoadingChange?.(value);
  }

  function validate(): FormErrors {
    const errs: FormErrors = {};
    if (!email) errs.email = "이메일을 입력해주세요.";
    else if (!EMAIL_REGEX.test(email)) errs.email = "유효한 이메일 형식이 아닙니다.";
    if (!password) errs.password = "비밀번호를 입력해주세요.";
    return errs;
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const errs = validate();
    if (Object.keys(errs).length > 0) {
      setErrors(errs);
      return;
    }

    abortRef.current?.abort();
    abortRef.current = new AbortController();

    setLoading(true);
    setApiError(null);
    setErrors({});

    try {
      const res = await fetch(`${API_BASE}/api/v1/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
        credentials: "include",
        signal: abortRef.current.signal,
      });

      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        setApiError(body.error ?? mapApiError(res.status));
        return;
      }

      const data = await res.json();
      setTokens(data.access_token, data.refresh_token);
      router.push("/");
    } catch (err) {
      if ((err as Error).name === "AbortError") return;
      setApiError("서버에 연결할 수 없습니다. 잠시 후 다시 시도해주세요.");
    } finally {
      setLoading(false);
    }
  }

  function resetErrors() {
    setErrors({});
    setApiError(null);
  }

  return {
    fields: { email, password },
    errors,
    apiError,
    isLoading,
    handleChange: { email: setEmail, password: setPassword },
    handleSubmit,
    resetErrors,
  };
}
