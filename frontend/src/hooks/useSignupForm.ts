"use client";

import { useState, FormEvent, useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import { useAuthStore } from "@/store/authStore";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8082";
const EMAIL_REGEX = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const NICKNAME_REGEX = /^[a-zA-Z0-9가-힣_]+$/;
const PASSWORD_COMPLEXITY = /(?=.*[a-zA-Z])(?=.*\d)/;

function mapApiError(status: number): string {
  switch (status) {
    case 409: return "이미 사용 중인 이메일입니다.";
    case 422: return "입력값을 확인해주세요.";
    default:  return "오류가 발생했습니다. 다시 시도해주세요.";
  }
}

interface FormErrors {
  email?: string;
  nickname?: string;
  password?: string;
}

interface UseSignupFormOptions {
  onLoadingChange?: (loading: boolean) => void;
  onSwitchToLogin?: () => void;
}

export function useSignupForm({ onLoadingChange, onSwitchToLogin }: UseSignupFormOptions = {}) {
  const router = useRouter();
  const { setToken } = useAuthStore();
  const abortRef = useRef<AbortController | null>(null);

  const [email, setEmail] = useState("");
  const [nickname, setNickname] = useState("");
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

    if (!nickname) errs.nickname = "닉네임을 입력해주세요.";
    else if (nickname.length < 2) errs.nickname = "닉네임은 2자 이상 입력해주세요.";
    else if (nickname.length > 20) errs.nickname = "닉네임은 20자 이하로 입력해주세요.";
    else if (!NICKNAME_REGEX.test(nickname)) errs.nickname = "닉네임에 사용할 수 없는 문자가 포함되어 있습니다.";

    if (!password) errs.password = "비밀번호를 입력해주세요.";
    else if (password.length < 8) errs.password = "비밀번호는 8자 이상이어야 합니다.";
    else if (password.length > 32) errs.password = "비밀번호는 32자 이하여야 합니다.";
    else if (!PASSWORD_COMPLEXITY.test(password)) errs.password = "비밀번호는 영문과 숫자를 모두 포함해야 합니다.";

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
    const signal = abortRef.current.signal;

    setLoading(true);
    setApiError(null);
    setErrors({});

    try {
      // 1. 회원가입
      const signupRes = await fetch(`${API_BASE}/api/v1/auth/signup`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password, nickname }),
        signal,
      });

      if (!signupRes.ok) {
        const body = await signupRes.json().catch(() => ({}));
        setApiError(body.error ?? mapApiError(signupRes.status));
        return;
      }

      // 2. 회원가입 성공 후 자동 로그인
      const loginRes = await fetch(`${API_BASE}/api/v1/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
        signal,
      });

      if (!loginRes.ok) {
        // 자동 로그인 실패 시 로그인 탭으로 전환
        setApiError("회원가입 완료! 로그인해주세요.");
        onSwitchToLogin?.();
        return;
      }

      const data = await loginRes.json();
      setToken(data.accessToken);
      router.push("/download");
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
    fields: { email, nickname, password },
    errors,
    apiError,
    isLoading,
    handleChange: { email: setEmail, nickname: setNickname, password: setPassword },
    handleSubmit,
    resetErrors,
  };
}
