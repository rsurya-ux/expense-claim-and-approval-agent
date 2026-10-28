# Ambient Expense Claim & Approval Agent 🚀

[![Live Demo](https://img.shields.io/badge/Live_Demo-GitHub_Pages-brightgreen.svg)](https://rsurya-ux.github.io/expense-claim-and-approval-agent/)
[![Google ADK 2.0](https://img.shields.io/badge/Google_ADK-2.0-blue.svg)](https://cloud.google.com/vertex-ai)
[![Vertex AI Reasoning Engine](https://img.shields.io/badge/Vertex_AI-Reasoning_Engine-4285F4.svg)](https://cloud.google.com/vertex-ai/docs/reasoning-engine/overview)
[![Cloud Run](https://img.shields.io/badge/Google_Cloud_Run-FastAPI-success.svg)](https://cloud.google.com/run)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%20%7C%203.12-blue)](https://www.python.org/)

An ambient enterprise expense processing system powered by **Google Agent Development Kit (ADK 2.0)**, **Vertex AI Reasoning Engine**, and a **Human-in-the-Loop (HITL) Manager Approval Dashboard** on Cloud Run.

> 🌐 **Live Interactive Web Demo:** Experience the ambient agent workflow and manager review gateway live in your browser:  
> **[https://rsurya-ux.github.io/expense-claim-and-approval-agent/](https://rsurya-ux.github.io/expense-claim-and-approval-agent/)**

---

## 🌟 Key Features

- **Ambient Event-Driven Architecture:** Ingests expenses asynchronously via Google Cloud Pub/Sub topics.
- **Automated Policy Decisions:**
  - **Auto-Approval:** Expenses **&le; $50** (e.g. daily team lunches) are automatically validated, policy-checked, and approved with instant zero-touch execution.
  - **Human-in-the-Loop (HITL):** Expenses **> $50** (e.g. flight tickets, equipment purchases) are flagged and routed to the manager queue.
- **Glassmorphism Manager Dashboard:** Modern, responsive FastAPI web dashboard hosted on Cloud Run for finance managers to inspect, approve, or reject flagged claims.
- **Robust Adapter Pattern:** Seamlessly translates raw Pub/Sub push HTTP requests (`--push-no-wrapper`) into ADK streaming execution workflows.
- **Enterprise-Grade Observability:** Cloud Logging and Cloud Trace integration for end-to-end auditability.

---

## 📂 Repository Layout

```
expense-claim-and-approval-agent/
├── backend/                       # ADK 2.0 Agent Backend
│   ├── app/
│   │   ├── agent.py               # Graph Workflow state machine & policy nodes
│   │   ├── fast_api_app.py        # Local / Containerized FastAPI entrypoint
│   │   └── app_utils/
│   │       ├── reasoning_engine_adapter.py  # Push adapter for Reasoning Engine
│   │       ├── services.py        # External service hooks
│   │       └── a2a.py             # Agent-to-Agent protocol utilities
│   ├── deployment/                # Terraform infrastructure definitions
│   ├── tests/                     # Unit, Integration, and Eval datasets
│   │   ├── unit/                  # Workflow step unit tests (pytest)
│   │   ├── integration/           # E2E server integration tests
│   │   └── eval/                  # Quality evaluation datasets & configs
│   ├── pyproject.toml
│   └── Dockerfile
│
├── frontend/                      # Manager HITL Approval Dashboard
│   ├── main.py                    # Dark glassmorphism dashboard server
│   ├── Dockerfile                 # Cloud Run container definition
│   ├── requirements.txt
│   └── pyproject.toml
│
├── scripts/                       # Automation & Testing Tooling
│   ├── setup_gcp_pipeline.sh      # Provisions Pub/Sub, IAM & Push Subscriptions
│   ├── publish_test_expenses.sh   # Submits $45 auto and $250 review test events
│   ├── run_local_backend.sh       # Launches backend on port 8080
│   └── run_local_frontend.sh      # Launches dashboard on port 8081
│
├── ARCHITECTURE.md                # System diagrams & execution flow
├── .gitignore                     # Clean repository ignore rules
└── README.md                      # Documentation
```

---

## 🛠️ Quickstart: Local Development

### 1. Prerequisites
- Python 3.11 or 3.12
- [`uv`](https://docs.astral.sh/uv/) package manager
- Google Cloud SDK (`gcloud`) authenticated to your GCP project

### 2. Run Backend Tests
Run the pytest test suite covering workflow policy execution:

```bash
cd backend
uv run pytest tests/unit
```

### 3. Start Backend Locally
```bash
./scripts/run_local_backend.sh
# Server starts at http://localhost:8080
```

### 4. Start Manager Dashboard Locally
```bash
./scripts/run_local_frontend.sh
# Dashboard accessible at http://localhost:8081
```

---

## ☁️ Google Cloud Deployment

### 1. Deploy Agent to Vertex AI Reasoning Engine
Deploy using `agents-cli` or Vertex AI SDK:
```bash
cd backend
agents-cli deploy reasoning-engine --project <PROJECT_ID> --region us-central1
```

### 2. Deploy Manager Dashboard to Cloud Run
```bash
cd frontend
gcloud run deploy expense-manager-dashboard \
  --source . \
  --region us-central1 \
  --allow-unauthenticated \
  --project <PROJECT_ID>
```

### 3. Configure Event Pipeline (Pub/Sub + IAM)
Run the automated setup script with your Reasoning Engine ID:
```bash
./scripts/setup_gcp_pipeline.sh <REASONING_ENGINE_ID>
```

---

## 🧪 Testing the End-to-End Flow

Submit test expense reports directly into the Pub/Sub pipeline:

```bash
./scripts/publish_test_expenses.sh
```

### Verification Scenarios:
1. **$45 Team Lunch (Auto-Approval):**
   - Published payload: `{"amount": 45, "submitter": "bob@company.com", "category": "meals"}`
   - **Expected Outcome:** Reasoning Engine processes event and completes with `200 OK`. No manager intervention required.
2. **$250 NYC Flight Tickets (Manager Review):**
   - Published payload: `{"amount": 250, "submitter": "alice@company.com", "category": "travel"}`
   - **Expected Outcome:** Policy flag triggers. Item appears on the Human-in-the-Loop manager dashboard for approval.

Monitor real-time execution in Cloud Logging:
```bash
gcloud logging read 'resource.type="aiplatform.googleapis.com/ReasoningEngine"' --limit=20
```

---

## 📄 License
Licensed under the Apache License, Version 2.0. See the LICENSE details in Google ADK templates.
