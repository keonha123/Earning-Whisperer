interface PasswordToggleProps {
  visible: boolean
  onToggle: () => void
}

/**
 * PasswordToggle — 비밀번호 input 우측에 붙는 eye / eye-off 아이콘 버튼.
 */
export default function PasswordToggle({ visible, onToggle }: PasswordToggleProps) {
  return (
    <button
      type="button"
      onClick={onToggle}
      aria-label={visible ? '비밀번호 숨기기' : '비밀번호 보기'}
      className="text-text-tertiary hover:text-text-secondary flex-none"
    >
      {visible ? (
        <svg
          width="14"
          height="14"
          viewBox="0 0 14 14"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
        >
          <path d="M2.5 2.5l9 9" />
          <path d="M5.6 5.6a1.7 1.7 0 002.4 2.4" />
          <path d="M3.5 4.5C2.2 5.5 1.5 7 1.5 7s2 4 5.5 4c1 0 1.9-.3 2.7-.7M11.2 9.2c.8-.7 1.3-1.6 1.3-2.2 0 0-2-4-5.5-4-.5 0-1 .1-1.5.2" />
        </svg>
      ) : (
        <svg
          width="14"
          height="14"
          viewBox="0 0 14 14"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
        >
          <path d="M1.5 7s2-4 5.5-4 5.5 4 5.5 4-2 4-5.5 4S1.5 7 1.5 7z" />
          <circle cx="7" cy="7" r="1.7" />
        </svg>
      )}
    </button>
  )
}
