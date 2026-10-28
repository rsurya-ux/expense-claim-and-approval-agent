#!/usr/bin/env bash
# Copyright 2026 Google LLC
# Starts the Expense Agent FastAPI backend locally.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(cd "${SCRIPT_DIR}/../backend" && pwd)"

cd "${BACKEND_DIR}"
echo "Starting Expense Agent backend on http://127.0.0.1:8080 ..."
uv run uvicorn app.fast_api_app:app --host 0.0.0.0 --port 8080 --reload
