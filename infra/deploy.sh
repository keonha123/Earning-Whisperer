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
die()  {
  printf 'ERROR: %s\n' "$*" >&2
  # 실패하면 --stop 에 도달하지 않아 인스턴스가 켜진 채 남는다. 자동으로 끄면 원인을
  # 볼 수 없으니 명령만 알려 준다.
  if [ "${DO_STOP:-0}" = 1 ]; then
    printf '인스턴스는 켜진 채로 남겨 두었습니다. 확인이 끝나면 정지해 주세요:\n' >&2
    printf '  aws ec2 stop-instances --region %s --instance-ids %s\n' "$REGION" "$INSTANCE_ID" >&2
  fi
  exit 1
}

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
    ai-engine|backend|all)
      [ -z "$TARGET" ] || die "대상은 하나만 지정해 주세요. 둘 다 배포하려면 all 을 쓰시면 됩니다."
      TARGET="$1"
      ;;
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
    if ssh -o ConnectTimeout=8 -o BatchMode=yes -- "$SERVER" 'exit 0' 2>/dev/null; then
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
    if ssh -o ConnectTimeout=8 -o BatchMode=yes -- "$SERVER" 'exit 0' 2>/dev/null; then
      log "  서버에 연결됩니다"
      return 0
    fi
    log "  서버에 연결되지 않습니다. 평소 꺼 두므로 대개 인스턴스가 중지 상태입니다."
    die "--start 를 붙이거나 인스턴스를 먼저 켜 주세요 (DEPLOY.md 4장)."
  fi

  # 두 값이 독립 환경변수라 한쪽만 덮으면 짝이 어긋난다. EW_DEPLOY_HOST 만 바꿔 두고
  # --stop 을 쓰면 다른 서버에 배포한 뒤 공용 인스턴스를 정지시킨다. 먼저 대조한다.
  local public_ip host_only
  public_ip="$(aws ec2 describe-instances --region "$REGION" --instance-ids "$INSTANCE_ID" \
    --query 'Reservations[0].Instances[0].PublicIpAddress' --output text 2>/dev/null || true)"
  host_only="${SERVER#*@}"
  if [ -n "$public_ip" ] && [ "$public_ip" != "None" ] && [ "$public_ip" != "$host_only" ]; then
    log "  배포 대상: $host_only"
    log "  인스턴스 IP: $public_ip ($INSTANCE_ID)"
    die "배포 대상과 인스턴스가 다릅니다. EW_DEPLOY_HOST 와 EW_INSTANCE_ID 를 맞춰 주세요."
  fi

  local state
  state="$(instance_state)"
  log "  현재 상태: $state"
  case "$state" in
    running) ;;
    stopped)
      log "  인스턴스를 시작합니다"
      aws ec2 start-instances --region "$REGION" --instance-ids "$INSTANCE_ID" >/dev/null
      local i
      for i in $(seq 1 18); do
        state="$(instance_state || true)"
        [ "$state" = running ] && break
        log "  대기 ($i/18) — $state"
        sleep 10
      done
      # 상한이 없으면 자격증명 만료나 네트워크 단절에서 아무 메시지 없이 영원히 돈다.
      [ "$state" = running ] || die "인스턴스가 running 이 되지 않았습니다 (마지막 상태: ${state:-조회 실패})"
      log "  running"
      ;;
    *) die "시작할 수 없는 상태입니다: $state" ;;
  esac
  wait_for_ssh
}

stop_instance() {
  step "인스턴스 정지"
  # run 호출에 리다이렉션을 붙이면 dry-run 출력까지 함께 버려진다. 안에서 처리한다.
  if [ "$DRY_RUN" = 1 ]; then
    log "  (dry-run) 인스턴스를 정지합니다"
    return 0
  fi
  aws ec2 stop-instances --region "$REGION" --instance-ids "$INSTANCE_ID" >/dev/null
  log "  정지 요청을 보냈습니다"
}

# ---------------------------------------------------------------- 동시 실행

# 두 사람이 같이 돌리면 서로의 rsync · pip · jar 교체가 겹쳐 어느 커밋도 아닌 상태가
# 남는다. 서버 쪽 락 하나로 막는다. 락은 SSH 세션이 끝나면 풀린다.
acquire_lock() {
  step "배포 잠금"
  if [ "$DRY_RUN" = 1 ]; then
    log "  (dry-run) 서버 락을 확인합니다"
    return 0
  fi
  if ssh -o BatchMode=yes -- "$SERVER" 'flock -n /tmp/ew-deploy.lock -c "echo ok"' >/dev/null 2>&1; then
    log "  다른 배포가 진행 중이지 않습니다"
  else
    die "다른 배포가 진행 중입니다. 끝난 뒤에 다시 시도해 주세요."
  fi
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
  local rc
  for i in $(seq 1 "$HEALTH_RETRIES"); do
    set +e
    body="$(ssh -o ConnectTimeout=8 -o BatchMode=yes -- "$SERVER" "curl -s --max-time 5 '$url'" 2>/dev/null)"
    rc=$?
    set -e
    case "$body" in
      *"$expect"*) log "  $body"; return 0 ;;
    esac
    # ssh 자체가 실패한 것(255)과 서비스가 아직 안 뜬 것을 구분한다. 구분하지 않으면
    # 인스턴스가 정지됐거나 키가 안 맞는 경우에도 "서비스 로그를 보라" 고 안내한다.
    if [ "$rc" = 255 ]; then
      log "  SSH 연결 실패 ($i/$HEALTH_RETRIES) — 인스턴스 상태와 키 등록을 확인해 주세요"
    else
      log "  대기 ($i/$HEALTH_RETRIES)"
    fi
    sleep "$HEALTH_INTERVAL"
  done
  log "  마지막 응답: ${body:-(없음)}"
  if [ "$rc" = 255 ]; then
    die "서버에 연결할 수 없습니다. 인스턴스가 켜져 있는지 확인해 주세요."
  fi
  log "  로그를 보시면 원인을 알 수 있습니다:"
  log "    ssh $SERVER 'journalctl -u earning-whisperer-${name} -n 50 --no-pager'"
  die "$name 이 정상 응답하지 않습니다."
}

# ---------------------------------------------------------------- ai-engine

deploy_ai_engine() {
  # 해시 비교는 rsync 보다 먼저 해야 한다. rsync 가 requirements.txt 까지 동기화하므로
  # 뒤에 비교하면 항상 같아 보이고 pip install 이 한 번도 돌지 않는다.
  step "의존성 변경 확인"
  local need_pip=0
  if [ "$DRY_RUN" = 1 ]; then
    log "  (dry-run) 서버 쪽 requirements.txt 와 해시를 비교합니다"
  else
    local local_sum remote_sum
    local_sum="$(sha256_of "$REPO_ROOT/ai-engine/requirements.txt")"
    remote_sum="$(ssh -o BatchMode=yes -- "$SERVER" "sha256sum $REMOTE_ROOT/ai-engine/requirements.txt 2>/dev/null | cut -d' ' -f1" || true)"
    if [ "$local_sum" = "$remote_sum" ]; then
      log "  동일 — pip install 을 건너뜁니다"
    else
      log "  달라졌습니다 — 동기화 후 의존성을 갱신합니다"
      need_pip=1
    fi
  fi

  step "ai-engine 동기화"
  # 제외 목록은 DEPLOY.md 5-2 와 같아야 한다. .env 를 빼먹으면 서버 환경변수가
  # 로컬 값으로 덮여 DATABASE_URL 등이 어긋나고 서비스가 뜨지 않는다.
  # data/ 는 삭제 대상에서 뺀다. 저장소에 없는 서버 산출물(캐시·다운로드·중간 결과)이
  # 그 아래에 생기는데, --delete 가 지우면 로컬에 없으니 되돌릴 수 없다. 임베딩처럼
  # 재생성에 하루 요청 한도를 쓰는 것도 있다. 파일 갱신은 그대로 이루어진다.
  run rsync -az --delete \
    --filter 'protect data/' \
    --exclude '.venv/' --exclude '__pycache__/' --exclude '*.pyc' \
    --exclude '.env' --exclude '.env.example' --exclude 'tests/' --exclude 'docs/' \
    --exclude '.pytest_cache/' --exclude 'data/yfinance_cache/' \
    -- "$REPO_ROOT/ai-engine/" "$SERVER:$REMOTE_ROOT/ai-engine/"
  log "  동기화 완료"

  if [ "$need_pip" = 1 ]; then
    step "의존성 갱신"
    run ssh -o BatchMode=yes -- "$SERVER" "$REMOTE_ROOT/ai-engine/.venv/bin/pip install -q -r $REMOTE_ROOT/ai-engine/requirements.txt"
    log "  갱신 완료"
  fi

  step "ai-engine 재시작"
  run ssh -o BatchMode=yes -- "$SERVER" 'sudo systemctl restart earning-whisperer-ai-engine'
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
  # /tmp 의 고정 이름을 쓰면 두 사람이 겹칠 때 남의 jar 를 설치하게 된다. 홈 디렉터리에
  # 자기 이름으로 받는다.
  local staged="backend.jar.staged.$$"
  run scp -q -- "$jar" "$SERVER:~/$staged"

  step "backend 교체"
  # 실행 중인 jar 를 덮으면 JVM 이 클래스를 읽다 깨진다. 멈추고 바꾼다.
  # 실패하면 이전 jar 로 되돌리고 서비스를 다시 띄운다 — 멈춘 채로 끝나지 않게 한다.
  # 백업은 타임스탬프로 남긴다. 고정 이름이면 깨진 jar 를 두 번 배포할 때
  # 되돌릴 대상이 사라진다.
  run ssh -o BatchMode=yes -- "$SERVER" "
    set -e
    BACKUP=$REMOTE_ROOT/backend.jar.\$(date +%Y%m%d-%H%M%S)
    rollback() {
      echo '  교체 실패 — 이전 jar 로 되돌립니다'
      if [ -f \"\$BACKUP\" ]; then cp -f \"\$BACKUP\" $REMOTE_ROOT/backend.jar; fi
      sudo systemctl start earning-whisperer-backend || true
    }
    trap rollback ERR
    if [ -f $REMOTE_ROOT/backend.jar ]; then cp $REMOTE_ROOT/backend.jar \"\$BACKUP\"; fi
    sudo systemctl stop earning-whisperer-backend
    mv ~/$staged $REMOTE_ROOT/backend.jar
    sudo systemctl start earning-whisperer-backend
    trap - ERR
    # 백업은 최근 3개만 남긴다
    ls -1t $REMOTE_ROOT/backend.jar.20* 2>/dev/null | tail -n +4 | xargs -r rm -f
    echo \"  백업: \$BACKUP\"
  "
  wait_health backend 'http://127.0.0.1:8082/actuator/health' '"status":"UP"'
}

# ---------------------------------------------------------------- 실행

log "대상: $TARGET"
[ "$DRY_RUN" = 1 ] && log "dry-run — 실제로 바꾸지 않습니다"

ensure_running
acquire_lock

case "$TARGET" in
  ai-engine) deploy_ai_engine ;;
  backend)   deploy_backend ;;
  # 백엔드가 ai-engine 을 호출하는 방향이라 ai-engine 을 먼저 올린다. 순서를 뒤집으면
  # 새 백엔드가 옛 ai-engine 과 맞지 않아 health 에서 죽고, 어느 커밋에도 없는 조합이 남는다.
  all)       deploy_ai_engine; deploy_backend ;;
esac

[ "$DO_STOP" = 1 ] && stop_instance

step "완료"
log "배포 후 확인 항목은 DEPLOY.md 7장에 있습니다."
log "근거 데이터(Qdrant)는 이 스크립트가 다루지 않습니다 — 6장을 참고해 주세요."
