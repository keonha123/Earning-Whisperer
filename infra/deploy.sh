#!/usr/bin/env bash
# =============================================================================
# AWS 시연 서버 배포 스크립트
#
# DEPLOY.md 5장의 절차를 그대로 담았다. 손으로 할 때 틀리기 쉬운 지점이 몇 개
# 있어서 스크립트로 옮겼다.
#
#   - JAVA_HOME 이 JDK 17 이 아니면 Gradle toolchain 이 거부한다
#   - rsync 제외 목록에서 .env 를 빼먹으면 서버 환경변수가 로컬 값으로 덮인다
#     (DATABASE_URL 등이 127.0.0.1 기준이라 서비스가 뜨지 않는다)
#   - 서버는 평소 꺼져 있어서 배포 전에 켜야 한다
#   - 재시작만 하고 health 를 보지 않으면 실패를 배포 성공으로 착각한다
#
# 사용:
#   ./infra/deploy.sh ai-engine              코드 동기화 + 재시작 + 확인
#   ./infra/deploy.sh backend                빌드 + 교체 + 확인
#   ./infra/deploy.sh all                    둘 다
#   ./infra/deploy.sh ai-engine --start      꺼져 있으면 인스턴스를 켜고 배포
#   ./infra/deploy.sh all --start --stop     켜고 배포하고 다시 끈다
#   ./infra/deploy.sh backend --dry-run      무엇을 할지만 출력한다
#
# 사전 조건:
#   - SSH 공개키가 서버 authorized_keys 에 등록되어 있음 (DEPLOY.md 4장)
#   - --start / --stop 을 쓰려면 AWS CLI 와 EC2 Start/Stop 권한 (DEPLOY.md 4장)
#   - backend 배포는 JDK 17
#
# 이 스크립트가 하지 않는 것:
#   - 서버 환경변수(*.env) 변경. 시크릿이라 저장소에 없고 손으로 고친다 (5-3장)
#   - Qdrant 근거 데이터 반영. 스냅샷 절차가 따로 있다 (6장)
#   - 컨테이너 재생성. compose 는 서버에서 직접 다룬다 (4장)
# =============================================================================

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVER="${EW_DEPLOY_HOST:-ubuntu@43.200.26.70}"
INSTANCE_ID="${EW_INSTANCE_ID:-i-0e932167662542771}"
REGION="${AWS_REGION:-ap-northeast-2}"
REMOTE_ROOT="/opt/earning-whisperer"
JAR_NAME="earningwhisperer-backend-0.0.1-SNAPSHOT.jar"

# 백엔드가 기동을 마치기까지 실측 20~30초. 여유를 두고 5초 간격으로 확인한다.
HEALTH_RETRIES=18
HEALTH_INTERVAL=5
# 인스턴스를 켠 뒤 SSH 가 열리기까지 실측 40~60초.
SSH_RETRIES=15
SSH_INTERVAL=8

TARGET=""
DO_START=0
DO_STOP=0
DRY_RUN=0

log()  { printf '%s\n' "$*"; }
step() { printf '\n== %s ==\n' "$*"; }
die()  { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

run() {
  if [ "$DRY_RUN" = 1 ]; then
    printf '  (dry-run) %s\n' "$*"
    return 0
  fi
  "$@"
}

# macOS 는 shasum, Linux 는 sha256sum 을 쓴다.
sha256_of() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | cut -d' ' -f1
  else
    shasum -a 256 "$1" | cut -d' ' -f1
  fi
}

usage() {
  sed -n '3,30p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
  exit "${1:-0}"
}

# ---------------------------------------------------------------- 인자 파싱

while [ $# -gt 0 ]; do
  case "$1" in
    ai-engine|backend|all) TARGET="$1" ;;
    --start)   DO_START=1 ;;
    --stop)    DO_STOP=1 ;;
    --dry-run) DRY_RUN=1 ;;
    -h|--help) usage 0 ;;
    *) die "알 수 없는 인자: $1 (--help 로 사용법을 볼 수 있습니다)" ;;
  esac
  shift
done

[ -n "$TARGET" ] || usage 1

# ---------------------------------------------------------------- 사전 점검

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "$1 이 필요합니다. $2"
}

require_cmd ssh "설치 여부를 확인해 주세요."
[ "$TARGET" = backend ] && require_cmd scp "설치 여부를 확인해 주세요."
[ "$TARGET" = ai-engine ] || [ "$TARGET" = all ] && require_cmd rsync "macOS 는 기본 포함, Ubuntu 는 apt install rsync 입니다."

if [ "$DO_START" = 1 ] || [ "$DO_STOP" = 1 ]; then
  require_cmd aws "인스턴스 제어에 필요합니다. --start / --stop 없이 쓰거나 AWS CLI 를 설치해 주세요."
fi

# JDK 17 확인. Gradle toolchain 이 다른 버전을 거부하므로 빌드 전에 막는다.
check_jdk17() {
  local java_bin version
  if [ -n "${JAVA_HOME:-}" ]; then
    java_bin="$JAVA_HOME/bin/java"
  else
    java_bin="$(command -v java || true)"
  fi
  [ -x "$java_bin" ] || die "java 를 찾을 수 없습니다. JDK 17 을 설치하고 JAVA_HOME 을 지정해 주세요."
  version="$("$java_bin" -version 2>&1 | head -1)"
  case "$version" in
    *'"17'*|*'"17.'*) log "  JDK 확인: $version" ;;
    *)
      log "  현재: $version"
      log "  backend 빌드는 JDK 17 이 필요합니다. 아래처럼 지정하면 됩니다."
      log "    macOS: export JAVA_HOME=\$(/usr/libexec/java_home -v 17)"
      log "    Linux: export JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64"
      die "JDK 버전이 맞지 않습니다."
      ;;
  esac
}

# ---------------------------------------------------------------- 인스턴스

instance_state() {
  aws ec2 describe-instances --region "$REGION" --instance-ids "$INSTANCE_ID" \
    --query 'Reservations[0].Instances[0].State.Name' --output text
}

wait_for_ssh() {
  local i
  for i in $(seq 1 "$SSH_RETRIES"); do
    if ssh -o ConnectTimeout=8 -o BatchMode=yes "$SERVER" 'exit 0' 2>/dev/null; then
      log "  SSH 연결됨"
      return 0
    fi
    log "  SSH 대기 ($i/$SSH_RETRIES)"
    sleep "$SSH_INTERVAL"
  done
  die "SSH 에 연결할 수 없습니다. 공개키 등록 여부와 인스턴스 상태를 확인해 주세요."
}

ensure_running() {
  step "인스턴스 상태"
  # dry-run 은 서버가 꺼져 있어도 계획을 볼 수 있어야 한다. 연결을 확인하지 않는다.
  if [ "$DRY_RUN" = 1 ]; then
    if [ "$DO_START" = 1 ]; then
      log "  (dry-run) 중지 상태면 인스턴스를 시작합니다"
    else
      log "  (dry-run) 서버 연결을 확인합니다"
    fi
    return 0
  fi

  if [ "$DO_START" = 0 ]; then
    # AWS 권한이 없는 팀원도 쓸 수 있도록, 상태 조회 대신 SSH 로 확인한다.
    if ssh -o ConnectTimeout=8 -o BatchMode=yes "$SERVER" 'exit 0' 2>/dev/null; then
      log "  서버에 연결됩니다"
      return 0
    fi
    log "  서버에 연결되지 않습니다. 평소 꺼 두므로 대개 인스턴스가 중지 상태입니다."
    die "--start 를 붙이거나 인스턴스를 먼저 켜 주세요 (DEPLOY.md 4장)."
  fi

  local state
  state="$(instance_state)"
  log "  현재 상태: $state"
  case "$state" in
    running) ;;
    stopped)
      log "  인스턴스를 시작합니다"
      aws ec2 start-instances --region "$REGION" --instance-ids "$INSTANCE_ID" >/dev/null
      until [ "$(instance_state)" = running ]; do sleep 10; done
      log "  running"
      ;;
    *) die "시작할 수 없는 상태입니다: $state" ;;
  esac
  wait_for_ssh
}

stop_instance() {
  step "인스턴스 정지"
  run aws ec2 stop-instances --region "$REGION" --instance-ids "$INSTANCE_ID" >/dev/null
  log "  정지 요청을 보냈습니다"
}

# ---------------------------------------------------------------- health

# 서버 안에서 확인한다. 외부 노출 포트가 없어 로컬 curl 로는 볼 수 없다
# (Cloudflare Tunnel 경유, DEPLOY.md 2장).
wait_health() {
  local name="$1" url="$2" expect="$3" i body
  step "$name 확인"
  if [ "$DRY_RUN" = 1 ]; then
    log "  (dry-run) $url 에서 $expect 확인"
    return 0
  fi
  for i in $(seq 1 "$HEALTH_RETRIES"); do
    body="$(ssh -o ConnectTimeout=8 "$SERVER" "curl -s --max-time 5 '$url'" 2>/dev/null || true)"
    case "$body" in
      *"$expect"*) log "  $body"; return 0 ;;
    esac
    log "  대기 ($i/$HEALTH_RETRIES)"
    sleep "$HEALTH_INTERVAL"
  done
  log "  마지막 응답: ${body:-(없음)}"
  log "  로그를 보시면 원인을 알 수 있습니다:"
  log "    ssh $SERVER 'journalctl -u earning-whisperer-${name} -n 50 --no-pager'"
  die "$name 이 정상 응답하지 않습니다."
}

# ---------------------------------------------------------------- ai-engine

deploy_ai_engine() {
  step "ai-engine 동기화"
  # 제외 목록은 DEPLOY.md 5-2 와 같아야 한다. .env 를 빼먹으면 서버 환경변수가
  # 로컬 값으로 덮여 DATABASE_URL 등이 어긋나고 서비스가 뜨지 않는다.
  run rsync -az --delete \
    --exclude '.venv/' --exclude '__pycache__/' --exclude '*.pyc' \
    --exclude '.env' --exclude '.env.example' --exclude 'tests/' --exclude 'docs/' \
    --exclude '.pytest_cache/' --exclude 'data/yfinance_cache/' \
    "$REPO_ROOT/ai-engine/" "$SERVER:$REMOTE_ROOT/ai-engine/"
  log "  동기화 완료"

  # requirements.txt 가 바뀌었는지 서버 쪽 해시와 비교한다. 매번 pip install 하면
  # 배포가 몇 분 길어지고, 건너뛰면 새 의존성이 없어 기동에 실패한다.
  step "의존성 확인"
  if [ "$DRY_RUN" = 1 ]; then
    log "  (dry-run) requirements.txt 변경 여부를 보고 필요하면 pip install"
  else
    local local_sum remote_sum
    local_sum="$(sha256_of "$REPO_ROOT/ai-engine/requirements.txt")"
    remote_sum="$(ssh "$SERVER" "sha256sum $REMOTE_ROOT/ai-engine/requirements.txt 2>/dev/null | cut -d' ' -f1" || true)"
    if [ "$local_sum" = "$remote_sum" ]; then
      log "  requirements.txt 동일 — pip install 을 건너뜁니다"
    else
      log "  requirements.txt 가 달라 의존성을 갱신합니다"
      ssh "$SERVER" "$REMOTE_ROOT/ai-engine/.venv/bin/pip install -q -r $REMOTE_ROOT/ai-engine/requirements.txt"
      log "  갱신 완료"
    fi
  fi

  step "ai-engine 재시작"
  run ssh "$SERVER" 'sudo systemctl restart earning-whisperer-ai-engine'
  wait_health ai-engine 'http://127.0.0.1:8000/health' '"status":"ok"'
}

# ---------------------------------------------------------------- backend

deploy_backend() {
  step "JDK 확인"
  if [ "$DRY_RUN" = 1 ]; then
    log "  (dry-run) JDK 17 여부 확인"
  else
    check_jdk17
  fi

  step "backend 빌드"
  # 테스트는 CI(.github/workflows/test.yml)가 PR 에서 돌린다. 여기서 또 돌리면
  # 배포가 느려지기만 한다.
  # env -C 는 오래된 macOS 에 없어 서브셸로 디렉터리를 옮긴다.
  if [ "$DRY_RUN" = 1 ]; then
    log "  (dry-run) ./gradlew bootJar -x test"
  else
    ( cd "$REPO_ROOT/backend" && ./gradlew bootJar -x test --console=plain -q )
  fi
  local jar="$REPO_ROOT/backend/build/libs/$JAR_NAME"
  if [ "$DRY_RUN" = 0 ]; then
    [ -f "$jar" ] || die "jar 가 만들어지지 않았습니다: $jar"
    log "  $(du -h "$jar" | cut -f1) $JAR_NAME"
  fi

  step "backend 전송"
  run scp -q "$jar" "$SERVER:/tmp/backend.jar"

  step "backend 교체"
  # 실행 중인 jar 를 덮으면 JVM 이 클래스를 읽다 깨진다. 멈추고 바꾼다.
  # 이전 jar 는 남겨 두어 문제가 생기면 되돌릴 수 있게 한다.
  run ssh "$SERVER" "
    set -e
    sudo systemctl stop earning-whisperer-backend
    if [ -f $REMOTE_ROOT/backend.jar ]; then
      cp $REMOTE_ROOT/backend.jar $REMOTE_ROOT/backend.jar.prev
    fi
    mv /tmp/backend.jar $REMOTE_ROOT/backend.jar
    sudo systemctl start earning-whisperer-backend
  "
  log "  교체 완료 (이전 jar 는 backend.jar.prev 로 남겨 두었습니다)"
  wait_health backend 'http://127.0.0.1:8082/actuator/health' '"status":"UP"'
}

# ---------------------------------------------------------------- 실행

log "대상: $TARGET"
[ "$DRY_RUN" = 1 ] && log "dry-run — 실제로 바꾸지 않습니다"

ensure_running

case "$TARGET" in
  ai-engine) deploy_ai_engine ;;
  backend)   deploy_backend ;;
  all)       deploy_backend; deploy_ai_engine ;;
esac

[ "$DO_STOP" = 1 ] && stop_instance

step "완료"
log "배포 후 확인 항목은 DEPLOY.md 7장에 있습니다."
log "근거 데이터(Qdrant)는 이 스크립트가 다루지 않습니다 — 6장을 참고해 주세요."
