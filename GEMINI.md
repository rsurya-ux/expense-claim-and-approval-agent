# Expense Claim & Approval Agent — System & Agent Guidance

This document defines the agent architecture, domain rules, guardrails, and operational constraints for the **Expense Claim & Approval Agent** (`expense_agent`), built with Google Agent Development Kit (ADK 2.0) and deployed on Google Cloud Vertex AI Reasoning Engine.

---

## 1. Agent Overview & Purpose

The `expense_agent` is an ambient, event-driven intelligent corporate expense auditing service. It continuously ingests expense submissions via Google Cloud Pub/Sub, validates business expense compliance, executes autonomous approvals for low-value transactions, and seamlessly pauses high-value claims for Human-in-the-Loop (HITL) manager sign-off.

- **Framework:** Google ADK (Agent Development Kit) 2.0 Graph Workflow (`Workflow`, `@node`, `InMemoryRunner` / `VertexAiSessionService`)
- **Execution Target:** Vertex AI Reasoning Engine (Agent Runtime)
- **Ingestion:** Cloud Pub/Sub Push Subscription with `--push-no-wrapper`
- **HITL Dashboard:** FastAPI service deployed on Google Cloud Run

---

## 2. Core Business Policy Rules & Thresholds

### A. Autonomous Approval Rule (< $100.00)
- Any valid business expense strictly under **$100.00** (e.g., $15.00 coffee, $45.00 team lunch, $85.50 office supplies) is **automatically approved** without requiring manager intervention.
- The agent immediately produces an `ExpenseDecision` payload:
  ```json
  {
    "status": "APPROVED",
    "approver": "auto_approve_policy",
    "note": "Instantly approved: claim is under the $100 threshold."
  }
  ```
- Returns HTTP `200 OK` to acknowledge the Pub/Sub event immediately.

### B. Human-in-the-Loop Review Rule (>= $100.00)
- Any expense claim of **$100.00 or more** (e.g., $250.00 flights, $1,250.00 laptops) triggers an intentional workflow pause.
- The agent yields an `adk_request_input` interrupt with `interruptId="manager_review"`.
- The session state stores `pending_claim` details while awaiting manager interaction via the HITL Dashboard.

### C. Resume & Decision Repair Guardrails
- **Valid Approvals:** Tokens such as `yes`, `y`, `approve`, `approved`, or structured payload `{"approved": true}` transition the claim to `status: "APPROVED"` with `approver: "manager_review"`.
- **Valid Rejections:** Tokens such as `no`, `n`, `reject`, `rejected`, or `{"approved": false}` transition the claim to `status: "REJECTED"` with `approver: "manager_review"`.
- **Ambiguous Response Repair:** Unrecognized or malformed inputs (e.g., `"yesyes"`, `"maybe"`, random text) **MUST NEVER** default to $0 or accidentally auto-approve. The agent re-prompts the user clearly, maintaining the paused state until an unambiguous decision is provided.

---

## 3. Workflow Graph Topology

```
[Incoming Payload] ──> classify_expense (Node)
                              │
            ┌─────────────────┴─────────────────┐
            │                                   │
      amount < $100.00                   amount >= $100.00
            │                                   │
            ▼                                   ▼
    auto_approve (Node)                 review_agent (Node)
            │                                   │
   [Status: APPROVED]                   [adk_request_input]
                                                │
                                        (Manager Decision)
                                                │
                                                ▼
                                    [APPROVED / REJECTED]
```

- **Resumability:** Configured with `ResumabilityConfig(is_resumable=True)` so workflow state survives process restarts and can be resumed across distributed workers.
- **ASGI Adapter Pattern:** `app/app_utils/reasoning_engine_adapter.py` bridges standard FastAPI and Vertex AI Reasoning Engine schemas, resolving method calls dynamically when invocations arrive via Pub/Sub push endpoints.

---

## 4. Evaluation & Quality Flywheel Guidelines

- **Evaluation Directory:** `tests/eval/`
- **Config:** `tests/eval/eval_config.yaml`
- **Dataset:** `tests/eval/datasets/basic-dataset.json`
- **Running Evals:**
  ```bash
  uv run pytest tests/unit tests/integration
  agents-cli eval run
  ```
- All evaluation cases must have verifiable ground truth matching the `< $100.00` auto-approve and `>= $100.00` review policy.
