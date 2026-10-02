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
ACTIVE_PLAYER_URL_FILE="${WEBCAST_ACTIVE_PLAYER_URL_FILE:-/tmp/ew-webcast-active-url}"
MEDIA_CANDIDATES_FILE="${WEBCAST_MEDIA_CANDIDATES_FILE:-/tmp/ew-webcast-media-candidates.json}"
PLAYBACK_READY_TIMEOUT_SECONDS="${WEBCAST_PLAYBACK_READY_TIMEOUT_SECONDS:-180}"
YOUTUBE_FALLBACK_SEEK_SECONDS="${WEBCAST_YOUTUBE_FALLBACK_SEEK_SECONDS:-240}"
WEBCAST_VNC_ENABLED="${WEBCAST_VNC_ENABLED:-false}"
WEBCAST_VNC_DISPLAY="${WEBCAST_VNC_DISPLAY:-:99}"
WEBCAST_VNC_RFB_PORT="${WEBCAST_VNC_RFB_PORT:-5900}"
WEBCAST_VNC_WEB_PORT="${WEBCAST_VNC_WEB_PORT:-6080}"
WEBCAST_VNC_RESOLUTION="${WEBCAST_VNC_RESOLUTION:-1280x900x24}"
export WEBCAST_RECIPE_CONTEXT_PATH="${RECIPE_CONTEXT_PATH}"
export WEBCAST_MANUAL_READY_FILE="${MANUAL_READY_FILE}"
export WEBCAST_PLAYBACK_READY_FILE="${PLAYBACK_READY_FILE}"
export WEBCAST_ACTIVE_PLAYER_URL_FILE="${ACTIVE_PLAYER_URL_FILE}"
export WEBCAST_MEDIA_CANDIDATES_FILE="${MEDIA_CANDIDATES_FILE}"

# The browser must remain alive long enough for the initial audio check.
MINIMUM_HOLD_SECONDS=$((WEBCAST_WARMUP_SECONDS + AUDIO_WAIT_SECONDS + 10))
if (( WEBCAST_HOLD_SECONDS < MINIMUM_HOLD_SECONDS )); then
  WEBCAST_HOLD_SECONDS="${MINIMUM_HOLD_SECONDS}"
fi

cleanup() {
  if [[ -n "${WEBCAST_PID:-}" ]]; then
    kill -- "-${WEBCAST_PID}" 2>/dev/null || kill "${WEBCAST_PID}" 2>/dev/null || true
    wait "${WEBCAST_PID}" 2>/dev/null || true
  fi
  if [[ -n "${YOUTUBE_FALLBACK_PID:-}" ]]; then
    kill "${YOUTUBE_FALLBACK_PID}" 2>/dev/null || true
    wait "${YOUTUBE_FALLBACK_PID}" 2>/dev/null || true
  fi
  if [[ -n "${MEDIA_FALLBACK_PID:-}" ]]; then
    kill "${MEDIA_FALLBACK_PID}" 2>/dev/null || true
    wait "${MEDIA_FALLBACK_PID}" 2>/dev/null || true
  fi
  if [[ -n "${WEBCAST_NOVNC_PID:-}" ]]; then
    kill "${WEBCAST_NOVNC_PID}" 2>/dev/null || true
    wait "${WEBCAST_NOVNC_PID}" 2>/dev/null || true
  fi
  if [[ -n "${WEBCAST_X11VNC_PID:-}" ]]; then
    kill "${WEBCAST_X11VNC_PID}" 2>/dev/null || true
    wait "${WEBCAST_X11VNC_PID}" 2>/dev/null || true
  fi
  if [[ -n "${WEBCAST_XVFB_PID:-}" ]]; then
    kill "${WEBCAST_XVFB_PID}" 2>/dev/null || true
    wait "${WEBCAST_XVFB_PID}" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

wait_for_pulseaudio() {
  for _ in {1..50}; do
    if pactl info >/dev/null 2>&1; then
      return 0
    fi
    sleep 0.1
  done
  return 1
}

if ! wait_for_pulseaudio; then
  pulseaudio --daemonize=yes --exit-idle-time=-1 --disallow-exit --log-target=stderr || true
fi

if ! wait_for_pulseaudio; then
  echo "PulseAudio server did not start." >&2
  exit 1
fi

if ! pactl list short sinks | awk '{print $2}' | grep -Fxq "${PULSE_SINK_NAME}"; then
  pactl load-module module-null-sink \
    sink_name="${PULSE_SINK_NAME}" \
    sink_properties=device.description="${PULSE_SINK_NAME}" >/dev/null
fi

pactl set-default-sink "${PULSE_SINK_NAME}"
export PULSE_SINK="${PULSE_SINK_NAME}"

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
rm -f "${ACTIVE_PLAYER_URL_FILE}"
rm -f "${MEDIA_CANDIDATES_FILE}"

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

wait_for_playback_ready() {
  local deadline=$((SECONDS + PLAYBACK_READY_TIMEOUT_SECONDS))
  echo "WAITING_FOR_PLAYBACK_READY signal_file=${PLAYBACK_READY_FILE} timeout=${PLAYBACK_READY_TIMEOUT_SECONDS}s"
  while (( SECONDS < deadline )); do
    if [[ -f "${PLAYBACK_READY_FILE}" ]]; then
      echo "PLAYBACK_READY_CONFIRMED"
      return 0
    fi
    if ! kill -0 "${WEBCAST_PID}" 2>/dev/null; then
      echo "WEBCAST_EXITED_BEFORE_PLAYBACK_READY" >&2
      return 1
    fi
    sleep 1
  done
  echo "PLAYBACK_READY_TIMED_OUT" >&2
  return 1
}

if ! wait_for_playback_ready; then
  exit 1
fi

sleep "${WEBCAST_WARMUP_SECONDS}"

start_youtube_audio_fallback() {
  local active_url
  local stream_url
  if [[ ! -s "${ACTIVE_PLAYER_URL_FILE}" ]]; then
    return 0
  fi
  active_url="$(head -n 1 "${ACTIVE_PLAYER_URL_FILE}")"
  if [[ ! "${active_url}" =~ ^https?://([^/]+\.)?(youtube\.com|youtu\.be)/ ]]; then
    return 0
  fi
  if ! command -v yt-dlp >/dev/null 2>&1 || ! command -v ffplay >/dev/null 2>&1; then
    echo "YOUTUBE_PULSE_FALLBACK_UNAVAILABLE" >&2
    return 0
  fi
  stream_url="$(
    timeout 30 yt-dlp \
      --no-playlist --no-warnings --no-progress \
      -f bestaudio -g "${active_url}" 2>/tmp/ew-yt-dlp.log \
      | head -n 1 || true
  )"
  if [[ -z "${stream_url}" ]]; then
    echo "YOUTUBE_PULSE_FALLBACK_RESOLVE_FAILED" >&2
    return 0
  fi
  while read -r sink_input _; do
    if [[ -n "${sink_input}" ]]; then
      pactl set-sink-input-mute "${sink_input}" 1 || true
    fi
  done < <(pactl list short sink-inputs)
  PULSE_SINK="${PULSE_SINK_NAME}" \
    ffplay -nodisp -autoexit -loglevel error \
      -ss "${YOUTUBE_FALLBACK_SEEK_SECONDS}" "${stream_url}" \
      >/tmp/ew-youtube-ffplay.log 2>&1 &
  YOUTUBE_FALLBACK_PID="$!"
  sleep 2
  if kill -0 "${YOUTUBE_FALLBACK_PID}" 2>/dev/null; then
    echo "YOUTUBE_PULSE_FALLBACK_STARTED seek=${YOUTUBE_FALLBACK_SEEK_SECONDS}s"
  else
    echo "YOUTUBE_PULSE_FALLBACK_START_FAILED" >&2
  fi
}

start_youtube_audio_fallback

start_media_stream_fallback() {
  local stream_url
  if [[ ! -s "${MEDIA_CANDIDATES_FILE}" ]]; then
    return 1
  fi

  stream_url="$(python -c 'import json,sys; values=json.load(open(sys.argv[1])); extensions=(".m3u8", ".mpd", ".mp4", ".m4a", ".mp3", ".aac", ".wav"); print(next((value for value in values if any(extension in value.lower() for extension in extensions)), ""))' "${MEDIA_CANDIDATES_FILE}" 2>/dev/null || true)"
  if [[ ! "${stream_url}" =~ ^https?:// ]]; then
    return 1
  fi

  echo "MEDIA_PULSE_FALLBACK_STARTING"
  PULSE_SINK="${PULSE_SINK_NAME}" \
    ffmpeg -hide_banner -loglevel error -nostdin \
      -i "${stream_url}" -vn -f pulse "${PULSE_SINK_NAME}" \
      >/tmp/ew-media-pulse-fallback.log 2>&1 &
  MEDIA_FALLBACK_PID="$!"
  sleep 2
  if ! kill -0 "${MEDIA_FALLBACK_PID}" 2>/dev/null; then
    echo "MEDIA_PULSE_FALLBACK_START_FAILED" >&2
    return 1
  fi
  echo "MEDIA_PULSE_FALLBACK_STARTED"
  return 0
}

wait_for_audio() {
  local deadline=$((SECONDS + AUDIO_WAIT_SECONDS))
  local probe_output
  local max_volume

  while (( SECONDS < deadline )); do
    if ! kill -0 "${WEBCAST_PID}" 2>/dev/null; then
      echo "WEBCAST_EXITED_BEFORE_AUDIO" >&2
      return 1
    fi

    probe_output="$(
      timeout "$((AUDIO_PROBE_SECONDS + 5))" \
        ffmpeg -hide_banner -nostdin -t "${AUDIO_PROBE_SECONDS}" \
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

  echo "AUDIO_NOT_DETECTED within=${AUDIO_WAIT_SECONDS}s threshold=${AUDIO_MIN_DB}dB" >&2
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
  if start_media_stream_fallback && wait_for_audio; then
    echo "AUDIO_DETECTED source=media-stream-fallback"
  else
    record_recipe_outcome failure "PulseAudio monitor did not receive audible webcast output"
    exit 1
  fi
fi

record_recipe_outcome success

if awk -v seconds="${SUCCESS_HOLD_SECONDS}" 'BEGIN { exit !(seconds > 0) }'; then
  echo "HOLDING_SUCCESS_SCREEN seconds=${SUCCESS_HOLD_SECONDS}"
  sleep "${SUCCESS_HOLD_SECONDS}"
fi

if [[ "${PROBE_ONLY}" == "true" ]]; then
  exit 0
fi

python -m data_pipeline.stt_worker.take \
  --ticker "${TICKER}" \
  --call-id "${CALL_ID}" \
  --input-kind device \
  --input-format pulse \
  --input-source "${PULSE_MONITOR}" \
  "$@"
