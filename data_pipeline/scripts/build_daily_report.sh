#!/usr/bin/env bash
set -euo pipefail

python -m data_pipeline.operations "$@"
