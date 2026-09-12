#!/usr/bin/env bash
# =============================================================================
# 로컬 시연 스택 기동 스크립트
#
# VM 없이 개발 PC 에서 백엔드를 띄우고 Cloudflare quick tunnel 로 공개한다.
# 데스크탑 앱(trading-terminal)이 다른 PC 에서 붙어야 할 때 쓴다.
# 같은 PC 에서 앱을 돌린다면 터널 없이 localhost:8082 를 쓰는 편이 안정적이다.
#
# 사용:
#   ./infra/demo-up.sh
#
# 사전 조건:
#   - Docker Desktop 실행 중 (WSL 에서는 Windows 쪽 docker 를 호출)
#   - backend/.env 존재 (backend/.env.example 참고)
#   - cloudflared 설치 (~/.local/bin/cloudflared)
#   - backend/build/libs/*.jar 존재 (없으면 ./gradlew bootJar)
#
# 종료: ./infra/demo-down.sh
# =============================================================================

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$REPO_ROOT/backend"
LOG_DIR="${TMPDIR:-/tmp}"
CLOUDFLARED="${CLOUDFLARED_BIN:-$HOME/.local/bin/cloudflared}"

# WSL 에서는 Windows Docker Desktop 을 호출한다. 네이티브 리눅스면 docker 를 그대로 쓴다.
if command -v docker >/dev/null 2>&1; then
  DOCKER="docker"
elif command -v powershell.exe >/dev/null 2>&1; then
  DOCKER="powershell.exe -NoProfile -Command docker"
else
  echo "docker 를 찾을 수 없습니다. Docker Desktop 실행 여부를 확인하세요." >&2
  exit 1
fi

echo "== 1/4 인프라 컨테이너 =="
# 이미 만들어진 컨테이너가 있으면 재사용한다(데이터 보존). 없으면 새로 만든다.
if $DOCKER ps -a --format '{{.Names}}' | grep -qx ew-mysql; then
  $DOCKER start ew-mysql ew-redis >/dev/null
else
  $DOCKER run -d --name ew-redis -p 6379:6379 redis:latest >/dev/null
  $DOCKER run -d --name ew-mysql \
    -e MYSQL_ROOT_PASSWORD=root \
    -e MYSQL_DATABASE=earning_whisperer \
    -p 3306:3306 mysql:8.0 >/dev/null
fi
echo "   mysql / redis 기동됨"

echo "== 2/4 백엔드 =="
[ -f "$BACKEND_DIR/.env" ] || { echo "backend/.env 가 없습니다. .env.example 을 복사해 채우세요." >&2; exit 1; }
JAR=$(ls "$BACKEND_DIR"/build/libs/*.jar 2>/dev/null | head -1) \
  || { echo "jar 이 없습니다. cd backend && ./gradlew bootJar" >&2; exit 1; }

pgrep -f "[e]arningwhisperer-backend" >/dev/null && {
  echo "   이미 실행 중 — 재시작"
  pgrep -f "[e]arningwhisperer-backend" | xargs -r kill
  sleep 3
}

# .env 의 값은 따옴표로 감싸져 있어야 한다 — DB_URL 의 '&' 가 셸 연산자로 해석되는 것을 막는다.
set -a; . "$BACKEND_DIR/.env"; set +a
nohup java -jar "$JAR" > "$LOG_DIR/ew-backend.log" 2>&1 &

echo -n "   기동 대기"
until curl -sf -o /dev/null http://localhost:8082/actuator/health 2>/dev/null; do
  echo -n "."; sleep 3
done
echo " OK"

echo "== 3/4 Cloudflare 터널 =="
[ -x "$CLOUDFLARED" ] || { echo "cloudflared 가 없습니다: $CLOUDFLARED" >&2; exit 1; }
pkill -f "[c]loudflared tunnel --url http://localhost:8082" 2>/dev/null || true
nohup "$CLOUDFLARED" tunnel --url http://localhost:8082 > "$LOG_DIR/ew-tunnel.log" 2>&1 &

echo -n "   URL 발급 대기"
TUNNEL_URL=""
for _ in $(seq 1 20); do
  TUNNEL_URL=$(grep -oE "https://[a-z0-9-]+\.trycloudflare\.com" "$LOG_DIR/ew-tunnel.log" 2>/dev/null | head -1 || true)
  [ -n "$TUNNEL_URL" ] && break
  echo -n "."; sleep 3
done
[ -n "$TUNNEL_URL" ] || { echo " 실패 — $LOG_DIR/ew-tunnel.log 확인" >&2; exit 1; }
echo " OK"

echo "== 4/4 확인 =="
curl -sf "$TUNNEL_URL/actuator/health" && echo

cat <<EOF

─────────────────────────────────────────────────────────────
백엔드 공개 URL:  $TUNNEL_URL

데스크탑 앱을 다른 PC 에서 실행한다면 trading-terminal/.env.local 에:

    BACKEND_URL=$TUNNEL_URL

같은 PC 에서 실행한다면 BACKEND_URL 을 지우고 기본값(localhost:8082)을 쓰는
편이 안정적이다.

주의: quick tunnel 은 일회용이다. 이 스크립트를 다시 돌리면 URL 이 바뀐다.

로그:  $LOG_DIR/ew-backend.log
       $LOG_DIR/ew-tunnel.log
─────────────────────────────────────────────────────────────
EOF
