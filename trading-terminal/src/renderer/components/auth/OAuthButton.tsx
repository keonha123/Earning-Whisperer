type OAuthProvider = 'google' | 'kakao'

interface OAuthButtonProps {
  provider: OAuthProvider
  onClick: () => void
  disabled?: boolean
  loading?: boolean
}

/**
 * OAuthButton — Google / Kakao 소셜 로그인 버튼.
 * provider 별 색상·아이콘은 디자인 캔버스 기준으로 인라인 hex 사용
 * (회사 브랜드 색은 디자인 토큰화 대상이 아님).
 *
 * loading=true 시 라벨이 "인증 중..." 으로 변경되며, disabled=true 면 클릭 차단.
 */
export default function OAuthButton({ provider, onClick, disabled, loading }: OAuthButtonProps) {
  const isDisabled = disabled || loading
  if (provider === 'google') {
    return (
      <button
        type="button"
        onClick={onClick}
        disabled={isDisabled}
        aria-busy={loading || undefined}
        className="w-full h-9 rounded-md inline-flex items-center justify-center gap-2 text-sm font-medium whitespace-nowrap transition-[filter] hover:brightness-95 disabled:opacity-60 disabled:cursor-not-allowed"
        style={{ background: '#ffffff', color: '#1f2937' }}
      >
        <svg width="15" height="15" viewBox="0 0 18 18" className="flex-none">
          <path
            fill="#4285F4"
            d="M17.64 9.2c0-.64-.06-1.25-.17-1.84H9v3.48h4.84a4.14 4.14 0 01-1.8 2.72v2.26h2.92c1.7-1.57 2.68-3.88 2.68-6.62z"
          />
          <path
            fill="#34A853"
            d="M9 18c2.43 0 4.47-.8 5.96-2.18l-2.92-2.26c-.8.54-1.83.86-3.04.86-2.34 0-4.32-1.58-5.03-3.71H.92v2.33A9 9 0 009 18z"
          />
          <path
            fill="#FBBC05"
            d="M3.97 10.71A5.4 5.4 0 013.68 9c0-.59.1-1.17.29-1.71V4.96H.92A9 9 0 000 9c0 1.45.35 2.82.96 4.04l3.01-2.33z"
          />
          <path
            fill="#EA4335"
            d="M9 3.58c1.32 0 2.51.45 3.44 1.35l2.58-2.58C13.46.89 11.43 0 9 0A9 9 0 00.92 4.96l3.05 2.33C4.68 5.16 6.66 3.58 9 3.58z"
          />
        </svg>
        {loading ? '인증 중...' : 'Google로 계속하기'}
      </button>
    )
  }

  return (
    <button
      type="button"
      onClick={onClick}
      disabled={isDisabled}
      aria-busy={loading || undefined}
      className="w-full h-9 rounded-md inline-flex items-center justify-center gap-2 text-sm font-medium whitespace-nowrap transition-[filter] hover:brightness-95 disabled:opacity-60 disabled:cursor-not-allowed"
      style={{ background: '#FEE500', color: '#000000' }}
    >
      <svg width="15" height="15" viewBox="0 0 16 16" className="flex-none">
        <path
          fill="#000"
          d="M8 2C4.14 2 1 4.54 1 7.68c0 2.03 1.32 3.81 3.33 4.84l-.7 2.64c-.07.27.22.48.46.34l3.1-2.08c.26.03.54.04.81.04 3.86 0 7-2.54 7-5.68C15 4.54 11.86 2 8 2z"
        />
      </svg>
      {loading ? '인증 중...' : '카카오로 계속하기'}
    </button>
  )
}
