"use client";

interface AuthErrorBannerProps {
  message: string | null;
}

export default function AuthErrorBanner({ message }: AuthErrorBannerProps) {
  if (!message) return null;

  return (
    <div
      role="alert"
      aria-live="assertive"
      className="bg-red-950/60 border border-red-800 rounded-lg px-4 py-3"
    >
      <p className="text-sm text-red-400">{message}</p>
    </div>
  );
}
