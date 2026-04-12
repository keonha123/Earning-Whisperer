"use client";

import { buildKakaoAuthUrl } from "@/lib/oauthConfig";

export default function KakaoLoginButton() {
  function handleClick() {
    window.location.href = buildKakaoAuthUrl();
  }

  return (
    <button
      type="button"
      onClick={handleClick}
      className="w-full flex items-center justify-center gap-3 py-2.5 px-4 rounded-lg bg-[#FEE500] hover:bg-[#FDD800] transition-colors text-sm font-medium text-[#191919]"
    >
      <svg className="w-5 h-5" viewBox="0 0 24 24">
        <path
          d="M12 3C6.477 3 2 6.463 2 10.691c0 2.726 1.8 5.117 4.508 6.47-.199.744-.721 2.695-.826 3.112-.13.52.19.513.4.373.165-.11 2.627-1.787 3.695-2.51.712.105 1.45.162 2.223.162 5.523 0 10-3.463 10-7.607C22 6.463 17.523 3 12 3z"
          fill="#191919"
        />
      </svg>
      카카오로 계속하기
    </button>
  );
}
