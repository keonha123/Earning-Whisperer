#!/usr/bin/env bash
set -euo pipefail

python -m data_pipeline.scripts.ensure_runtime_schema "$@"
