#!/usr/bin/env bash
# Copyright 2026 Google LLC
# Starts the Human-in-the-Loop Expense Manager Dashboard locally.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FRONTEND_DIR="$(cd "${SCRIPT_DIR}/../frontend" && pwd)"

cd "${FRONTEND_DIR}"
echo "Starting Manager Dashboard frontend on http://127.0.0.1:8081 ..."
uv run uvicorn main:app --host 0.0.0.0 --port 8081 --reload
