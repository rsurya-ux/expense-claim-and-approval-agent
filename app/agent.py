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

"""Ambient Expense Agent with ADK 2.0 Graph Workflow and Human-in-the-Loop Review."""

import re
from typing import Any

from google.adk.agents.context import Context
from google.adk.apps import App, ResumabilityConfig
from google.adk.events.event import Event
from google.adk.events.request_input import RequestInput
from google.adk.models import Gemini
from google.adk.workflow import START, Workflow, node
from google.genai import types
from pydantic import BaseModel, Field

# Preserved model configuration
MODEL = "gemini-3.8-flash"


class ExpenseClaim(BaseModel):
    """Schema for an employee expense claim."""

    amount: float = Field(
        description="Monetary amount of the expense claim in USD."
    )
    description: str = Field(
        default="Expense claim",
        description="Description or justification of the expense.",
    )
    employee_id: str = Field(
        default="EMP-001",
        description="Employee identifier submitting the expense.",
    )


class ExpenseDecision(BaseModel):
    """Schema for an expense approval decision."""

    claim_id: str = Field(default="EXP-DEFAULT")
    amount: float
    description: str
    status: str = Field(description="APPROVED, REJECTED, or PENDING_REVIEW")
    approver: str
    note: str = ""


def _parse_claim_from_input(node_input: Any) -> tuple[float, str]:
    """Extracts monetary amount and description from diverse input types."""
    if isinstance(node_input, dict):
        amount = float(node_input.get("amount", 0.0))
        description = str(node_input.get("description", "Standard expense claim"))
        return amount, description
    if isinstance(node_input, (int, float)):
        return float(node_input), "Standard expense claim"

    text = ""
    if isinstance(node_input, types.Content):
        text = " ".join(
            p.text for p in node_input.parts if hasattr(p, "text") and p.text
        )
    elif isinstance(node_input, str):
        text = node_input

    # Parse numeric dollar amount (e.g. '$150', '150.00', '$45')
    match = re.search(r"(?:\$|\b)([0-9]+(?:\.[0-9]{1,2})?)\b", text)
    amount = float(match.group(1)) if match else 0.0
    description = text.strip() if text.strip() else "Standard expense claim"
    return amount, description


def classify_expense(ctx: Context, node_input: Any) -> Event:
    """Intake node: parses claim amount and routes based on $100 threshold."""
    amount, description = _parse_claim_from_input(node_input)
    pending = ctx.state.get("pending_claim")

    raw_text = description.lower().strip()
    decision_tokens = {"yes", "y", "approve", "approved", "no", "n", "reject", "rejected"}
    raw_words = set(re.findall(r"\w+", raw_text))

    # If there is a pending claim awaiting manager review:
    # Any input containing a decision token OR having no dollar amount is treated as a review response.
    if pending and (bool(raw_words & decision_tokens) or amount == 0.0):
        return Event(
            output={
                "amount": pending["amount"],
                "description": pending["description"],
                "human_decision": raw_text,
            },
            route="review_agent",
        )

    claim_payload = {"amount": amount, "description": description}

    if amount < 100.0:
        return Event(
            output=claim_payload,
            route="auto_approve",
            state={"current_claim": claim_payload, "pending_claim": None},
        )
    else:
        return Event(
            output=claim_payload,
            route="review_agent",
            state={"pending_claim": claim_payload, "current_claim": claim_payload},
        )


@node(name="auto_approve")
def auto_approve(node_input: dict) -> Event:
    """Automatically approves standard expense claims under $100."""
    amount = float(node_input.get("amount", 0.0))
    description = str(node_input.get("description", "Expense claim"))

    decision = ExpenseDecision(
        claim_id=f"EXP-{int(amount * 100)}",
        amount=amount,
        description=description,
        status="APPROVED",
        approver="auto_approve_policy",
        note="Instantly approved: claim is under the $100 threshold.",
    )

    content_text = (
        f"### Instant Expense Approval\n"
        f"- **Status:** APPROVED\n"
        f"- **Amount:** ${amount:.2f}\n"
        f"- **Description:** {description}\n"
        f"- **Policy:** Standard claims under $100 are automatically approved.\n"
    )

    return Event(
        output=decision.model_dump(),
        content=types.Content(
            role="model", parts=[types.Part.from_text(text=content_text)]
        ),
        state={"approval_decision": decision.model_dump()},
    )


@node(name="review_agent", rerun_on_resume=True)
async def review_agent(ctx: Context, node_input: dict) -> Any:
    """Human-in-the-loop review node: pauses claims >= $100 for manager approval."""
    amount = float(node_input.get("amount", 0.0)) if node_input else 0.0
    description = (
        str(node_input.get("description", "Expense claim"))
        if node_input
        else "Expense claim"
    )

    interrupt_id = "manager_review"

    # Check if review input was provided via resumption or forwarded text response
    human_decision = node_input.get("human_decision") if node_input else None
    user_response = None
    if ctx.resume_inputs and interrupt_id in ctx.resume_inputs:
        user_response = ctx.resume_inputs[interrupt_id]
    elif human_decision:
        user_response = human_decision

    # Step 1: Trigger HITL Pause if manager approval has not been provided
    if user_response is None:
        prompt_message = (
            f"### ⚠️ Manager Review Required\n\n"
            f"- **Claim Amount:** ${amount:.2f}\n"
            f"- **Description:** {description}\n"
            f"- **Policy:** Claims of $100 or more require explicit manager approval.\n\n"
            f"👉 **Action Required:** Do you approve this expense claim? (Reply **yes** or **no**)"
        )
        yield Event(
            content=types.Content(
                role="model",
                parts=[types.Part.from_text(text=prompt_message)],
            )
        )
        yield RequestInput(
            interrupt_id=interrupt_id,
            message=prompt_message,
            payload={"amount": amount, "description": description},
        )
        return

    # Step 2: Validate human review decision
    response_str = str(user_response).lower().strip()
    tokens_approve = {"yes", "y", "approve", "approved"}
    tokens_reject = {"no", "n", "reject", "rejected"}

    if isinstance(user_response, dict):
        resp_val = str(user_response.get("response", "")).lower().strip()
        is_approved = user_response.get("approved") is True or resp_val in tokens_approve
        is_rejected = user_response.get("approved") is False or resp_val in tokens_reject
    else:
        words = set(re.findall(r"\w+", response_str))
        is_approved = bool(words & tokens_approve) and not bool(words & tokens_reject)
        is_rejected = bool(words & tokens_reject) and not bool(words & tokens_approve)

    if not is_approved and not is_rejected:
        # Invalid response! Re-prompt and keep workflow paused.
        invalid_message = (
            f"### ⚠️ Invalid Response: \"{user_response}\"\n\n"
            f"`{user_response}` is not a recognized review decision for pending claim of **${amount:.2f}** ('{description}').\n\n"
            f"👉 **Please reply with:**\n"
            f"- **yes** (or **approve**) to approve this claim\n"
            f"- **no** (or **reject**) to reject this claim"
        )
        yield Event(
            content=types.Content(
                role="model",
                parts=[types.Part.from_text(text=invalid_message)],
            )
        )
        yield RequestInput(
            interrupt_id=interrupt_id,
            message=invalid_message,
            payload={"amount": amount, "description": description},
        )
        return

    final_status = "APPROVED" if is_approved else "REJECTED"

    decision = ExpenseDecision(
        claim_id=f"EXP-{int(amount * 100)}",
        amount=amount,
        description=description,
        status=final_status,
        approver="manager_review",
        note=f"Manager review completed with response: {user_response}",
    )

    summary_text = (
        f"### Review Decision: {final_status}\n"
        f"- **Status:** {final_status}\n"
        f"- **Amount:** ${amount:.2f}\n"
        f"- **Description:** {description}\n"
        f"- **Approver:** Manager (Human-in-the-Loop)\n"
        f"- **Decision Input:** {user_response}\n"
    )

    yield Event(
        output=decision.model_dump(),
        content=types.Content(
            role="model", parts=[types.Part.from_text(text=summary_text)]
        ),
        state={"approval_decision": decision.model_dump(), "pending_claim": None},
    )


# Graph Topology Definition
edges = [
    (START, classify_expense),
    (classify_expense, {"auto_approve": auto_approve, "review_agent": review_agent}),
]

root_agent = Workflow(
    name="expense_agent",
    description="Ambient expense agent with automated approval under $100 and human-in-the-loop review for claims $100 or more.",
    edges=edges,
)

app = App(
    root_agent=root_agent,
    name="app",
    resumability_config=ResumabilityConfig(is_resumable=True),
)
