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

## 🌟 Key Capabilities & Policy Rules

- **Ambient Event-Driven Ingestion:** Ingests expenses asynchronously via Google Cloud Pub/Sub topics.
- **Automated Policy Enforcement:**
  - **Auto-Approval:** Claims strictly **< $100.00** (e.g., $15 coffee, $45 team lunch, $85 office supplies) are validated and approved automatically with zero human intervention.
  - **Human-in-the-Loop (HITL):** Claims **&ge; $100.00** (e.g., $250 flights, $1,250 hardware) pause via ADK interrupts and route to the manager queue.
- **Enterprise Agent Constitution:** Governed by an immutable system prompt enforcing fiscal responsibility, anti-fraud compliance, and privacy rules.
- **Strategic Tiered Model Routing:** Dynamically routes routine claims to `gemini-2.5-flash` and high-value / disputed claims to `gemini-2.5-pro` for deep reasoning.
- **Active Runtime Guardrails:** Intercepts and screens inputs for adversarial prompt injections, negative amounts, and invalid parameters before workflow dispatch.
- **Context Compaction & Async Memory:** Automatically compacts long conversation histories into structured summaries and asynchronously updates employee spend ledgers in the background.
- **Structured JSON Logging & PII Redaction:** Emits RFC-compliant Google Cloud structured logs with explicit **Intent vs. Outcome** tracking and automatic redaction of credit cards, SSNs, and emails.
- **Glassmorphism Manager Dashboard:** Modern, responsive FastAPI web dashboard hosted on Cloud Run for finance managers to inspect, approve, or reject flagged claims.
- **Robust Adapter Pattern:** Seamlessly translates raw Pub/Sub push HTTP requests (`--push-no-wrapper`) into ADK streaming execution workflows (`app/app_utils/reasoning_engine_adapter.py`).
- **Resilient Memory & State:** Backed by ADK resumable state machine (`ResumabilityConfig(is_resumable=True)`), surviving container recycles and network interrupts.
- **Evaluation & Quality Flywheel:** Built-in evaluation dataset in `tests/eval/` matching the Gemini platform evaluation methodology.

---

## 📂 Repository Layout

```
expense-claim-and-approval-agent/
├── app/                           # Core ADK 2.0 Graph Workflow Agent
│   ├── agent.py                   # State machine graph & approval policy nodes
│   ├── fast_api_app.py            # Local & containerized ASGI application
│   └── app_utils/
│       ├── reasoning_engine_adapter.py  # Push adapter for Reasoning Engine
│       ├── services.py            # External service hooks
│       └── a2a.py                 # Agent-to-Agent protocol utilities
├── dashboard/                     # Manager HITL Approval Dashboard (FastAPI)
│   ├── main.py                    # Dark glassmorphism dashboard server
│   ├── Dockerfile                 # Cloud Run container definition
│   ├── requirements.txt
│   └── pyproject.toml
├── deployment/                    # Terraform single-project & telemetry infrastructure
├── tests/                         # Full Pytest test suite
│   ├── unit/                      # Policy, boundary ($99 vs $100), and repair tests
│   ├── integration/               # E2E server integration tests
│   └── eval/                      # Evaluation dataset & quality config
│       ├── eval_config.yaml
│       ├── response_quality.py
│       └── datasets/
│           └── basic-dataset.json
├── scripts/                       # Automation & Testing Tooling
│   ├── setup_gcp_pipeline.sh      # Provisions Pub/Sub, IAM & Push Subscriptions
│   ├── publish_test_expenses.sh   # Submits test events ($45 auto vs $250 review)
│   ├── run_local_backend.sh       # Launches backend on port 8080
│   └── run_local_frontend.sh      # Launches dashboard on port 8081
├── agents-cli-manifest.yaml       # Project manifest for agents-cli
├── Dockerfile                     # Backend container definition
├── pyproject.toml                 # Project metadata & dependencies
├── GEMINI.md                      # System & domain agent specification
├── ARCHITECTURE.md                # System diagrams & execution flow
├── index.html                     # Live client-side web showcase
└── README.md
```

---

## 🛠️ Quickstart: Local Development

### 1. Prerequisites
- Python 3.11 or 3.12
- [`uv`](https://docs.astral.sh/uv/) package manager
- Google Cloud SDK (`gcloud`) authenticated to your GCP project

### 2. Run Tests
```bash
# Run unit tests (8 passing tests covering boundaries & repair)
uv run pytest tests/unit -v

# Run integration tests
uv run pytest tests/integration -v
```

### 3. Run Evaluation Suite
```bash
agents-cli eval run
```

### 4. Start Local Services
```bash
# Start Agent Backend (http://localhost:8080)
./scripts/run_local_backend.sh

# Start Manager Dashboard (http://localhost:8081)
./scripts/run_local_frontend.sh
```

---

## ☁️ Google Cloud Deployment

### 1. Deploy Agent to Vertex AI Reasoning Engine
```bash
agents-cli deploy reasoning-engine --project <PROJECT_ID> --region us-central1
```

### 2. Deploy Manager Dashboard to Cloud Run
```bash
cd dashboard
gcloud run deploy expense-manager-dashboard \
  --source . \
  --region us-central1 \
  --allow-unauthenticated \
  --project <PROJECT_ID>
```

### 3. Configure Event Pipeline (Pub/Sub + IAM)
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
   - Amount < $100 threshold &rarr; Reasoning Engine validates and approves automatically with `200 OK`.
2. **$250 NYC Flight Tickets (Manager Review):**
   - Amount &ge; $100 threshold &rarr; Workflow pauses with `adk_request_input`. The claim appears on the Manager Dashboard for human approval.

Monitor real-time execution in Cloud Logging:
```bash
gcloud logging read 'resource.type="aiplatform.googleapis.com/ReasoningEngine"' --limit=20
```

---

## 📄 License
Licensed under the Apache License, Version 2.0.
