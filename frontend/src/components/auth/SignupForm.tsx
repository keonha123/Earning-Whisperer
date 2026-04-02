"use client";

import { useSignupForm } from "@/hooks/useSignupForm";
import AuthInput from "./AuthInput";
import AuthSubmitButton from "./AuthSubmitButton";
import AuthErrorBanner from "./AuthErrorBanner";

interface SignupFormProps {
  onLoadingChange?: (loading: boolean) => void;
  onSwitchToLogin?: () => void;
}

export default function SignupForm({ onLoadingChange, onSwitchToLogin }: SignupFormProps) {
  const { fields, errors, apiError, isLoading, handleChange, handleSubmit } =
    useSignupForm({ onLoadingChange, onSwitchToLogin });

  return (
    <form id="signup-panel" role="tabpanel" onSubmit={handleSubmit} noValidate className="space-y-4">
      <AuthInput
        id="signup-email"
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
        id="signup-nickname"
        label="닉네임"
        type="text"
        value={fields.nickname}
        onChange={handleChange.nickname}
        placeholder="2~20자, 영문/한글/숫자/_"
        error={errors.nickname}
        disabled={isLoading}
        autoComplete="nickname"
      />
      <AuthInput
        id="signup-password"
        label="비밀번호"
        type="password"
        value={fields.password}
        onChange={handleChange.password}
        placeholder="영문+숫자 8자 이상"
        error={errors.password}
        disabled={isLoading}
        autoComplete="new-password"
      />
      <AuthErrorBanner message={apiError} />
      <AuthSubmitButton label="회원가입" isLoading={isLoading} />
    </form>
  );
}
