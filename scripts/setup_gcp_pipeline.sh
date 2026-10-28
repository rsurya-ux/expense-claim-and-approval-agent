#!/usr/bin/env bash
# Copyright 2026 Google LLC
# Licensed under the Apache License, Version 2.0
# Sets up Google Cloud Pub/Sub topics, IAM permissions, and Push Subscription for Agent Runtime.

set -euo pipefail

PROJECT_ID="${GOOGLE_CLOUD_PROJECT:-surya-kaggle-day1b-project}"
REGION="${GOOGLE_CLOUD_REGION:-us-central1}"
REASONING_ENGINE_ID="${1:-4814069000583512064}"

echo "=========================================================="
echo "Configuring GCP Pub/Sub & IAM for Expense Approval Agent"
echo "Project:          ${PROJECT_ID}"
echo "Region:           ${REGION}"
echo "Reasoning Engine: ${REASONING_ENGINE_ID}"
echo "=========================================================="

# 1. Create Topics
echo "[1/4] Ensuring Pub/Sub topics exist..."
gcloud pubsub topics create expense-reports --project="${PROJECT_ID}" 2>/dev/null || echo "Topic 'expense-reports' already exists."
gcloud pubsub topics create expense-reports-dead-letter --project="${PROJECT_ID}" 2>/dev/null || echo "Topic 'expense-reports-dead-letter' already exists."

# 2. Service Account for Push Auth
echo "[2/4] Ensuring invoker service account exists..."
SA_NAME="pubsub-invoker"
SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

gcloud iam service-accounts create "${SA_NAME}" \
  --display-name="Pub/Sub Push Agent Runtime Invoker" \
  --project="${PROJECT_ID}" 2>/dev/null || echo "Service account ${SA_NAME} already exists."

# Grant Vertex AI user role so Pub/Sub can invoke the Reasoning Engine
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/aiplatform.user" \
  --condition=None --quiet

# 3. Create / Recreate Push Subscription
echo "[3/4] Configuring push subscription pointing to Reasoning Engine..."
PUSH_ENDPOINT="https://${REGION}-aiplatform.googleapis.com/v1beta1/projects/${PROJECT_ID}/locations/${REGION}/reasoningEngines/${REASONING_ENGINE_ID}:query"

gcloud pubsub subscriptions delete expense-reports-push --project="${PROJECT_ID}" --quiet 2>/dev/null || true

gcloud pubsub subscriptions create expense-reports-push \
  --topic=expense-reports \
  --push-endpoint="${PUSH_ENDPOINT}" \
  --push-auth-service-account="${SA_EMAIL}" \
  --push-no-wrapper \
  --dead-letter-topic=expense-reports-dead-letter \
  --max-delivery-attempts=5 \
  --ack-deadline=60 \
  --project="${PROJECT_ID}"

echo "[4/4] Pipeline configured successfully!"
echo "Push Subscription: expense-reports-push -> ${PUSH_ENDPOINT}"
