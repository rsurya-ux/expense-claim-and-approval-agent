# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Standalone Manager Dashboard Service for Ambient Expense Agent."""

import asyncio
import logging
import os
import re
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from google.adk.sessions import VertexAiSessionService
from pydantic import BaseModel

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("manager_dashboard")

load_dotenv()

# GCP & Agent Runtime Configuration from Environment
PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT", "surya-kaggle-day1b-project")
LOCATION = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
AGENT_RUNTIME_ID = os.getenv(
    "AGENT_RUNTIME_ID",
    "projects/304616680887/locations/us-central1/reasoningEngines/4814069000583512064",
)
APP_NAME = os.getenv("APP_NAME", "app")

# Extract numeric ID for SessionService if full resource path was provided
ENGINE_NUMERIC_ID = (
    AGENT_RUNTIME_ID.split("/")[-1] if "/" in AGENT_RUNTIME_ID else AGENT_RUNTIME_ID
)

app = FastAPI(
    title="ExpenseOps Manager Dashboard",
    description="Human-in-the-Loop approval gateway for ambient expense agents.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_session_service() -> VertexAiSessionService:
    """Returns an initialized ADK VertexAiSessionService instance."""
    return VertexAiSessionService(
        project=PROJECT_ID,
        location=LOCATION,
        agent_engine_id=ENGINE_NUMERIC_ID,
    )


def find_unresolved_request_input(session: Any) -> Optional[Dict[str, Any]]:
    """Identifies unresolved adk_request_input function calls in a session history.

    A request is considered resolved if:
    1. The session state already has an approval_decision and pending_claim is None, OR
    2. An adk_request_input function_call is answered by a function_response or approval event.
    """
    state = getattr(session, "state", {}) or {}

    # Check 1: Already decided in session state
    if state.get("approval_decision") and state.get("pending_claim") is None:
        return None

    # Check 2: Scan events for final approval/rejection event
    for event in reversed(session.events):
        output = getattr(event, "output", None)
        if isinstance(output, dict) and output.get("approver") == "manager_review":
            return None
        event_state = getattr(event, "state", None) or {}
        if event_state.get("approval_decision") and event_state.get("pending_claim") is None:
            return None

    # Check 3: Match adk_request_input function_call against function_response
    pending_calls: Dict[str, Dict[str, Any]] = {}

    for event in session.events:
        content = getattr(event, "content", None)
        if not content:
            continue
        parts = getattr(content, "parts", []) or []
        for part in parts:
            fc = getattr(part, "function_call", None)
            fr = getattr(part, "function_response", None)

            if fc and getattr(fc, "name", "") == "adk_request_input":
                args = getattr(fc, "args", {}) or {}
                interrupt_id = args.get("interruptId") or "manager_review"
                payload = args.get("payload") or {}
                message = args.get("message") or ""
                pending_calls[interrupt_id] = {
                    "session_id": session.id,
                    "user_id": session.user_id,
                    "interrupt_id": interrupt_id,
                    "payload": payload,
                    "message": message,
                    "timestamp": getattr(event, "timestamp", None),
                }
            elif fr and getattr(fr, "name", "") == "adk_request_input":
                interrupt_id = getattr(fr, "id", None) or "manager_review"
                pending_calls.pop(interrupt_id, None)

    if not pending_calls:
        return None

    # Retrieve the most recent unresolved pending request
    latest = list(pending_calls.values())[-1]
    payload = latest.get("payload") or {}

    amount = payload.get("amount")
    description = payload.get("description")

    # Fallback to session state if values were omitted from payload
    if amount is None or description is None:
        claim = state.get("pending_claim") or state.get("current_claim") or {}
        amount = amount or claim.get("amount")
        description = description or claim.get("description")

    # Fallback: regex search from message string
    if amount is None:
        match = re.search(r"\$([0-9]+(?:\.[0-9]{1,2})?)", latest.get("message", ""))
        amount = float(match.group(1)) if match else 100.0

    latest["amount"] = float(amount or 0.0)
    latest["description"] = str(description or "Corporate Expense Claim")
    return latest


class ActionRequest(BaseModel):
    approved: bool = True
    comment: Optional[str] = None
    interrupt_id: Optional[str] = "manager_review"


class TestExpenseRequest(BaseModel):
    amount: float = 250.0
    description: str = "Conference ticket & travel accommodations"


@app.get("/api/config")
async def get_config():
    """Returns deployment connection information."""
    return {
        "project_id": PROJECT_ID,
        "location": LOCATION,
        "agent_runtime_id": AGENT_RUNTIME_ID,
        "engine_numeric_id": ENGINE_NUMERIC_ID,
        "app_name": APP_NAME,
    }


@app.get("/api/pending")
async def list_pending_approvals():
    """Queries ADK VertexAiSessionService to list all sessions, fetches full history,

    and identifies unresolved adk_request_input events.
    """
    try:
        svc = get_session_service()
        list_resp = await svc.list_sessions(app_name=APP_NAME)
        sessions = list_resp.sessions or []
    except Exception as e:
        logger.error(f"Error querying session service: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": str(e), "pending": [], "total": 0},
        )

    # Concurrently inspect full session histories
    async def inspect(s):
        try:
            full_session = await svc.get_session(
                app_name=APP_NAME,
                user_id=s.user_id,
                session_id=s.id,
            )
            if not full_session or not full_session.events:
                return None
            return find_unresolved_request_input(full_session)
        except Exception as ex:
            logger.warning(f"Could not load events for session {s.id}: {ex}")
            return None

    results = await asyncio.gather(
        *(inspect(s) for s in sessions), return_exceptions=True
    )
    pending_list = [r for r in results if r and not isinstance(r, Exception)]

    # Sort descending by event timestamp
    pending_list.sort(key=lambda x: x.get("timestamp") or 0, reverse=True)
    return {"pending": pending_list, "total": len(pending_list)}


@app.post("/api/action/{session_id}")
async def handle_approval_action(session_id: str, action: ActionRequest):
    """Resumes the paused session on Agent Runtime.

    Passes resume payload directly as dict value of message argument.
    Matches the session's owner user_id to prevent ownership mismatch errors.
    """
    import json
    from google.cloud import aiplatform_v1

    # Look up session owner (vais-query-reasoning-engine from Console or default-user from SDK)
    target_user_id = "default-user"
    try:
        svc = get_session_service()
        list_resp = await svc.list_sessions(app_name=APP_NAME)
        for s in list_resp.sessions or []:
            if s.id == session_id and s.user_id:
                target_user_id = s.user_id
                break
    except Exception as ex:
        logger.warning(f"Could not check session owner: {ex}")

    client = aiplatform_v1.ReasoningEngineExecutionServiceClient(
        client_options={"api_endpoint": f"{LOCATION}-aiplatform.googleapis.com"}
    )

    interrupt_id = action.interrupt_id or "manager_review"
    comment_text = (
        action.comment
        or ("Manager Approved" if action.approved else "Manager Rejected")
    )

    resume_payload = {
        "role": "user",
        "parts": [
            {
                "function_response": {
                    "id": interrupt_id,
                    "name": "adk_request_input",
                    "response": {
                        "approved": action.approved,
                        "comment": comment_text,
                    },
                }
            }
        ],
    }

    input_payload = {
        "message": resume_payload,
        "user_id": target_user_id,
        "session_id": session_id,
    }

    stream_req = aiplatform_v1.StreamQueryReasoningEngineRequest(
        name=AGENT_RUNTIME_ID,
        class_method="stream_query",
        input=input_payload,
    )

    try:
        review_text = ""
        decision_data = None

        response_stream = client.stream_query_reasoning_engine(request=stream_req)
        for http_body in response_stream:
            raw_text = http_body.data.decode("utf-8")
            for line in raw_text.strip().split("\n"):
                if not line:
                    continue
                try:
                    event_json = json.loads(line)
                    cnt = event_json.get("content") or {}
                    parts = cnt.get("parts", []) if isinstance(cnt, dict) else []
                    for p in parts:
                        if isinstance(p, dict) and "text" in p:
                            review_text += p["text"]
                    if "output" in event_json and isinstance(event_json["output"], dict):
                        decision_data = event_json["output"]
                except Exception:
                    review_text += line

        if not review_text and decision_data:
            review_text = (
                f"### Review Decision: {decision_data.get('status', 'COMPLETED')}\n"
                f"- **Status:** {decision_data.get('status')}\n"
                f"- **Amount:** ${float(decision_data.get('amount', 0)):.2f}\n"
                f"- **Description:** {decision_data.get('description')}\n"
                f"- **Approver:** {decision_data.get('approver', 'manager_review')}\n"
            )

        return {
            "status": "success",
            "session_id": session_id,
            "approved": action.approved,
            "review_summary": review_text
            or (
                "Claim review successfully processed."
                if action.approved
                else "Claim rejected."
            ),
            "decision": decision_data,
        }
    except Exception as e:
        logger.error(f"Failed resuming session {session_id}: {e}")
        raise HTTPException(
            status_code=500, detail=f"Reasoning Engine error: {str(e)}"
        )


@app.post("/api/submit-expense")
async def submit_test_expense(req: TestExpenseRequest):
    """Convenience endpoint to submit a test claim directly to Agent Runtime."""
    from google.cloud import aiplatform_v1

    client = aiplatform_v1.ReasoningEngineExecutionServiceClient(
        client_options={"api_endpoint": f"{LOCATION}-aiplatform.googleapis.com"}
    )

    prompt = f"Submit expense of ${req.amount:.2f} for {req.description}"
    stream_req = aiplatform_v1.StreamQueryReasoningEngineRequest(
        name=AGENT_RUNTIME_ID,
        class_method="stream_query",
        input={"message": prompt, "user_id": "default-user"},
    )
    try:
        events = list(client.stream_query_reasoning_engine(request=stream_req))
        return {
            "status": "submitted",
            "prompt": prompt,
            "events_count": len(events),
        }
    except Exception as e:
        logger.error(f"Error submitting test expense: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/", response_class=HTMLResponse)
async def serve_dashboard():
    """Serves the polished, glassmorphism Manager Dashboard HTML page."""
    html_content = """<!DOCTYPE html>
<html lang="en" class="dark">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>ExpenseOps | Autonomous Manager Approval Gateway</title>
  
  <!-- Fonts: Outfit (headings) & Inter (body) -->
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=Outfit:wght@400;500;600;700;800&display=swap" rel="stylesheet">
  
  <!-- Tailwind CSS & Lucide Icons & Marked for Markdown Rendering -->
  <script src="https://cdn.tailwindcss.com"></script>
  <script src="https://unpkg.com/lucide@latest"></script>
  <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>

  <script>
    tailwind.config = {
      darkMode: 'class',
      theme: {
        extend: {
          fontFamily: {
            sans: ['Inter', 'sans-serif'],
            display: ['Outfit', 'sans-serif'],
          },
          colors: {
            brand: {
              50: '#eef2ff',
              400: '#818cf8',
              500: '#6366f1',
              600: '#4f46e5',
            }
          }
        }
      }
    }
  </script>

  <style>
    body {
      background-color: #07090e;
      background-image: 
        radial-gradient(circle at 15% 20%, rgba(99, 102, 241, 0.12) 0%, transparent 40%),
        radial-gradient(circle at 85% 15%, rgba(168, 85, 247, 0.10) 0%, transparent 45%),
        radial-gradient(circle at 50% 85%, rgba(16, 185, 129, 0.07) 0%, transparent 50%);
      background-attachment: fixed;
    }
    
    .glass-card {
      background: rgba(15, 23, 42, 0.65);
      backdrop-filter: blur(16px);
      -webkit-backdrop-filter: blur(16px);
      border: 1px solid rgba(255, 255, 255, 0.08);
      box-shadow: 0 10px 30px -10px rgba(0, 0, 0, 0.5);
    }
    
    .glass-nav {
      background: rgba(8, 12, 20, 0.80);
      backdrop-filter: blur(20px);
      border-bottom: 1px solid rgba(255, 255, 255, 0.07);
    }

    .pulse-dot {
      animation: pulseGlow 2s infinite;
    }
    @keyframes pulseGlow {
      0%, 100% { opacity: 1; transform: scale(1); }
      50% { opacity: 0.5; transform: scale(0.9); }
    }
    
    /* Markdown Styles for Review Output */
    .prose-custom h3 {
      font-family: 'Outfit', sans-serif;
      font-size: 1.25rem;
      font-weight: 700;
      color: #f8fafc;
      margin-bottom: 0.75rem;
    }
    .prose-custom ul {
      list-style-type: none;
      padding-left: 0;
      display: flex;
      flex-direction: column;
      gap: 0.5rem;
    }
    .prose-custom li {
      font-size: 0.95rem;
      color: #cbd5e1;
      padding-left: 0.25rem;
    }
    .prose-custom strong {
      color: #818cf8;
    }
  </style>
</head>

<body class="text-slate-100 min-h-screen flex flex-col font-sans antialiased selection:bg-brand-500 selection:text-white">

  <!-- TOP NAVIGATION -->
  <nav class="sticky top-0 z-40 glass-nav px-6 py-3.5">
    <div class="max-w-7xl mx-auto flex items-center justify-between">
      
      <!-- Brand Logo -->
      <div class="flex items-center space-x-3.5">
        <div class="w-10 h-10 rounded-xl bg-gradient-to-tr from-brand-600 to-violet-500 flex items-center justify-center shadow-lg shadow-indigo-500/25 border border-indigo-400/30">
          <i data-lucide="shield-check" class="w-5 h-5 text-white"></i>
        </div>
        <div>
          <div class="flex items-center space-x-2">
            <span class="font-display font-extrabold text-xl tracking-tight text-white">ExpenseOps</span>
            <span class="text-xs font-semibold px-2 py-0.5 rounded-full bg-indigo-500/10 text-indigo-400 border border-indigo-500/20">HITL Gateway</span>
          </div>
          <p class="text-xs text-slate-400 hidden sm:block">ADK 2.0 Autonomous Agent Approval Pipeline</p>
        </div>
      </div>

      <!-- Center / Right Status & Actions -->
      <div class="flex items-center space-x-3">
        <!-- Live Status Pill -->
        <div class="hidden md:flex items-center space-x-2 px-3 py-1.5 rounded-full bg-slate-900/80 border border-white/10 text-xs">
          <span class="w-2 h-2 rounded-full bg-emerald-400 pulse-dot"></span>
          <span class="text-slate-300 font-medium">Agent Runtime Live</span>
          <span class="text-slate-600">|</span>
          <span class="text-slate-400" id="location-badge">us-central1</span>
        </div>

        <!-- Sync Button -->
        <button onclick="fetchPendingApprovals(true)" id="refresh-btn" class="flex items-center space-x-2 px-3.5 py-1.5 rounded-lg bg-slate-800/80 hover:bg-slate-700/80 text-xs font-medium text-slate-200 border border-white/10 transition-all hover:border-indigo-500/40">
          <i data-lucide="refresh-cw" class="w-3.5 h-3.5" id="refresh-icon"></i>
          <span>Refresh</span>
        </button>

        <!-- New Test Claim Button -->
        <button onclick="openTestModal()" class="flex items-center space-x-2 px-3.5 py-1.5 rounded-lg bg-gradient-to-r from-brand-600 to-indigo-600 hover:from-brand-500 hover:to-indigo-500 text-xs font-medium text-white shadow-md shadow-indigo-600/20 border border-indigo-400/20 transition-all">
          <i data-lucide="plus-circle" class="w-3.5 h-3.5"></i>
          <span>Submit Claim</span>
        </button>
      </div>

    </div>
  </nav>

  <!-- MAIN CONTAINER -->
  <main class="flex-1 max-w-7xl w-full mx-auto px-6 py-8 space-y-8">
    
    <!-- STATS / POLICY RIBBON -->
    <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
      
      <!-- Card 1: Pending Approvals -->
      <div class="glass-card rounded-2xl p-5 relative overflow-hidden group">
        <div class="absolute -right-4 -bottom-4 w-24 h-24 bg-amber-500/10 rounded-full blur-xl group-hover:bg-amber-500/15 transition-all"></div>
        <div class="flex items-center justify-between">
          <span class="text-xs font-medium text-slate-400 uppercase tracking-wider">Awaiting Review</span>
          <span class="p-2 rounded-xl bg-amber-500/10 text-amber-400 border border-amber-500/20">
            <i data-lucide="clock" class="w-4 h-4"></i>
          </span>
        </div>
        <div class="mt-4 flex items-baseline space-x-2">
          <span class="font-display text-3xl font-bold text-white" id="pending-count">0</span>
          <span class="text-xs text-amber-400 font-medium">Claims Paused</span>
        </div>
      </div>

      <!-- Card 2: Threshold Policy -->
      <div class="glass-card rounded-2xl p-5 relative overflow-hidden group">
        <div class="absolute -right-4 -bottom-4 w-24 h-24 bg-indigo-500/10 rounded-full blur-xl group-hover:bg-indigo-500/15 transition-all"></div>
        <div class="flex items-center justify-between">
          <span class="text-xs font-medium text-slate-400 uppercase tracking-wider">Review Rule</span>
          <span class="p-2 rounded-xl bg-indigo-500/10 text-indigo-400 border border-indigo-500/20">
            <i data-lucide="sliders" class="w-4 h-4"></i>
          </span>
        </div>
        <div class="mt-4 flex items-baseline space-x-2">
          <span class="font-display text-2xl font-bold text-white">&ge; $100.00</span>
          <span class="text-xs text-slate-400">Human Sign-off</span>
        </div>
      </div>

      <!-- Card 3: Auto-Approved Policy -->
      <div class="glass-card rounded-2xl p-5 relative overflow-hidden group">
        <div class="absolute -right-4 -bottom-4 w-24 h-24 bg-emerald-500/10 rounded-full blur-xl group-hover:bg-emerald-500/15 transition-all"></div>
        <div class="flex items-center justify-between">
          <span class="text-xs font-medium text-slate-400 uppercase tracking-wider">Instant Approval</span>
          <span class="p-2 rounded-xl bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
            <i data-lucide="zap" class="w-4 h-4"></i>
          </span>
        </div>
        <div class="mt-4 flex items-baseline space-x-2">
          <span class="font-display text-2xl font-bold text-emerald-400">&lt; $100.00</span>
          <span class="text-xs text-slate-400">Autonomous</span>
        </div>
      </div>

      <!-- Card 4: Engine Info -->
      <div class="glass-card rounded-2xl p-5 relative overflow-hidden group">
        <div class="absolute -right-4 -bottom-4 w-24 h-24 bg-purple-500/10 rounded-full blur-xl group-hover:bg-purple-500/15 transition-all"></div>
        <div class="flex items-center justify-between">
          <span class="text-xs font-medium text-slate-400 uppercase tracking-wider">Reasoning Engine</span>
          <span class="p-2 rounded-xl bg-purple-500/10 text-purple-400 border border-purple-500/20">
            <i data-lucide="cpu" class="w-4 h-4"></i>
          </span>
        </div>
        <div class="mt-4">
          <span class="font-display text-sm font-semibold text-slate-200 block truncate" id="engine-id-badge">Engine #4814...</span>
          <span class="text-xs text-slate-400">Gemini 3.8 Flash ADK Graph</span>
        </div>
      </div>

    </div>

    <!-- PENDING APPROVALS QUEUE -->
    <div class="space-y-4">
      <div class="flex items-center justify-between">
        <div>
          <h2 class="font-display font-bold text-2xl text-white tracking-tight">Pending Manager Approvals</h2>
          <p class="text-sm text-slate-400">Interactive queue of expense claims paused at the human review checkpoint</p>
        </div>
        <div class="flex items-center space-x-2 text-xs text-slate-400">
          <label class="flex items-center space-x-2 cursor-pointer select-none">
            <input type="checkbox" id="auto-refresh-toggle" checked class="rounded border-slate-700 bg-slate-900 text-indigo-600 focus:ring-0">
            <span>Auto-refresh (8s)</span>
          </label>
        </div>
      </div>

      <!-- Loading State Skeleton -->
      <div id="loading-skeleton" class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        <div class="glass-card rounded-2xl p-6 h-64 animate-pulse flex flex-col justify-between">
          <div class="space-y-3">
            <div class="h-5 bg-slate-800 rounded w-1/3"></div>
            <div class="h-8 bg-slate-800 rounded w-1/2"></div>
            <div class="h-4 bg-slate-800 rounded w-3/4"></div>
          </div>
          <div class="h-10 bg-slate-800 rounded"></div>
        </div>
        <div class="glass-card rounded-2xl p-6 h-64 animate-pulse flex flex-col justify-between">
          <div class="space-y-3">
            <div class="h-5 bg-slate-800 rounded w-1/3"></div>
            <div class="h-8 bg-slate-800 rounded w-1/2"></div>
            <div class="h-4 bg-slate-800 rounded w-3/4"></div>
          </div>
          <div class="h-10 bg-slate-800 rounded"></div>
        </div>
      </div>

      <!-- Cards Grid -->
      <div id="cards-container" class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6 hidden">
        <!-- Rendered Dynamically by JS -->
      </div>

      <!-- Empty State -->
      <div id="empty-state" class="glass-card rounded-2xl p-12 text-center flex flex-col items-center justify-center space-y-4 border border-dashed border-white/10 hidden">
        <div class="w-16 h-16 rounded-2xl bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 flex items-center justify-center shadow-lg shadow-emerald-500/10">
          <i data-lucide="check-circle" class="w-8 h-8"></i>
        </div>
        <div class="space-y-1">
          <h3 class="font-display font-bold text-lg text-white">All Clear! No Pending Approvals</h3>
          <p class="text-sm text-slate-400 max-w-md">Standard claims under $100 are auto-approved. Claims meeting or exceeding $100 will automatically pause and appear here for your review.</p>
        </div>
        <button onclick="openTestModal()" class="mt-2 px-4 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-xs font-semibold text-slate-200 border border-white/10 transition-all flex items-center space-x-2">
          <i data-lucide="sparkles" class="w-3.5 h-3.5 text-indigo-400"></i>
          <span>Simulate $250 Expense Claim</span>
        </button>
      </div>

    </div>

  </main>

  <!-- MODAL / SLIDE-OUT DRAWER: DECISION COMPLIANCE RECEIPT -->
  <div id="decision-modal" class="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-md hidden transition-opacity duration-300">
    <div class="glass-card w-full max-w-xl rounded-3xl p-7 border border-white/15 shadow-2xl relative space-y-6 transform transition-all duration-300 scale-95" id="modal-card">
      
      <!-- Modal Header -->
      <div class="flex items-start justify-between">
        <div class="flex items-center space-x-3">
          <div id="modal-icon-badge" class="w-12 h-12 rounded-2xl flex items-center justify-center border shadow-lg">
            <i id="modal-icon" data-lucide="check" class="w-6 h-6"></i>
          </div>
          <div>
            <h3 class="font-display font-extrabold text-xl text-white tracking-tight" id="modal-title">Expense Review Completed</h3>
            <p class="text-xs text-slate-400" id="modal-subtitle">Autonomous reasoning engine audit record</p>
          </div>
        </div>
        <button onclick="closeDecisionModal()" class="p-2 rounded-xl bg-slate-800/80 hover:bg-slate-700 text-slate-400 hover:text-white transition-colors border border-white/10">
          <i data-lucide="x" class="w-4 h-4"></i>
        </button>
      </div>

      <!-- Modal Body / Agent Output -->
      <div class="p-5 rounded-2xl bg-slate-900/90 border border-white/5 space-y-4">
        <div class="text-xs text-slate-400 uppercase tracking-wider font-semibold">Agent Compliance Decision</div>
        <div id="modal-markdown" class="prose-custom text-sm text-slate-300"></div>
      </div>

      <!-- Modal Footer -->
      <div class="flex items-center justify-between pt-2 text-xs text-slate-400 border-t border-white/10">
        <div class="flex items-center space-x-1.5">
          <i data-lucide="lock" class="w-3.5 h-3.5 text-indigo-400"></i>
          <span>Signed by Manager HITL Node</span>
        </div>
        <button onclick="closeDecisionModal()" class="px-4 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-white font-medium transition-all">
          Dismiss
        </button>
      </div>

    </div>
  </div>

  <!-- TEST EXPENSE SUBMISSION MODAL -->
  <div id="test-modal" class="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-md hidden">
    <div class="glass-card w-full max-w-md rounded-3xl p-6 border border-white/15 shadow-2xl relative space-y-5">
      <div class="flex items-center justify-between">
        <div class="flex items-center space-x-2.5">
          <div class="p-2.5 rounded-xl bg-indigo-500/10 text-indigo-400 border border-indigo-500/20">
            <i data-lucide="file-plus" class="w-5 h-5"></i>
          </div>
          <div>
            <h3 class="font-display font-bold text-lg text-white">Create Test Expense</h3>
            <p class="text-xs text-slate-400">Inject a claim directly into Agent Runtime</p>
          </div>
        </div>
        <button onclick="closeTestModal()" class="p-2 rounded-xl bg-slate-800 text-slate-400 hover:text-white">
          <i data-lucide="x" class="w-4 h-4"></i>
        </button>
      </div>

      <div class="space-y-4">
        <div>
          <label class="block text-xs font-semibold uppercase tracking-wider text-slate-400 mb-1.5">Expense Amount ($)</label>
          <input type="number" id="test-amount" value="250.00" step="5" class="w-full px-3.5 py-2.5 rounded-xl bg-slate-900 border border-white/10 text-white focus:outline-none focus:border-indigo-500 text-sm font-semibold">
          <span class="text-[11px] text-slate-500 mt-1 block">&ge; $100 triggers human review; &lt; $100 auto-approves.</span>
        </div>
        <div>
          <label class="block text-xs font-semibold uppercase tracking-wider text-slate-400 mb-1.5">Description / Purpose</label>
          <input type="text" id="test-desc" value="Conference pass & accommodations" class="w-full px-3.5 py-2.5 rounded-xl bg-slate-900 border border-white/10 text-white focus:outline-none focus:border-indigo-500 text-sm">
        </div>
      </div>

      <div class="flex items-center justify-end space-x-3 pt-2">
        <button onclick="closeTestModal()" class="px-4 py-2 rounded-xl bg-slate-800 text-xs font-semibold text-slate-300 hover:bg-slate-700">Cancel</button>
        <button onclick="submitTestClaim()" id="submit-test-btn" class="px-4 py-2 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-xs font-semibold text-white flex items-center space-x-1.5">
          <span>Submit to Agent</span>
        </button>
      </div>
    </div>
  </div>

  <!-- TOAST NOTIFICATION -->
  <div id="toast" class="fixed bottom-6 right-6 z-50 flex items-center space-x-3 px-4 py-3 rounded-2xl glass-card border border-white/20 shadow-2xl text-xs font-medium text-white transition-all transform translate-y-20 opacity-0">
    <i data-lucide="info" id="toast-icon" class="w-4 h-4 text-indigo-400"></i>
    <span id="toast-msg">Notification</span>
  </div>

  <!-- CLIENT LOGIC -->
  <script>
    lucide.createIcons();

    let autoRefreshInterval = null;
    const resolvedSessionIds = new Set();

    // Fetch initial system config
    async function loadConfig() {
      try {
        const res = await fetch('/api/config');
        const cfg = await res.json();
        document.getElementById('location-badge').innerText = cfg.location;
        document.getElementById('engine-id-badge').innerText = `Engine #${cfg.engine_numeric_id.slice(-6)}`;
      } catch (err) {
        console.error('Config fetch failed:', err);
      }
    }

    // Fetch pending approvals
    async function fetchPendingApprovals(isManual = false) {
      const refreshIcon = document.getElementById('refresh-icon');
      if (refreshIcon) refreshIcon.classList.add('animate-spin');

      try {
        const res = await fetch('/api/pending');
        const data = await res.json();
        const pending = data.pending || [];
        
        renderPendingCards(pending);
        
        if (isManual) showToast(`Synced queue`);
      } catch (err) {
        console.error('Failed to fetch pending items:', err);
        showToast('Error syncing pending approvals', 'alert-circle');
      } finally {
        if (refreshIcon) setTimeout(() => refreshIcon.classList.remove('animate-spin'), 600);
      }
    }

    // Render cards
    function renderPendingCards(items) {
      const container = document.getElementById('cards-container');
      const emptyState = document.getElementById('empty-state');
      const skeleton = document.getElementById('loading-skeleton');

      skeleton.classList.add('hidden');

      const trulyPending = (items || []).filter(item => !resolvedSessionIds.has(item.session_id));
      document.getElementById('pending-count').innerText = trulyPending.length;

      if (!trulyPending || trulyPending.length === 0) {
        container.classList.add('hidden');
        emptyState.classList.remove('hidden');
        return;
      }

      emptyState.classList.add('hidden');
      container.classList.remove('hidden');

      container.innerHTML = trulyPending.map(item => {
        const amountFormatted = Number(item.amount || 0).toLocaleString('en-US', {
          style: 'currency',
          currency: 'USD'
        });
        const shortSession = item.session_id ? item.session_id.slice(-8) : 'Session';
        const dateStr = item.timestamp ? new Date(item.timestamp * 1000).toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'}) : 'Pending Review';

        return `
          <div class="glass-card rounded-3xl p-6 flex flex-col justify-between border border-white/10 hover:border-indigo-500/30 transition-all duration-300 hover:shadow-xl hover:shadow-indigo-500/5 group" id="card-${item.session_id}">
            
            <div class="space-y-4">
              <!-- Card Header -->
              <div class="flex items-center justify-between">
                <span class="inline-flex items-center space-x-1.5 px-2.5 py-1 rounded-full text-[11px] font-semibold bg-amber-500/10 text-amber-300 border border-amber-500/20">
                  <span class="w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse"></span>
                  <span>Review Required</span>
                </span>
                <span class="text-xs text-slate-500 font-mono">#${shortSession}</span>
              </div>

              <!-- Amount & Title -->
              <div>
                <div class="font-display font-extrabold text-3xl text-white tracking-tight">
                  ${amountFormatted}
                </div>
                <p class="text-sm font-medium text-slate-300 mt-1 line-clamp-2">
                  ${escapeHtml(item.description)}
                </p>
              </div>

              <!-- Policy Tag -->
              <div class="p-3 rounded-xl bg-slate-900/60 border border-white/5 text-xs text-slate-400 space-y-1">
                <div class="flex items-center justify-between text-[11px] text-slate-400">
                  <span>Policy Check</span>
                  <span class="text-amber-400 font-semibold">&ge; $100 Threshold</span>
                </div>
                <div class="text-[11px] text-slate-500">
                  Employee: <span class="text-slate-300 font-mono">${item.user_id || 'default-user'}</span>
                </div>
              </div>
            </div>

            <!-- Action Buttons -->
            <div class="grid grid-cols-2 gap-3 mt-6 pt-4 border-t border-white/5">
              
              <!-- Reject Action -->
              <button onclick="handleAction('${item.session_id}', false)" id="btn-reject-${item.session_id}" class="py-2.5 px-3 rounded-xl bg-slate-800/80 hover:bg-rose-500/10 text-xs font-semibold text-rose-300 border border-white/10 hover:border-rose-500/30 transition-all flex items-center justify-center space-x-1.5">
                <i data-lucide="x" class="w-3.5 h-3.5"></i>
                <span>Reject</span>
              </button>

              <!-- Approve Action -->
              <button onclick="handleAction('${item.session_id}', true)" id="btn-approve-${item.session_id}" class="py-2.5 px-3 rounded-xl bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-500 hover:to-teal-500 text-xs font-semibold text-white shadow-lg shadow-emerald-600/20 border border-emerald-400/20 transition-all flex items-center justify-center space-x-1.5">
                <i data-lucide="check" class="w-3.5 h-3.5"></i>
                <span>Approve</span>
              </button>

            </div>

          </div>
        `;
      }).join('');

      lucide.createIcons();
    }

    // Process Action (Approve / Reject)
    async function handleAction(sessionId, approved) {
      const approveBtn = document.getElementById(`btn-approve-${sessionId}`);
      const rejectBtn = document.getElementById(`btn-reject-${sessionId}`);

      const targetBtn = approved ? approveBtn : rejectBtn;
      const originalHtml = targetBtn.innerHTML;
      
      targetBtn.disabled = true;
      targetBtn.innerHTML = `<span class="inline-block animate-spin mr-1">⟳</span> ${approved ? 'Approving...' : 'Rejecting...'}`;

      try {
        const res = await fetch(`/api/action/${sessionId}`, {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({
            approved: approved,
            comment: approved ? 'Manager approved via ExpenseOps Dashboard' : 'Manager rejected via ExpenseOps Dashboard'
          })
        });

        if (!res.ok) {
          const errData = await res.json();
          throw new Error(errData.detail || 'Execution error');
        }

        const data = await res.json();
        
        // Mark session as resolved so it never reappears in this client
        resolvedSessionIds.add(sessionId);

        // Remove card gracefully
        const card = document.getElementById(`card-${sessionId}`);
        if (card) {
          card.style.opacity = '0';
          card.style.transform = 'scale(0.95)';
          setTimeout(() => card.remove(), 250);
        }

        // Show result modal
        openDecisionModal(approved, data.review_summary);
        showToast(approved ? 'Expense claim approved!' : 'Expense claim rejected.');
        
        // Refresh queue
        setTimeout(() => fetchPendingApprovals(), 400);

      } catch (err) {
        console.error('Action error:', err);
        showToast(`Failed: ${err.message}`, 'alert-triangle');
        targetBtn.disabled = false;
        targetBtn.innerHTML = originalHtml;
      }
    }

    // Modal Control
    function openDecisionModal(approved, markdownSummary) {
      const modal = document.getElementById('decision-modal');
      const badge = document.getElementById('modal-icon-badge');
      const icon = document.getElementById('modal-icon');
      const title = document.getElementById('modal-title');
      const body = document.getElementById('modal-markdown');

      if (approved) {
        badge.className = "w-12 h-12 rounded-2xl flex items-center justify-center border bg-emerald-500/10 text-emerald-400 border-emerald-500/20 shadow-emerald-500/20";
        icon.setAttribute('data-lucide', 'check');
        title.innerText = 'Expense Claim Approved';
      } else {
        badge.className = "w-12 h-12 rounded-2xl flex items-center justify-center border bg-rose-500/10 text-rose-400 border-rose-500/20 shadow-rose-500/20";
        icon.setAttribute('data-lucide', 'x');
        title.innerText = 'Expense Claim Rejected';
      }

      body.innerHTML = marked.parse(markdownSummary || 'Completed review execution.');
      lucide.createIcons();

      modal.classList.remove('hidden');
      setTimeout(() => {
        document.getElementById('modal-card').classList.remove('scale-95');
        document.getElementById('modal-card').classList.add('scale-100');
      }, 10);
    }

    function closeDecisionModal() {
      const modal = document.getElementById('decision-modal');
      document.getElementById('modal-card').classList.add('scale-95');
      setTimeout(() => modal.classList.add('hidden'), 150);
    }

    // Test Claim Modal
    function openTestModal() {
      document.getElementById('test-modal').classList.remove('hidden');
    }
    function closeTestModal() {
      document.getElementById('test-modal').classList.add('hidden');
    }

    async function submitTestClaim() {
      const btn = document.getElementById('submit-test-btn');
      const amount = parseFloat(document.getElementById('test-amount').value) || 250.0;
      const desc = document.getElementById('test-desc').value;

      btn.disabled = true;
      btn.innerText = 'Submitting...';

      try {
        const res = await fetch('/api/submit-expense', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({amount: amount, description: desc})
        });
        if (!res.ok) throw new Error('Submission failed');

        closeTestModal();
        showToast('Claim submitted to Agent Runtime!');
        setTimeout(() => fetchPendingApprovals(), 1500);
      } catch (err) {
        showToast('Submission error', 'alert-circle');
      } finally {
        btn.disabled = false;
        btn.innerText = 'Submit to Agent';
      }
    }

    // Toast notification
    function showToast(msg, iconName = 'info') {
      const toast = document.getElementById('toast');
      const msgEl = document.getElementById('toast-msg');
      const iconEl = document.getElementById('toast-icon');

      msgEl.innerText = msg;
      iconEl.setAttribute('data-lucide', iconName);
      lucide.createIcons();

      toast.classList.remove('translate-y-20', 'opacity-0');
      setTimeout(() => {
        toast.classList.add('translate-y-20', 'opacity-0');
      }, 3500);
    }

    function escapeHtml(str) {
      if (!str) return '';
      return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
    }

    // Auto-refresh setup
    document.getElementById('auto-refresh-toggle').addEventListener('change', (e) => {
      if (e.target.checked) {
        startAutoRefresh();
      } else {
        clearInterval(autoRefreshInterval);
      }
    });

    function startAutoRefresh() {
      clearInterval(autoRefreshInterval);
      autoRefreshInterval = setInterval(() => fetchPendingApprovals(), 8000);
    }

    // Initialization
    window.addEventListener('DOMContentLoaded', () => {
      loadConfig();
      fetchPendingApprovals();
      startAutoRefresh();
    });
  </script>
</body>
</html>
"""
    return HTMLResponse(content=html_content)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8001, reload=True)
