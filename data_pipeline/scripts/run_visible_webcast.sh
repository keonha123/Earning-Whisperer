#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"
PYTHON_BIN="${REPO_ROOT}/data_pipeline/.venv/bin/python"

if [[ ! -x "${PYTHON_BIN}" ]]; then
  echo "data_pipeline virtual environment is missing: ${PYTHON_BIN}" >&2
  exit 1
fi

cd "${REPO_ROOT}"
exec "${PYTHON_BIN}" -m data_pipeline.tools.debug.visible_webcast "$@"
