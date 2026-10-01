#!/usr/bin/env bash
set -euo pipefail

PROBE_ONLY=false
if [[ "${1:-}" == "--probe-only" ]]; then
  PROBE_ONLY=true
  shift
fi

if [[ $# -lt 2 ]]; then
  echo "usage: $0 [--probe-only] TICKER IR_URL [take.py args...]" >&2
  exit 2
fi

TICKER="$1"
IR_URL="$2"
shift 2

CALL_ID="${CALL_ID:-${TICKER}-webcast-audio}"
PULSE_SINK_NAME="${WEBCAST_PULSE_SINK:-ew_webcast}"
PULSE_MONITOR="${STT_INPUT_SOURCE:-${PULSE_SINK_NAME}.monitor}"
WEBCAST_HOLD_SECONDS="${WEBCAST_HOLD_SECONDS:-3600}"
WEBCAST_WARMUP_SECONDS="${WEBCAST_AUDIO_WARMUP_SECONDS:-12}"
AUDIO_WAIT_SECONDS="${DATE_STREAM_AUDIO_WAIT_SECONDS:-90}"
AUDIO_PROBE_SECONDS="${DATE_STREAM_AUDIO_PROBE_SECONDS:-3}"
AUDIO_MIN_DB="${DATE_STREAM_AUDIO_MIN_DB:--55}"
AUDIO_PROBE_INTERVAL_SECONDS="${DATE_STREAM_AUDIO_PROBE_INTERVAL_SECONDS:-1}"
SUCCESS_HOLD_SECONDS="${WEBCAST_SUCCESS_HOLD_SECONDS:-0}"
RECIPE_CONTEXT_PATH="${WEBCAST_RECIPE_CONTEXT_PATH:-/tmp/ew-webcast-recipe.json}"
MANUAL_READY_FILE="${WEBCAST_MANUAL_READY_FILE:-}"
MANUAL_READY_TIMEOUT_SECONDS="${WEBCAST_MANUAL_READY_TIMEOUT_SECONDS:-900}"
PLAYBACK_READY_FILE="${WEBCAST_PLAYBACK_READY_FILE:-/tmp/ew-webcast-playback-ready}"
TARGET_IDENTITY_READY_FILE="${WEBCAST_TARGET_IDENTITY_READY_FILE:-/tmp/ew-webcast-target-identity-ready}"
ACTIVE_PLAYER_URL_FILE="${WEBCAST_ACTIVE_PLAYER_URL_FILE:-/tmp/ew-webcast-active-url}"
LAST_TARGET_URL_FILE="${WEBCAST_LAST_TARGET_URL_FILE:-/tmp/ew-webcast-last-target-url}"
MEDIA_CANDIDATES_FILE="${WEBCAST_MEDIA_CANDIDATES_FILE:-/tmp/ew-webcast-media-candidates.json}"
PROBE_MEDIA_CANDIDATES_FILE="${WEBCAST_PROBE_MEDIA_CANDIDATES_FILE:-}"
HUMAN_LOOP_ENABLED="${WEBCAST_HUMAN_LOOP_ENABLED:-false}"
HUMAN_RESUME_FILE="${WEBCAST_HUMAN_RESUME_FILE:-}"
HUMAN_HANDOFF_FILE="${WEBCAST_HUMAN_HANDOFF_FILE:-}"
HUMAN_ACTION_LOG_FILE="${WEBCAST_HUMAN_ACTION_LOG_FILE:-}"
HUMAN_HANDOFF_TIMEOUT_SECONDS="${WEBCAST_HUMAN_HANDOFF_TIMEOUT_SECONDS:-900}"
PLAYBACK_READY_TIMEOUT_SECONDS="${WEBCAST_PLAYBACK_READY_TIMEOUT_SECONDS:-180}"
MEDIA_FALLBACK_MAX_RESTARTS="${WEBCAST_MEDIA_FALLBACK_MAX_RESTARTS:-2}"
# A live YouTube stream must start at the current playback point. Historical
# replay callers can still set a positive seek explicitly when desired.
YOUTUBE_FALLBACK_SEEK_SECONDS="${WEBCAST_YOUTUBE_FALLBACK_SEEK_SECONDS:-0}"
WEBCAST_VNC_ENABLED="${WEBCAST_VNC_ENABLED:-false}"
WEBCAST_VNC_DISPLAY="${WEBCAST_VNC_DISPLAY:-:99}"
WEBCAST_VNC_RFB_PORT="${WEBCAST_VNC_RFB_PORT:-5900}"
WEBCAST_VNC_WEB_PORT="${WEBCAST_VNC_WEB_PORT:-6080}"
WEBCAST_VNC_RESOLUTION="${WEBCAST_VNC_RESOLUTION:-1280x900x24}"
WEBCAST_CAPTURE_LOG_FILE="${WEBCAST_CAPTURE_LOG_FILE:-}"
STT_AUDIO_PREFLIGHT_SECONDS="${STT_AUDIO_PREFLIGHT_SECONDS:-12}"
STT_AUDIO_PREFLIGHT_FILE="${STT_AUDIO_PREFLIGHT_FILE:-/tmp/${PULSE_SINK_NAME}-preflight.wav}"
STT_AUDIO_PREFLIGHT_REPORT_FILE="${STT_AUDIO_PREFLIGHT_REPORT_FILE:-/tmp/${PULSE_SINK_NAME}-preflight.json}"
WEBCAST_SPEECH_PREFLIGHT_ENABLED="${WEBCAST_SPEECH_PREFLIGHT_ENABLED:-true}"
WEBCAST_REQUIRE_LIVE_TARGET_CONFIRMATION="${WEBCAST_REQUIRE_LIVE_TARGET_CONFIRMATION:-true}"
STT_AUDIO_PREFLIGHT_MODEL_NAME="${STT_AUDIO_PREFLIGHT_MODEL_NAME:-tiny}"
PROBE_PROMOTION_ENABLED="${WEBCAST_PROBE_PROMOTION_ENABLED:-false}"
AUDIO_READY_FILE="${WEBCAST_AUDIO_READY_FILE:-/tmp/${PULSE_SINK_NAME}-audio-ready}"
PROBE_PROMOTE_FILE="${WEBCAST_PROBE_PROMOTE_FILE:-/tmp/${PULSE_SINK_NAME}-promote}"
PROBE_ABORT_FILE="${WEBCAST_PROBE_ABORT_FILE:-/tmp/${PULSE_SINK_NAME}-abort}"
PROBE_PROMOTION_TIMEOUT_SECONDS="${WEBCAST_PROBE_PROMOTION_TIMEOUT_SECONDS:-90}"
MEDIA_FALLBACK_LOG="${WEBCAST_MEDIA_FALLBACK_LOG_FILE:-/tmp/${PULSE_SINK_NAME}-media-fallback.log}"
YTDLP_LOG="${WEBCAST_YTDLP_LOG_FILE:-/tmp/${PULSE_SINK_NAME}-yt-dlp.log}"
YOUTUBE_FFMPEG_LOG="${WEBCAST_YOUTUBE_FFMPEG_LOG_FILE:-/tmp/${PULSE_SINK_NAME}-youtube-ffmpeg.log}"
PREFLIGHT_CAPTURE_LOG="${STT_AUDIO_PREFLIGHT_CAPTURE_LOG_FILE:-/tmp/${PULSE_SINK_NAME}-preflight-capture.log}"
export STT_AUDIO_PREFLIGHT_FILE
export STT_AUDIO_PREFLIGHT_REPORT_FILE
export CALL_ID TICKER
if [[ "${WEBCAST_LIFECYCLE:-unknown}" == "live" ]]; then
  export WEBCAST_SUPERVISED_LIVE=true
  # Native model hangs are isolated from the browser/recorder and retried at
  # the same uncommitted audio window by the existing parent consumer.
  export STT_ISOLATED_MODEL="${STT_ISOLATED_MODEL:-true}"
  export WEBCAST_LIVE_TERMINATION_FILE="${WEBCAST_LIVE_TERMINATION_FILE:-/tmp/${PULSE_SINK_NAME}-live-termination.json}"
  export WEBCAST_LIVE_RUN_ID="$(python -c 'import uuid; print(uuid.uuid4().hex)')"
  export WEBCAST_LIVE_RUN_STARTED_AT="$(python -c 'import time; print(time.time())')"
  rm -f "${WEBCAST_LIVE_TERMINATION_FILE}"
else
  export WEBCAST_SUPERVISED_LIVE=false
fi

# Keep a compact per-capture supervisor log alongside the handoff manifest.
# The manager only reads it after a non-zero exit to classify a real provider
# barrier (for example an email-login requirement) without replaying the same
# registration form blindly. The path lives in the mounted runtime directory.
if [[ -n "${WEBCAST_CAPTURE_LOG_FILE}" ]]; then
  if mkdir -p "$(dirname "${WEBCAST_CAPTURE_LOG_FILE}")" 2>/dev/null \
    && : > "${WEBCAST_CAPTURE_LOG_FILE}" 2>/dev/null; then
    chmod 600 "${WEBCAST_CAPTURE_LOG_FILE}" 2>/dev/null || true
    exec > >(tee -a "${WEBCAST_CAPTURE_LOG_FILE}") 2>&1
  else
    echo "WEBCAST_CAPTURE_LOG_UNAVAILABLE path=${WEBCAST_CAPTURE_LOG_FILE}" >&2
  fi
fi

export WEBCAST_RECIPE_CONTEXT_PATH="${RECIPE_CONTEXT_PATH}"
export WEBCAST_MANUAL_READY_FILE="${MANUAL_READY_FILE}"
export WEBCAST_PLAYBACK_READY_FILE="${PLAYBACK_READY_FILE}"
export WEBCAST_TARGET_IDENTITY_READY_FILE="${TARGET_IDENTITY_READY_FILE}"
export WEBCAST_ACTIVE_PLAYER_URL_FILE="${ACTIVE_PLAYER_URL_FILE}"
export WEBCAST_LAST_TARGET_URL_FILE="${LAST_TARGET_URL_FILE}"
export WEBCAST_MEDIA_CANDIDATES_FILE="${MEDIA_CANDIDATES_FILE}"
export WEBCAST_PROBE_MEDIA_CANDIDATES_FILE="${PROBE_MEDIA_CANDIDATES_FILE}"
export WEBCAST_HUMAN_LOOP_ENABLED="${HUMAN_LOOP_ENABLED}"
export WEBCAST_HUMAN_RESUME_FILE="${HUMAN_RESUME_FILE}"
export WEBCAST_HUMAN_HANDOFF_FILE="${HUMAN_HANDOFF_FILE}"
export WEBCAST_HUMAN_ACTION_LOG_FILE="${HUMAN_ACTION_LOG_FILE}"
export WEBCAST_HUMAN_HANDOFF_TIMEOUT_SECONDS="${HUMAN_HANDOFF_TIMEOUT_SECONDS}"

if [[ "${HUMAN_LOOP_ENABLED}" == "true" && -n "${HUMAN_RESUME_FILE}" ]]; then
  rm -f "${HUMAN_RESUME_FILE}"
fi

# The browser must remain alive long enough for the initial audio check.
MINIMUM_HOLD_SECONDS=$((WEBCAST_WARMUP_SECONDS + AUDIO_WAIT_SECONDS + 10))
if (( WEBCAST_HOLD_SECONDS < MINIMUM_HOLD_SECONDS )); then
  WEBCAST_HOLD_SECONDS="${MINIMUM_HOLD_SECONDS}"
fi

# The STT worker owns normal shutdown and writes a terminal archive marker.
# These bounds prevent a quiet or stalled PulseAudio monitor from keeping a
# browser session alive indefinitely.
if [[ "${WEBCAST_SUPERVISED_LIVE}" == "true" ]]; then
  STT_MAX_SESSION_SECONDS="${STT_MAX_SESSION_SECONDS:-14400}"
else
  STT_MAX_SESSION_SECONDS="${STT_MAX_SESSION_SECONDS:-$((WEBCAST_HOLD_SECONDS + 90))}"
fi
STT_NO_CHUNK_TIMEOUT_SECONDS="${STT_NO_CHUNK_TIMEOUT_SECONDS:-45}"
STT_NO_TEXT_TIMEOUT_SECONDS="${STT_NO_TEXT_TIMEOUT_SECONDS:-600}"
export STT_MAX_SESSION_SECONDS
export STT_NO_CHUNK_TIMEOUT_SECONDS
export STT_NO_TEXT_TIMEOUT_SECONDS
LIVE_AUDIO_SOURCE_KIND=browser

terminate_child() {
  local pid="${1:-}"
  local process_group="${2:-false}"
  local grace_ticks="${3:-25}"
  local cleanup_tick
  [[ -n "${pid}" ]] || return 0

  if [[ "${process_group}" == "true" ]]; then
    kill -- "-${pid}" 2>/dev/null || kill "${pid}" 2>/dev/null || true
  else
    kill "${pid}" 2>/dev/null || true
  fi
  # Avoid an unbounded wait in EXIT cleanup. Chromium occasionally keeps a
  # helper alive after TERM; five seconds later the complete browser session
  # is force-killed so the scheduler slot cannot leak across probes.
  for (( cleanup_tick=0; cleanup_tick<grace_ticks; cleanup_tick++ )); do
    if [[ "${process_group}" == "true" ]]; then
      kill -0 -- "-${pid}" 2>/dev/null || break
    else
      kill -0 "${pid}" 2>/dev/null || break
    fi
    sleep 0.2
  done
  if [[ "${process_group}" == "true" ]]; then
    if kill -0 -- "-${pid}" 2>/dev/null; then
      kill -KILL -- "-${pid}" 2>/dev/null || true
    fi
  else
    if kill -0 "${pid}" 2>/dev/null; then
      kill -KILL "${pid}" 2>/dev/null || true
    fi
  fi
  wait "${pid}" 2>/dev/null || true
}

pulse_process_identity() {
  local pid="${1:-}" process_stat stat_tail
  local -a stat_fields
  [[ "${pid}" =~ ^[0-9]+$ ]] || return 1
  IFS= read -r process_stat 2>/dev/null < "/proc/${pid}/stat" || return 1
  stat_tail="${process_stat##*) }"
  read -ra stat_fields <<< "${stat_tail}"
  [[ "${stat_fields[0]:-Z}" != "Z" && -n "${stat_fields[19]:-}" ]] || return 1
  printf '%s\n' "${stat_fields[19]}"
}

cleanup_private_pulse() {
  local pulse_pid="" pulse_identity="" observed="" pulse_tick
  if [[ -r "${PULSE_RUNTIME_PATH:-}/pid" ]]; then
    read -r pulse_pid < "${PULSE_RUNTIME_PATH}/pid" || true
    pulse_identity="$(pulse_process_identity "${pulse_pid}")" || true
  fi
  pulseaudio --kill >/dev/null 2>&1 || true
  # --kill only sends a signal. Removing the directory before the daemon has
  # finished lets its shutdown code recreate an empty runtime/pulse directory.
  # Wait for this exact private daemon (PID + process start), not a reused PID.
  if [[ -n "${pulse_identity}" ]]; then
    for (( pulse_tick=0; pulse_tick<50; pulse_tick++ )); do
      observed="$(pulse_process_identity "${pulse_pid}")" || break
      [[ "${observed}" == "${pulse_identity}" ]] || break
      sleep 0.1
    done
    if [[ "$(pulse_process_identity "${pulse_pid}" || true)" == "${pulse_identity}" ]]; then
      echo "PULSE_CLEANUP_FORCE_KILL pid=${pulse_pid} sink=${PULSE_SINK_NAME}" >&2
      kill -KILL "${pulse_pid}" 2>/dev/null || true
      for (( pulse_tick=0; pulse_tick<10; pulse_tick++ )); do
        observed="$(pulse_process_identity "${pulse_pid}")" || break
        [[ "${observed}" == "${pulse_identity}" ]] || break
        sleep 0.1
      done
    fi
    if [[ "$(pulse_process_identity "${pulse_pid}" || true)" == "${pulse_identity}" ]]; then
      echo "PULSE_CLEANUP_INCOMPLETE pid=${pulse_pid} sink=${PULSE_SINK_NAME}" >&2
      return 1
    fi
  fi
  rm -rf "${XDG_RUNTIME_DIR}" 2>/dev/null || return 1
}

cleanup() {
  local capture_exit_code="$?"
  # The parent may send TERM while the EXIT trap is waiting for Chromium.
  # Re-entering the signal trap would abort cleanup before this call's private
  # PulseAudio daemon is stopped. The parent's final KILL remains the bound.
  trap '' INT TERM
  echo "CAPTURE_CLEANUP_STARTED code=${capture_exit_code} sink=${PULSE_SINK_NAME}"
  terminate_child "${LIVE_SOURCE_WATCH_PID:-}"
  terminate_child "${PCM_HANDOFF_PID:-}" true 35
  terminate_child "${WEBCAST_PID:-}" true
  terminate_child "${YOUTUBE_FALLBACK_PID:-}"
  terminate_child "${MEDIA_FALLBACK_PID:-}"
  terminate_child "${WEBCAST_NOVNC_PID:-}"
  terminate_child "${WEBCAST_X11VNC_PID:-}"
  terminate_child "${WEBCAST_XVFB_PID:-}"
  if [[ "${PULSE_RUNTIME_DIR_OWNED:-false}" == "true" ]]; then
    cleanup_private_pulse || echo "PULSE_RUNTIME_CLEANUP_FAILED sink=${PULSE_SINK_NAME}" >&2
  fi
  # Browser and recorder run in separate sessions: the manager cannot reap
  # them by killing this supervisor's process group. Stop them and the private
  # audio daemon before best-effort archive finalization, whose filesystem
  # I/O has no subprocess deadline. Failed captures retain their PCM if
  # finalization cannot finish. KILL also bounds children inheriting ignored
  # TERM from the cleanup trap. The finalizer does not spawn subprocesses;
  # --foreground kills only that Python PID, leaving timeout alive to reap it
  # instead of killing timeout's own group and orphaning a zombie under PID 1.
  if [[ -n "${PCM_HANDOFF_FILE:-}" ]]; then
    timeout --foreground --signal=KILL 5s python -m data_pipeline.stt_worker.audio_rescue \
      --finalize "${PCM_HANDOFF_FILE}" --exit-code "${capture_exit_code}" \
      || echo "STT_PCM_RESCUE_MANIFEST_FAILED finalize_incomplete=true capture_exit_code=${capture_exit_code} finalize_deadline_seconds=5"
  fi
  echo "CAPTURE_CLEANUP_DONE code=${capture_exit_code} sink=${PULSE_SINK_NAME}"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

# Isolate PulseAudio per call. A shared daemon lets a stale socket or a
# concurrent bootstrap affect unrelated calls and can route audio to the wrong
# monitor. The sink name is unique per call, so it is also a stable directory
# key for the browser and STT child processes.
if [[ -n "${WEBCAST_PULSE_RUNTIME_DIR:-}" ]]; then
  PULSE_RUNTIME_PATH="${WEBCAST_PULSE_RUNTIME_DIR}"
  XDG_RUNTIME_DIR="${WEBCAST_XDG_RUNTIME_DIR:-${PULSE_RUNTIME_PATH%/pulse}}"
  PULSE_RUNTIME_DIR_OWNED=false
else
  PULSE_RUNTIME_ROOT="${WEBCAST_XDG_RUNTIME_DIR:-/tmp/ew-pulse-${UID:-$(id -u)}}"
  XDG_RUNTIME_DIR="${PULSE_RUNTIME_ROOT}/${PULSE_SINK_NAME}"
  PULSE_RUNTIME_PATH="${XDG_RUNTIME_DIR}/pulse"
  PULSE_RUNTIME_DIR_OWNED=true
fi
export XDG_RUNTIME_DIR
export PULSE_RUNTIME_PATH
export PULSE_SERVER="unix:${PULSE_RUNTIME_PATH}/native"
mkdir -p "${XDG_RUNTIME_DIR}"
chmod 700 "${XDG_RUNTIME_DIR}" 2>/dev/null || true

if [[ -n "${FFMPEG_BIN:-}" ]]; then
  FFMPEG_BIN="${FFMPEG_BIN}"
elif [[ -x /usr/bin/ffmpeg ]] && /usr/bin/ffmpeg -hide_banner -muxers 2>&1 | grep -q pulse; then
  FFMPEG_BIN="/usr/bin/ffmpeg"
else
  FFMPEG_BIN="$(command -v ffmpeg)"
fi

wait_for_pulseaudio() {
  for _ in {1..50}; do
    if pactl info >/dev/null 2>&1; then
      return 0
    fi
    sleep 0.1
  done
  return 1
}

pulse_lock_fd=""
if command -v flock >/dev/null 2>&1; then
  exec {pulse_lock_fd}>"${XDG_RUNTIME_DIR}/ew-pulse-bootstrap.lock"
  flock -x "${pulse_lock_fd}"
fi

if ! wait_for_pulseaudio; then
  # This runtime belongs to this call, so a failed connection can only be a
  # stale process/socket for this call. Clear both before retrying bootstrap.
  pulseaudio --kill >/dev/null 2>&1 || true
  rm -f "${PULSE_RUNTIME_PATH}/native" "${PULSE_RUNTIME_PATH}/pid"
  pulseaudio --daemonize=yes --exit-idle-time=-1 --disallow-exit --log-target=stderr || true
fi

if ! wait_for_pulseaudio; then
  if [[ -n "${pulse_lock_fd}" ]]; then
    flock -u "${pulse_lock_fd}" || true
    eval "exec ${pulse_lock_fd}>&-"
  fi
  echo "PulseAudio server did not start." >&2
  exit 1
fi

if [[ -n "${pulse_lock_fd}" ]]; then
  flock -u "${pulse_lock_fd}"
  eval "exec ${pulse_lock_fd}>&-"
fi

if ! pactl list short sinks | awk '{print $2}' | grep -Fxq "${PULSE_SINK_NAME}"; then
  pactl load-module module-null-sink \
    sink_name="${PULSE_SINK_NAME}" \
    sink_properties=device.description="${PULSE_SINK_NAME}" >/dev/null
fi

# This daemon is isolated per call, so its default cannot affect another call
# or the user's desktop. Some Chromium builds ignore PULSE_SINK and only use
# the PulseAudio daemon default, so point this private daemon at its own sink.
pactl set-default-sink "${PULSE_SINK_NAME}"
export PULSE_SINK="${PULSE_SINK_NAME}"

pulse_sink_index() {
  pactl list short sinks 2>/dev/null \
    | awk -v sink="${PULSE_SINK_NAME}" '$2 == sink { print $1; exit }'
}

route_sink_inputs() {
  # A browser can create its sink input before Chromium observes the private
  # daemon's default sink. Keep the per-call capture isolated and unmuted.
  local target_sink_index
  target_sink_index="$(pulse_sink_index)"
  if [[ -z "${target_sink_index}" ]]; then
    return 0
  fi
  while read -r sink_input sink_index _; do
    if [[ -z "${sink_input}" || ! "${sink_input}" =~ ^[0-9]+$ ]]; then
      continue
    fi
    if [[ "${sink_index}" != "${target_sink_index}" ]]; then
      pactl move-sink-input "${sink_input}" "${PULSE_SINK_NAME}" >/dev/null 2>&1 || true
    fi
    pactl set-sink-input-mute "${sink_input}" 0 >/dev/null 2>&1 || true
  done < <(pactl list short sink-inputs 2>/dev/null || true)
}

WEBCAST_COMMAND=(
  python
  -m
  data_pipeline.collectors.streams.browser_webcast
  --ticker
  "${TICKER}"
  --ir-url
  "${IR_URL}"
  --hold-seconds
  "${WEBCAST_HOLD_SECONDS}"
)
if [[ -n "${WEBCAST_TARGET_YEAR:-}" ]]; then
  WEBCAST_COMMAND+=(--target-year "${WEBCAST_TARGET_YEAR}")
fi
if [[ -n "${WEBCAST_TARGET_QUARTER:-}" ]]; then
  WEBCAST_COMMAND+=(--target-quarter "${WEBCAST_TARGET_QUARTER}")
fi
if [[ "${WEBCAST_HEADED:-true}" == "true" ]]; then
  WEBCAST_COMMAND+=(--headed)
fi

if [[ -n "${MANUAL_READY_FILE}" ]]; then
  rm -f "${MANUAL_READY_FILE}"
fi
rm -f "${PLAYBACK_READY_FILE}"
rm -f "${TARGET_IDENTITY_READY_FILE}"
rm -f "${ACTIVE_PLAYER_URL_FILE}"
rm -f "${MEDIA_CANDIDATES_FILE}"
rm -f "${AUDIO_READY_FILE}" "${PROBE_PROMOTE_FILE}" "${PROBE_ABORT_FILE}"

start_vnc_display() {
  if [[ ! -d /usr/share/novnc ]]; then
    echo "noVNC is not installed in the browser image." >&2
    exit 1
  fi

  export DISPLAY="${WEBCAST_VNC_DISPLAY}"
  Xvfb "${DISPLAY}" -screen 0 "${WEBCAST_VNC_RESOLUTION}" -ac -nolisten tcp &
  WEBCAST_XVFB_PID="$!"
  sleep 1
  if ! kill -0 "${WEBCAST_XVFB_PID}" 2>/dev/null; then
    echo "Xvfb did not start for noVNC." >&2
    exit 1
  fi

  x11vnc -display "${DISPLAY}" -localhost -forever -shared -nopw \
    -rfbport "${WEBCAST_VNC_RFB_PORT}" >/tmp/ew-x11vnc.log 2>&1 &
  WEBCAST_X11VNC_PID="$!"
  websockify --web=/usr/share/novnc "${WEBCAST_VNC_WEB_PORT}" \
    "127.0.0.1:${WEBCAST_VNC_RFB_PORT}" >/tmp/ew-novnc.log 2>&1 &
  WEBCAST_NOVNC_PID="$!"
  sleep 1
  if ! kill -0 "${WEBCAST_X11VNC_PID}" 2>/dev/null \
    || ! kill -0 "${WEBCAST_NOVNC_PID}" 2>/dev/null; then
    echo "noVNC did not start." >&2
    exit 1
  fi
  echo "NOVNC_READY url=http://127.0.0.1:${WEBCAST_VNC_WEB_PORT}/vnc.html"
}

launch_webcast() {
  if [[ "${WEBCAST_VNC_ENABLED}" == "true" ]]; then
    start_vnc_display
    setsid "${WEBCAST_COMMAND[@]}" &
  elif [[ "${WEBCAST_USE_HOST_DISPLAY:-false}" == "true" ]]; then
    setsid "${WEBCAST_COMMAND[@]}" &
  elif [[ "${WEBCAST_HEADED:-true}" == "true" ]]; then
    setsid xvfb-run -a "${WEBCAST_COMMAND[@]}" &
  else
    setsid "${WEBCAST_COMMAND[@]}" &
  fi
  WEBCAST_PID="$!"
}

launch_webcast

wait_for_manual_ready() {
  if [[ -z "${MANUAL_READY_FILE}" ]]; then
    return 0
  fi

  local deadline=$((SECONDS + MANUAL_READY_TIMEOUT_SECONDS))
  echo "MANUAL_BROWSER_READY signal_file=${MANUAL_READY_FILE} timeout=${MANUAL_READY_TIMEOUT_SECONDS}s"
  while (( SECONDS < deadline )); do
    if [[ -f "${MANUAL_READY_FILE}" ]]; then
      echo "MANUAL_BROWSER_CONFIRMED"
      return 0
    fi
    if ! kill -0 "${WEBCAST_PID}" 2>/dev/null; then
      echo "WEBCAST_EXITED_BEFORE_MANUAL_CONFIRMATION" >&2
      return 1
    fi
    sleep 1
  done
  echo "MANUAL_BROWSER_CONFIRMATION_TIMED_OUT" >&2
  return 1
}

if ! wait_for_manual_ready; then
  exit 1
fi

list_direct_media_candidates() {
  # The current browser session is authoritative. Probe artifacts are only a
  # fallback because signed URLs from the earlier process may already be stale.
  python -c 'import json,re,sys; seen=set(); ranked=[]
for source_rank,path in enumerate(sys.argv[1:]):
  try: values=json.load(open(path)) if path else []
  except Exception: values=[]
  for value in values if isinstance(values,list) else []:
    value=str(value)
    if value in seen or not re.search(r"\.(?:m3u8|mpd|mp4|m4a|mp3|aac|wav|ts)(?:[/?#]|$)",value,re.I) or re.search(r"\.ts(?:[?#]|$)",value,re.I): continue
    seen.add(value); media_rank=0 if re.search(r"\.(?:m3u8|mpd)(?:[?#]|$)",value,re.I) else 1 if re.search(r"\.(?:mp4|m4a|mp3|aac|wav)(?:[?#]|$)",value,re.I) else 9
    audio_rank=0 if re.search(r"(?:audio|sound|aac|m4a|mp3|part1)(?:[._/-]|$)",value,re.I) else 1
    ranked.append(((source_rank,media_rank,audio_rank,len(value)),value))
for _,value in sorted(ranked): print(value)' \
    "${MEDIA_CANDIDATES_FILE}" "${PROBE_MEDIA_CANDIDATES_FILE}" 2>/dev/null || true
}

classify_media_fallback_failure() {
  local text
  text="$(tr '[:upper:]' '[:lower:]' < "${MEDIA_FALLBACK_LOG}" 2>/dev/null || true)"
  if [[ "${text}" == *"403"* || "${text}" == *"forbidden"* || "${text}" == *"accessdenied"* ]]; then
    printf 'access_denied'
  elif [[ "${text}" == *"404"* || "${text}" == *"not found"* ]]; then
    printf 'not_found'
  elif [[ "${text}" == *"expired"* || "${text}" == *"signature"* ]]; then
    printf 'expired_media_url'
  elif [[ "${text}" == *"invalid data"* || "${text}" == *"unsupported"* ]]; then
    printf 'unsupported_media'
  else
    printf 'startup_failed'
  fi
}

media_cookie_header() {
  local stream_url="$1"
  local storage_state="${WEBCAST_STORAGE_STATE:-}"
  if [[ -z "${storage_state}" || ! -s "${storage_state}" ]]; then
    return 0
  fi
  python -c 'import json,sys,urllib.parse
state=json.load(open(sys.argv[1])); parsed=urllib.parse.urlparse(sys.argv[2]); host=parsed.hostname or ""; path=parsed.path or "/"; pairs=[]
for cookie in state.get("cookies",[]):
  domain=str(cookie.get("domain") or "").lstrip("."); cookie_path=str(cookie.get("path") or "/")
  if domain and (host==domain or host.endswith("."+domain)) and path.startswith(cookie_path):
    name=str(cookie.get("name") or "").replace(";",""); value=str(cookie.get("value") or "").replace("\r","").replace("\n","").replace(";","");
    if name: pairs.append(name+"="+value)
print("; ".join(pairs))' "${storage_state}" "${stream_url}" 2>/dev/null || true
}

declare -A MEDIA_FALLBACK_REJECTED_URLS=()
MEDIA_FALLBACK_URL=""

media_url_key() {
  printf '%s' "$1" | sha256sum | awk '{print $1}'
}

live_target_identity_ready() {
  if [[ "${WEBCAST_LIFECYCLE:-unknown}" != "live" ]] \
    || [[ "${WEBCAST_REQUIRE_LIVE_TARGET_CONFIRMATION}" != "true" ]]; then
    return 0
  fi
  if [[ "${WEBCAST_LIVE_ENTRYPOINT_VERIFIED:-false}" == "true" ]]; then
    return 0
  fi
  if [[ -s "${TARGET_IDENTITY_READY_FILE}" ]]; then
    return 0
  fi
  echo "MEDIA_FALLBACK_BLOCKED target_identity_unconfirmed" >&2
  return 1
}

start_media_stream_fallback() {
  local stream_url
  local target_sink_index
  local cookie_header referer candidate_index=0 url_key
  live_target_identity_ready || return 1
  referer="$(head -n 1 "${ACTIVE_PLAYER_URL_FILE}" 2>/dev/null || head -n 1 "${LAST_TARGET_URL_FILE}" 2>/dev/null || true)"
  while IFS= read -r stream_url; do
    [[ "${stream_url}" =~ ^https?:// ]] || continue
    url_key="$(media_url_key "${stream_url}")"
    if [[ -n "${MEDIA_FALLBACK_REJECTED_URLS[${url_key}]:-}" ]]; then
      continue
    fi
    candidate_index=$((candidate_index + 1))
    local -a loop_args=()
    local -a request_args=(-user_agent "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126 Safari/537.36")
    if [[ "${stream_url}" =~ \.(mp4|m4a|mp3|aac|wav)([?#/]|$) ]]; then
      loop_args=(-stream_loop -1)
    fi
    if [[ "${referer}" =~ ^https?:// ]]; then
      request_args+=(-referer "${referer}")
    fi
    cookie_header="$(media_cookie_header "${stream_url}")"
    if [[ -n "${cookie_header}" ]]; then
      request_args+=(-headers "Cookie: ${cookie_header}"$'\r\n')
    fi
    echo "MEDIA_PULSE_FALLBACK_STARTING candidate=${candidate_index}"
    : > "${MEDIA_FALLBACK_LOG}"
    PULSE_SINK="${PULSE_SINK_NAME}" \
      "${FFMPEG_BIN}" -hide_banner -loglevel error -nostdin "${loop_args[@]}" -re \
        "${request_args[@]}" -i "${stream_url}" -map 0:a:0? -vn \
        -f pulse "${PULSE_SINK_NAME}" >"${MEDIA_FALLBACK_LOG}" 2>&1 &
    MEDIA_FALLBACK_PID="$!"
    MEDIA_FALLBACK_URL="${stream_url}"
    sleep 1
    if ! kill -0 "${MEDIA_FALLBACK_PID}" 2>/dev/null; then
      wait "${MEDIA_FALLBACK_PID}" 2>/dev/null || true
      MEDIA_FALLBACK_REJECTED_URLS["${url_key}"]=1
      echo "MEDIA_PULSE_FALLBACK_START_FAILED candidate=${candidate_index} kind=$(classify_media_fallback_failure)" >&2
      if [[ -s "${MEDIA_FALLBACK_LOG}" ]]; then
        tail -n 8 "${MEDIA_FALLBACK_LOG}" >&2 || true
      fi
      unset MEDIA_FALLBACK_PID
      continue
    fi
    local routed=false
    for _ in {1..20}; do
      route_sink_inputs
      target_sink_index="$(pulse_sink_index)"
      if [[ -n "${target_sink_index}" ]] \
        && pactl list short sink-inputs 2>/dev/null \
          | awk -v sink_index="${target_sink_index}" '$2 == sink_index { found=1 } END { exit !found }'; then
        routed=true
        echo "MEDIA_PULSE_FALLBACK_ROUTED sink=${PULSE_SINK_NAME}"
        break
      fi
      sleep 0.5
    done
    if [[ "${routed}" == "true" ]]; then
      LIVE_AUDIO_SOURCE_KIND=media
      echo "MEDIA_PULSE_FALLBACK_STARTED routed=true candidate=${candidate_index}"
      return 0
    fi
    echo "MEDIA_PULSE_FALLBACK_ROUTE_TIMEOUT sink=${PULSE_SINK_NAME} candidate=${candidate_index}" >&2
    terminate_child "${MEDIA_FALLBACK_PID}"
    MEDIA_FALLBACK_REJECTED_URLS["${url_key}"]=1
    unset MEDIA_FALLBACK_PID
  done < <(list_direct_media_candidates)
  echo "MEDIA_PULSE_FALLBACK_UNAVAILABLE no_usable_direct_media_candidate" >&2
  return 1
}

restart_media_stream_fallback_if_needed() {
  if [[ -z "${MEDIA_FALLBACK_PID:-}" ]] \
    || kill -0 "${MEDIA_FALLBACK_PID}" 2>/dev/null; then
    return 0
  fi
  if (( MEDIA_FALLBACK_RESTARTS >= MEDIA_FALLBACK_MAX_RESTARTS )); then
    return 1
  fi

  local exit_code=0
  wait "${MEDIA_FALLBACK_PID}" 2>/dev/null || exit_code=$?
  if [[ -n "${MEDIA_FALLBACK_URL}" ]]; then
    MEDIA_FALLBACK_REJECTED_URLS["$(media_url_key "${MEDIA_FALLBACK_URL}")"]=1
  fi
  echo "MEDIA_PULSE_FALLBACK_EXITED code=${exit_code} restart=${MEDIA_FALLBACK_RESTARTS}" >&2
  if [[ -s "${MEDIA_FALLBACK_LOG}" ]]; then
    tail -n 12 "${MEDIA_FALLBACK_LOG}" >&2 || true
  fi
  MEDIA_FALLBACK_RESTARTS=$((MEDIA_FALLBACK_RESTARTS + 1))
  start_media_stream_fallback
}

wait_for_playback_ready() {
  local deadline=$((SECONDS + PLAYBACK_READY_TIMEOUT_SECONDS))
  echo "WAITING_FOR_PLAYBACK_READY signal_file=${PLAYBACK_READY_FILE} timeout=${PLAYBACK_READY_TIMEOUT_SECONDS}s"
  while (( SECONDS < deadline )); do
    # _signal_playback_ready writes the active URL immediately before the
    # readiness marker. Accept both files so a filesystem notification race
    # cannot discard a confirmed player.
    if [[ -f "${PLAYBACK_READY_FILE}" ]] || [[ -s "${ACTIVE_PLAYER_URL_FILE}" ]]; then
      echo "PLAYBACK_READY_CONFIRMED"
      return 0
    fi
    if ! kill -0 "${WEBCAST_PID}" 2>/dev/null; then
      echo "WEBCAST_EXITED_BEFORE_PLAYBACK_READY" >&2
      return 1
    fi
    sleep 1
  done
  # The browser and this supervisor share the mounted handshake file, but a
  # signal can be created on the exact deadline between the final loop check
  # and the timeout branch. Give that boundary race a short grace window so a
  # confirmed player is not reported as an activation failure.
  for _ in 1 2 3; do
    if [[ -f "${PLAYBACK_READY_FILE}" ]] || [[ -s "${ACTIVE_PLAYER_URL_FILE}" ]]; then
      echo "PLAYBACK_READY_CONFIRMED_AFTER_GRACE"
      return 0
    fi
    sleep 1
  done
  echo "PLAYBACK_READY_TIMED_OUT" >&2
  return 1
}

MEDIA_FALLBACK_RESTARTS=0
if ! wait_for_playback_ready; then
  if start_media_stream_fallback; then
    echo "PLAYBACK_READY_RECOVERED_FROM_MEDIA_CANDIDATE"
  else
    exit 1
  fi
fi

route_sink_inputs
# Retain the confirmed player's input across warmup, preflight and promotion.
# The spool is per-process, private, bounded, and retained on incomplete exit.
if [[ "${STT_PCM_HANDOFF_ENABLED:-true}" == "true" ]] && live_target_identity_ready; then
  if PCM_HANDOFF_FILE="$(python -m data_pipeline.stt_worker.audio_rescue --allocate --supervisor-pid "$$")"; then
    :
  else
    echo "PCM_ALLOCATION_FAILED: see typed audio storage error above" >&2
    exit 73
  fi
  setsid python -m data_pipeline.stt_worker.pcm_handoff \
    --record "${PCM_HANDOFF_FILE}" \
    --max-bytes "${STT_PCM_HANDOFF_MAX_BYTES:-536870912}" -- \
    "${FFMPEG_BIN}" -hide_banner -loglevel error -nostdin \
    -f pulse -i "${PULSE_MONITOR}" -vn -ac 1 -ar 16000 -f s16le pipe:1 &
  PCM_HANDOFF_PID="$!"
  export STT_PCM_HANDOFF_FILE="${PCM_HANDOFF_FILE}"
  export STT_PCM_HANDOFF_PID="${PCM_HANDOFF_PID}"
  export STT_PCM_HANDOFF_STARTED_AT="$(date +%s.%N)"
  echo "STT_PCM_HANDOFF_STARTED pid=${PCM_HANDOFF_PID}"
fi
sleep "${WEBCAST_WARMUP_SECONDS}"

start_youtube_audio_fallback() {
  local active_url
  local stream_url
  live_target_identity_ready || return 1
  if [[ ! -s "${ACTIVE_PLAYER_URL_FILE}" ]]; then
    return 1
  fi
  active_url="$(head -n 1 "${ACTIVE_PLAYER_URL_FILE}")"
  if [[ ! "${active_url}" =~ ^https?://([^/]+\.)?(youtube\.com|youtu\.be)/ ]]; then
    return 1
  fi
  if ! command -v yt-dlp >/dev/null 2>&1 || [[ ! -x "${FFMPEG_BIN}" ]]; then
    echo "YOUTUBE_PULSE_FALLBACK_UNAVAILABLE" >&2
    return 1
  fi
  stream_url="$(
    timeout 30 yt-dlp \
      --no-playlist --no-warnings --no-progress \
      -f bestaudio -g "${active_url}" 2>"${YTDLP_LOG}" \
      | head -n 1 || true
  )"
  if [[ -z "${stream_url}" ]]; then
    local resolver_log
    resolver_log="$(tr '[:upper:]' '[:lower:]' < "${YTDLP_LOG}" 2>/dev/null || true)"
    if [[ "${resolver_log}" == *"sign in"* || "${resolver_log}" == *"confirm you\u2019re not a bot"* ]]; then
      echo "YOUTUBE_PULSE_FALLBACK_RESOLVE_FAILED kind=auth_required" >&2
    elif [[ "${resolver_log}" == *"403"* || "${resolver_log}" == *"forbidden"* ]]; then
      echo "YOUTUBE_PULSE_FALLBACK_RESOLVE_FAILED kind=access_denied" >&2
    elif [[ "${resolver_log}" == *"requested format is not available"* ]]; then
      echo "YOUTUBE_PULSE_FALLBACK_RESOLVE_FAILED kind=format_unavailable" >&2
    else
      echo "YOUTUBE_PULSE_FALLBACK_RESOLVE_FAILED kind=resolver_error" >&2
    fi
    return 1
  fi
  PULSE_SINK="${PULSE_SINK_NAME}" \
    "${FFMPEG_BIN}" -hide_banner -loglevel error -nostdin -re \
      -ss "${YOUTUBE_FALLBACK_SEEK_SECONDS}" -i "${stream_url}" \
      -vn -f pulse "${PULSE_SINK_NAME}" \
      >"${YOUTUBE_FFMPEG_LOG}" 2>&1 &
  YOUTUBE_FALLBACK_PID="$!"
  sleep 2
  if kill -0 "${YOUTUBE_FALLBACK_PID}" 2>/dev/null; then
    echo "YOUTUBE_PULSE_FALLBACK_STARTED seek=${YOUTUBE_FALLBACK_SEEK_SECONDS}s"
  else
    # Historical proxy videos are often shorter than the normal seek point.
    # Retry from the beginning so a short but playable video can still feed
    # the isolated PulseAudio monitor.
    wait "${YOUTUBE_FALLBACK_PID}" 2>/dev/null || true
    PULSE_SINK="${PULSE_SINK_NAME}" \
      "${FFMPEG_BIN}" -hide_banner -loglevel error -nostdin -re \
        -i "${stream_url}" -vn -f pulse "${PULSE_SINK_NAME}" \
        >"${YOUTUBE_FFMPEG_LOG}" 2>&1 &
    YOUTUBE_FALLBACK_PID="$!"
    sleep 2
    if kill -0 "${YOUTUBE_FALLBACK_PID}" 2>/dev/null; then
      echo "YOUTUBE_PULSE_FALLBACK_STARTED seek=0 retry=true"
    else
      local player_log
      player_log="$(tr '[:upper:]' '[:lower:]' < "${YOUTUBE_FFMPEG_LOG}" 2>/dev/null || true)"
      if [[ "${player_log}" == *"403"* || "${player_log}" == *"forbidden"* ]]; then
        echo "YOUTUBE_PULSE_FALLBACK_START_FAILED kind=access_denied" >&2
      elif [[ "${player_log}" == *"404"* || "${player_log}" == *"not found"* ]]; then
        echo "YOUTUBE_PULSE_FALLBACK_START_FAILED kind=not_found" >&2
      elif [[ "${player_log}" == *"invalid data"* || "${player_log}" == *"unable to"* ]]; then
        echo "YOUTUBE_PULSE_FALLBACK_START_FAILED kind=media_read_failed" >&2
      else
        echo "YOUTUBE_PULSE_FALLBACK_START_FAILED kind=startup_failed" >&2
      fi
      if [[ -s "${YOUTUBE_FFMPEG_LOG}" ]]; then
        tail -n 8 "${YOUTUBE_FFMPEG_LOG}" >&2 || true
      fi
      unset YOUTUBE_FALLBACK_PID
      return 1
    fi
  fi
  route_sink_inputs
  LIVE_AUDIO_SOURCE_KIND=youtube
  return 0
}

wait_for_audio() {
  local deadline=$((SECONDS + AUDIO_WAIT_SECONDS))
  local probe_output
  local max_volume

  while (( SECONDS < deadline )); do
    restart_media_stream_fallback_if_needed || true
    # A browser session may exit after it has handed us a direct media URL.
    # Keep probing while the media fallback is still feeding the isolated
    # PulseAudio sink; otherwise short historical clips are discarded before
    # their audio can be measured.
    if ! kill -0 "${WEBCAST_PID}" 2>/dev/null \
      && { [[ -z "${MEDIA_FALLBACK_PID:-}" ]] \
        || ! kill -0 "${MEDIA_FALLBACK_PID}" 2>/dev/null; } \
      && { [[ -z "${YOUTUBE_FALLBACK_PID:-}" ]] \
        || ! kill -0 "${YOUTUBE_FALLBACK_PID}" 2>/dev/null; }; then
      echo "WEBCAST_EXITED_BEFORE_AUDIO" >&2
      return 1
    fi

    route_sink_inputs

    probe_output="$(
      timeout "$((AUDIO_PROBE_SECONDS + 5))" \
        "${FFMPEG_BIN}" -hide_banner -nostdin -t "${AUDIO_PROBE_SECONDS}" \
        -f pulse -i "${PULSE_MONITOR}" -af volumedetect -f null - 2>&1 || true
    )"
    max_volume="$(
      printf '%s\n' "${probe_output}" \
        | sed -n 's/.*max_volume: \([-0-9.]*\) dB.*/\1/p' \
        | tail -n 1
    )"

    if [[ -n "${max_volume}" ]] \
      && awk -v measured="${max_volume}" -v threshold="${AUDIO_MIN_DB}" \
        'BEGIN { exit !(measured > threshold) }'; then
      echo "AUDIO_DETECTED max_volume=${max_volume}dB threshold=${AUDIO_MIN_DB}dB"
      return 0
    fi

    sleep "${AUDIO_PROBE_INTERVAL_SECONDS}"
  done

  local sink_state input_state target_sink_index
  sink_state="$(pactl list short sinks 2>/dev/null \
    | awk -v sink="${PULSE_SINK_NAME}" '$2 == sink {print; found=1} END {if (!found) print "not-found"}' \
    | tr '\n' ';')"
  target_sink_index="$(pulse_sink_index)"
  input_state="$(pactl list short sink-inputs 2>/dev/null \
    | awk -v sink_index="${target_sink_index}" '$2 == sink_index {print; found=1} END {if (!found) print "not-found"}' \
    | tr '\n' ';')"
  echo "AUDIO_NOT_DETECTED within=${AUDIO_WAIT_SECONDS}s threshold=${AUDIO_MIN_DB}dB" >&2
  echo "PULSE_AUDIO_STATE sink=${PULSE_SINK_NAME} monitor=${PULSE_MONITOR} sink_state=${sink_state} input_state=${input_state}" >&2
  return 1
}

wait_for_human_audio_resume() {
  if [[ "${HUMAN_LOOP_ENABLED}" != "true" || -z "${HUMAN_RESUME_FILE}" ]]; then
    return 1
  fi

  local deadline=$((SECONDS + HUMAN_HANDOFF_TIMEOUT_SECONDS))
  echo "HUMAN_HANDOFF stage=audio reason=가상 오디오 장치에서 음성이 검출되지 않았습니다."
  while (( SECONDS < deadline )); do
    if [[ -f "${HUMAN_RESUME_FILE}" ]]; then
      rm -f "${HUMAN_RESUME_FILE}"
      echo "HUMAN_BATON_RETURNED stage=audio"
      return 0
    fi
    if ! kill -0 "${WEBCAST_PID}" 2>/dev/null; then
      return 1
    fi
    sleep 1
  done
  echo "HUMAN_HANDOFF_TIMEOUT stage=audio timeout=${HUMAN_HANDOFF_TIMEOUT_SECONDS}s" >&2
  return 1
}

capture_stt_audio_preflight() {
  if ! awk -v seconds="${STT_AUDIO_PREFLIGHT_SECONDS}" \
    'BEGIN { exit !(seconds > 0) }'; then
    echo "STT_PREFLIGHT_DISABLED"
    return 0
  fi

  local sample_file="${STT_AUDIO_PREFLIGHT_FILE}"
  local temporary_file="${sample_file}.part.wav"
  local capture_log="${PREFLIGHT_CAPTURE_LOG}"
  local timeout_seconds
  timeout_seconds="$(awk -v seconds="${STT_AUDIO_PREFLIGHT_SECONDS}" 'BEGIN { printf "%d", seconds + 15 }')"
  mkdir -p "$(dirname "${sample_file}")" 2>/dev/null || true
  rm -f "${temporary_file}" "${sample_file}"

  echo "STT_PREFLIGHT_CAPTURING seconds=${STT_AUDIO_PREFLIGHT_SECONDS} monitor=${PULSE_MONITOR}"
  if timeout "${timeout_seconds}" \
    "${FFMPEG_BIN}" -hide_banner -loglevel error -nostdin -y \
      -f pulse -i "${PULSE_MONITOR}" \
      -t "${STT_AUDIO_PREFLIGHT_SECONDS}" -vn -ac 1 -ar 16000 \
      -c:a pcm_s16le -f wav "${temporary_file}" \
      >"${capture_log}" 2>&1 \
    && [[ -s "${temporary_file}" ]]; then
    mv "${temporary_file}" "${sample_file}"
    echo "STT_PREFLIGHT_CAPTURED path=${sample_file} bytes=$(wc -c < "${sample_file}")"
    return 0
  fi

  rm -f "${temporary_file}"
  echo "STT_PREFLIGHT_CAPTURE_FAILED" >&2
  if [[ -s "${capture_log}" ]]; then
    tail -n 8 "${capture_log}" >&2 || true
  fi
  return 1
}

confirm_stt_preflight_speech() {
  if [[ "${WEBCAST_SPEECH_PREFLIGHT_ENABLED}" != "true" ]]; then
    echo "SPEECH_PREFLIGHT_DISABLED"
    return 0
  fi
  if ! capture_stt_audio_preflight; then
    echo "SPEECH_NOT_DETECTED reason=audio_sample_unavailable" >&2
    return 1
  fi
  if python -m data_pipeline.stt_worker.take \
    --ticker "${TICKER}" \
    --call-id "${CALL_ID}-preflight" \
    --input-kind file \
    --input-source "${STT_AUDIO_PREFLIGHT_FILE}" \
    --input-format wav \
    --model-name "${STT_AUDIO_PREFLIGHT_MODEL_NAME}" \
    --audio-preflight-only \
    --no-ai-engine \
    --no-backend \
    --no-transcript-archive; then
    return 0
  fi
  echo "SPEECH_NOT_DETECTED reason=whisper_preflight" >&2
  return 1
}

record_recipe_outcome() {
  local outcome="$1"
  local error_message="${2:-}"
  if [[ ! -f "${RECIPE_CONTEXT_PATH}" ]]; then
    return
  fi
  python -m data_pipeline.collectors.streams.recipe_outcome \
    --context-file "${RECIPE_CONTEXT_PATH}" \
    --outcome "${outcome}" \
    --error "${error_message}" >/dev/null 2>&1 || true
}

if ! wait_for_audio; then
  if wait_for_human_audio_resume && wait_for_audio; then
    echo "AUDIO_DETECTED after human intervention"
  elif start_media_stream_fallback && wait_for_audio; then
    echo "AUDIO_DETECTED source=media-stream-fallback"
  elif start_youtube_audio_fallback && wait_for_audio; then
    echo "AUDIO_DETECTED source=youtube-media-fallback"
  else
    record_recipe_outcome failure "PulseAudio monitor did not receive audible webcast output"
    exit 1
  fi
fi

record_recipe_outcome success

# The fallback search has finished, so the winning producer PIDs are now fixed.
# Browser death is legitimate only while that selected fallback is still alive.
# Stop PCM on source loss/end to let STT consume the remaining recorded bytes.
if [[ "${WEBCAST_SUPERVISED_LIVE}" == "true" ]]; then
  LIVE_SOURCE_WATCH_COMMAND=(
    python -m data_pipeline.collectors.streams.browser.lifetime
    --watch-sources --browser-pid "${WEBCAST_PID}"
  )
  if [[ -n "${PCM_HANDOFF_PID:-}" ]]; then
    LIVE_SOURCE_WATCH_COMMAND+=(--pcm-pid "${PCM_HANDOFF_PID}")
  fi
  # Preserve the selected producer even if it died just after the audio probe.
  # Dropping a dead fallback PID would mistake an idle browser for the source.
  case "${LIVE_AUDIO_SOURCE_KIND}" in
    media) LIVE_SOURCE_WATCH_COMMAND+=(--fallback-pid "${MEDIA_FALLBACK_PID:-0}") ;;
    youtube) LIVE_SOURCE_WATCH_COMMAND+=(--fallback-pid "${YOUTUBE_FALLBACK_PID:-0}") ;;
  esac
  "${LIVE_SOURCE_WATCH_COMMAND[@]}" &
  LIVE_SOURCE_WATCH_PID="$!"
fi

if awk -v seconds="${SUCCESS_HOLD_SECONDS}" 'BEGIN { exit !(seconds > 0) }'; then
  echo "HOLDING_SUCCESS_SCREEN seconds=${SUCCESS_HOLD_SECONDS}"
  sleep "${SUCCESS_HOLD_SECONDS}"
fi

if [[ "${PROBE_ONLY}" == "true" ]]; then
  if ! confirm_stt_preflight_speech; then
    # The page, player, and audio route are already confirmed above. A short
    # sample without speech is a temporal observation, not evidence that this
    # is the wrong webcast. Keep the learned target and let the long capture
    # observe later speech instead of restarting candidate discovery.
    echo "SPEECH_PENDING short_sample_without_speech"
  fi
  if [[ "${PROBE_PROMOTION_ENABLED}" == "true" ]]; then
    : > "${AUDIO_READY_FILE}"
    echo "PROBE_READY_FOR_PROMOTION signal_file=${PROBE_PROMOTE_FILE}"
    promotion_deadline=$((SECONDS + PROBE_PROMOTION_TIMEOUT_SECONDS))
    while (( SECONDS < promotion_deadline )); do
      if [[ -f "${PROBE_ABORT_FILE}" ]]; then
        echo "PROBE_PROMOTION_ABORTED"
        exit 75
      fi
      if [[ -f "${PROBE_PROMOTE_FILE}" ]]; then
        echo "PROBE_PROMOTED_TO_CAPTURE"
        PROBE_ONLY=false
        break
      fi
      if ! kill -0 "${WEBCAST_PID}" 2>/dev/null \
        && { [[ -z "${MEDIA_FALLBACK_PID:-}" ]] || ! kill -0 "${MEDIA_FALLBACK_PID}" 2>/dev/null; } \
        && { [[ -z "${YOUTUBE_FALLBACK_PID:-}" ]] || ! kill -0 "${YOUTUBE_FALLBACK_PID}" 2>/dev/null; } \
        && [[ ! -s "${WEBCAST_LIVE_TERMINATION_FILE:-/nonexistent}" ]]; then
        echo "WEBCAST_EXITED_BEFORE_PROMOTION" >&2
        exit 1
      fi
      sleep 0.2
    done
    if [[ "${PROBE_ONLY}" == "true" ]]; then
      echo "PROBE_PROMOTION_TIMED_OUT" >&2
      exit 75
    fi
  else
    exit 0
  fi
fi

# Record the current speech readiness for diagnostics. Long STT is allowed to
# continue through an intro, disclaimer, or pause; its watchdog decides only
# after the configured observation window whether speech never arrived.
# The WAV is deleted by take.py unless explicitly retained for diagnosis.
if [[ -z "${PCM_HANDOFF_FILE:-}" ]]; then
  capture_stt_audio_preflight || true
else
  echo "STT_PCM_HANDOFF_CONTINUING duplicate_preflight_skipped=true"
fi

# Generic IR entrypoints are verified by the browser after this shell process
# starts. Re-read that durable signal before launching STT so an in-place probe
# promotion carries the same target proof into the terminal transcript marker.
if [[ "${WEBCAST_LIVE_ENTRYPOINT_VERIFIED:-false}" == "true" ]] \
  || [[ -s "${TARGET_IDENTITY_READY_FILE}" ]]; then
  export WEBCAST_LIVE_ENTRYPOINT_VERIFIED=true
  export STT_TARGET_IDENTITY_VERIFIED=true
fi

python -m data_pipeline.stt_worker.take \
  --ticker "${TICKER}" \
  --call-id "${CALL_ID}" \
  --input-kind device \
  --input-format pulse \
  --input-source "${PULSE_MONITOR}" \
  "$@"
