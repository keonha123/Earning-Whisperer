"use client";

function Spinner() {
  return (
    <svg
      className="w-4 h-4 animate-spin text-purple-300"
      xmlns="http://www.w3.org/2000/svg"
      fill="none"
      viewBox="0 0 24 24"
    >
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
    </svg>
  );
}

interface AuthSubmitButtonProps {
  label: string;
  isLoading: boolean;
  disabled?: boolean;
}

export default function AuthSubmitButton({ label, isLoading, disabled }: AuthSubmitButtonProps) {
  const isDisabled = disabled || isLoading;

  const bgClass = isLoading
    ? "bg-purple-700 cursor-not-allowed opacity-80"
    : isDisabled
    ? "bg-gray-700 text-gray-500 cursor-not-allowed"
    : "bg-purple-600 hover:bg-purple-500";

  return (
    <button
      type="submit"
      disabled={isDisabled}
      aria-busy={isLoading}
      aria-label={isLoading ? "처리 중" : label}
      className={`w-full py-2.5 rounded-lg text-sm font-semibold text-white transition-colors duration-150 inline-flex items-center justify-center gap-2 ${bgClass}`}
    >
      {isLoading ? (
        <>
          <Spinner />
          처리 중...
        </>
      ) : (
        label
      )}
    </button>
  );
}
