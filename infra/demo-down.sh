#!/usr/bin/env bash
# 로컬 시연 스택 종료. 컨테이너는 stop 만 하고 삭제하지 않는다(DB 데이터 보존).
set -uo pipefail

if command -v docker >/dev/null 2>&1; then
  DOCKER="docker"
elif command -v powershell.exe >/dev/null 2>&1; then
  DOCKER="powershell.exe -NoProfile -Command docker"
else
  DOCKER=""
fi

echo "터널 종료"
pkill -f "[c]loudflared tunnel --url http://localhost:8082" 2>/dev/null || true

echo "백엔드 종료"
pgrep -f "[e]arningwhisperer-backend" | xargs -r kill 2>/dev/null || true

if [ -n "$DOCKER" ]; then
  echo "컨테이너 정지 (삭제 아님)"
  $DOCKER stop ew-mysql ew-redis >/dev/null 2>&1 || true
fi

echo "완료"
