#!/usr/bin/env bash
# Copyright 2026 Google LLC
# Licensed under the Apache License, Version 2.0

set -euo pipefail

PROJECT_ID="${GOOGLE_CLOUD_PROJECT:-surya-kaggle-day1b-project}"
TOPIC_NAME="expense-reports"

echo "=========================================================="
echo "Publishing test expense reports to Pub/Sub topic: ${TOPIC_NAME}"
echo "Project: ${PROJECT_ID}"
echo "=========================================================="

echo ""
echo "[1/2] Submitting $45 Auto-Approved Expense (Threshold < $100)..."
gcloud pubsub topics publish "${TOPIC_NAME}" \
  --project="${PROJECT_ID}" \
  --message='{"input": {"message": "{\"amount\": 45, \"submitter\": \"bob@company.com\", \"category\": \"meals\", \"description\": \"Team lunch\", \"date\": \"2026-04-12\"}"}}'

echo ""
echo "[2/2] Submitting $250 Human-in-the-Loop Review Expense (Threshold >= $100)..."
gcloud pubsub topics publish "${TOPIC_NAME}" \
  --project="${PROJECT_ID}" \
  --message='{"input": {"message": "{\"amount\": 250, \"submitter\": \"alice@company.com\", \"category\": \"travel\", \"description\": \"NYC Flight Tickets\", \"date\": \"2026-04-12\"}"}}'

echo ""
echo "Test messages successfully published to ${TOPIC_NAME}!"
echo "Check Reasoning Engine logs with:"
echo "  gcloud logging read 'resource.type=\"aiplatform.googleapis.com/ReasoningEngine\"' --limit=20 --project=${PROJECT_ID}"
