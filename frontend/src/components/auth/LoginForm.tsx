"use client";

import { useLoginForm } from "@/hooks/useLoginForm";
import AuthInput from "./AuthInput";
import AuthSubmitButton from "./AuthSubmitButton";
import AuthErrorBanner from "./AuthErrorBanner";

interface LoginFormProps {
  onLoadingChange?: (loading: boolean) => void;
}

export default function LoginForm({ onLoadingChange }: LoginFormProps) {
  const { fields, errors, apiError, isLoading, handleChange, handleSubmit } =
    useLoginForm({ onLoadingChange });

  return (
    <form id="login-panel" role="tabpanel" onSubmit={handleSubmit} noValidate className="space-y-4">
      <AuthInput
        id="login-email"
        label="이메일"
        type="email"
        value={fields.email}
        onChange={handleChange.email}
        placeholder="you@example.com"
        error={errors.email}
        disabled={isLoading}
        autoComplete="email"
      />
      <AuthInput
        id="login-password"
        label="비밀번호"
        type="password"
        value={fields.password}
        onChange={handleChange.password}
        placeholder="비밀번호 입력"
        error={errors.password}
        disabled={isLoading}
        autoComplete="current-password"
      />
      <AuthErrorBanner message={apiError} />
      <AuthSubmitButton label="로그인" isLoading={isLoading} />
    </form>
  );
}
