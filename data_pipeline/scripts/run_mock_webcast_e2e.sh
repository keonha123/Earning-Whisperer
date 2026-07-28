#!/usr/bin/env bash
set -euo pipefail

PORT="${MOCK_WEBCAST_PORT:-8787}"
ARGS=(--port "${PORT}")
if [[ "${MOCK_WEBCAST_CLEANUP:-false}" == "true" ]]; then
  ARGS+=(--cleanup)
fi
ARGS+=("$@")

python -m data_pipeline.tools.mock.mock_webcast_e2e "${ARGS[@]}"
