"use client";

interface ProfileHeaderProps {
  nickname: string;
  email: string;
  role: "FREE" | "PRO";
  createdAt: string;
}

export default function ProfileHeader({ nickname, email, role, createdAt }: ProfileHeaderProps) {
  const joined = new Date(createdAt).toLocaleDateString("ko-KR", {
    year: "numeric",
    month: "long",
    day: "numeric",
  });

  return (
    <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
      <div className="flex items-center gap-4">
        {/* 아바타 */}
        <div className="flex h-12 w-12 items-center justify-center rounded-xl border border-gray-700 bg-gray-800 font-mono text-lg font-bold text-accent-400">
          {nickname.charAt(0).toUpperCase()}
        </div>
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-lg font-bold text-white">{nickname}</h1>
            {role === "PRO" ? (
              <span className="rounded-md bg-accent-600 px-2 py-0.5 text-xs font-bold uppercase tracking-wider text-white">
                Pro
              </span>
            ) : (
              <span className="rounded-md border border-gray-600 px-2 py-0.5 text-xs font-medium uppercase tracking-wider text-gray-400">
                Free
              </span>
            )}
          </div>
          <p className="text-sm text-gray-500">{email}</p>
        </div>
      </div>
      <p className="font-mono text-xs text-gray-600">가입일 {joined}</p>
    </div>
  );
}
