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

"""Unit tests for the ADK 2.0 Ambient Expense Workflow."""

import asyncio
import pytest
from google.adk.runners import InMemoryRunner
from google.genai import types

from app.agent import app, root_agent


def test_auto_approve_under_100() -> None:
    """Expenses under $100 must be auto-approved without human intervention."""
    async def _test():
        runner = InMemoryRunner(app=app)
        session = await runner.session_service.create_session(
            app_name=app.name, user_id="test-employee"
        )

        events = []
        message = types.Content(
            role="user",
            parts=[types.Part.from_text(text="I submit an expense for $45.00 lunch with a client")],
        )

        async for event in runner.run_async(
            user_id="test-employee",
            session_id=session.id,
            new_message=message,
        ):
            events.append(event)

        # Check for approval event
        approved_events = [
            e for e in events
            if e.output and isinstance(e.output, dict) and e.output.get("status") == "APPROVED"
        ]
        assert len(approved_events) == 1, "Expected exactly one APPROVED output event"
        assert approved_events[0].output["amount"] == 45.0
        assert approved_events[0].output["approver"] == "auto_approve_policy"

    asyncio.run(_test())


def test_review_agent_pauses_for_expenses_100_or_more() -> None:
    """Expenses of $100 or more must trigger a human-in-the-loop pause (RequestInput)."""
    async def _test():
        runner = InMemoryRunner(app=app)
        session = await runner.session_service.create_session(
            app_name=app.name, user_id="test-employee"
        )

        events = []
        message = types.Content(
            role="user",
            parts=[types.Part.from_text(text="Expense report: $150.00 for annual conference pass")],
        )

        async for event in runner.run_async(
            user_id="test-employee",
            session_id=session.id,
            new_message=message,
        ):
            events.append(event)

        # Verify pause event was emitted
        request_input_events = [
            e for e in events
            if e.long_running_tool_ids and "manager_review" in e.long_running_tool_ids
        ]
        assert len(request_input_events) == 1, "Expected a RequestInput pause event"
        fc = request_input_events[0].content.parts[0].function_call
        assert fc.name == "adk_request_input"
        assert fc.args["interruptId"] == "manager_review"
        assert "$150.00" in fc.args["message"]

    asyncio.run(_test())


def test_review_agent_resume_approved() -> None:
    """Resuming a paused expense review with approval must set status to APPROVED."""
    async def _test():
        runner = InMemoryRunner(app=app)
        session = await runner.session_service.create_session(
            app_name=app.name, user_id="test-employee"
        )

        # 1. Initial submission triggers pause
        message = types.Content(
            role="user",
            parts=[types.Part.from_text(text="Flight ticket for $350.00 to Chicago summit")],
        )
        async for _ in runner.run_async(
            user_id="test-employee",
            session_id=session.id,
            new_message=message,
        ):
            pass

        # 2. Manager responds with approval
        resume_message = types.Content(
            role="user",
            parts=[
                types.Part(
                    function_response=types.FunctionResponse(
                        id="manager_review",
                        name="manager_review",
                        response={"approved": True, "comment": "Approved for business travel"},
                    )
                )
            ],
        )

        resumed_events = []
        async for event in runner.run_async(
            user_id="test-employee",
            session_id=session.id,
            new_message=resume_message,
        ):
            resumed_events.append(event)

        decision_events = [
            e for e in resumed_events
            if e.output and isinstance(e.output, dict) and e.output.get("status") == "APPROVED"
        ]
        assert len(decision_events) == 1
        assert decision_events[0].output["amount"] == 350.0
        assert decision_events[0].output["approver"] == "manager_review"

    asyncio.run(_test())


def test_review_agent_resume_rejected() -> None:
    """Resuming a paused expense review with rejection must set status to REJECTED."""
    async def _test():
        runner = InMemoryRunner(app=app)
        session = await runner.session_service.create_session(
            app_name=app.name, user_id="test-employee"
        )

        # 1. Initial submission
        message = types.Content(
            role="user",
            parts=[types.Part.from_text(text="$500.00 luxury watch expense")],
        )
        async for _ in runner.run_async(
            user_id="test-employee",
            session_id=session.id,
            new_message=message,
        ):
            pass

        # 2. Manager rejects claim
        resume_message = types.Content(
            role="user",
            parts=[
                types.Part(
                    function_response=types.FunctionResponse(
                        id="manager_review",
                        name="manager_review",
                        response={"approved": False, "comment": "Not a permissible business expense"},
                    )
                )
            ],
        )

        resumed_events = []
        async for event in runner.run_async(
            user_id="test-employee",
            session_id=session.id,
            new_message=resume_message,
        ):
            resumed_events.append(event)

        decision_events = [
            e for e in resumed_events
            if e.output and isinstance(e.output, dict) and e.output.get("status") == "REJECTED"
        ]
        assert len(decision_events) == 1
        assert decision_events[0].output["amount"] == 500.0
        assert decision_events[0].output["status"] == "REJECTED"

    asyncio.run(_test())


def test_review_agent_invalid_response_repairs_and_reprompts() -> None:
    """An ambiguous or invalid response like 'yesyes' must re-prompt without approving $0."""
    async def _test():
        runner = InMemoryRunner(app=app)
        session = await runner.session_service.create_session(
            app_name=app.name, user_id="test-employee"
        )

        # 1. Initial submission of $250 claim pauses
        message = types.Content(
            role="user",
            parts=[types.Part.from_text(text="Submit expense of $250 for conference ticket")],
        )
        async for _ in runner.run_async(
            user_id="test-employee",
            session_id=session.id,
            new_message=message,
        ):
            pass

        # 2. User sends 'yesyes'
        invalid_message = types.Content(
            role="user",
            parts=[types.Part.from_text(text="yesyes")],
        )
        invalid_events = []
        async for event in runner.run_async(
            user_id="test-employee",
            session_id=session.id,
            new_message=invalid_message,
        ):
            invalid_events.append(event)

        # Verify it did NOT auto-approve a $0 claim!
        auto_approved = [
            e for e in invalid_events
            if e.output and isinstance(e.output, dict) and e.output.get("approver") == "auto_approve_policy"
        ]
        assert len(auto_approved) == 0, "Must not auto-approve invalid response as a new $0 claim!"

        # Verify it asked for clarification / re-prompted
        has_warning = any(
            "Invalid Response" in p.text for e in invalid_events if e.content for p in e.content.parts if hasattr(p, "text") and p.text
        )
        assert has_warning, "Expected invalid response warning in output content"

        # 3. Now send valid approval 'yes'
        approval_message = types.Content(
            role="user",
            parts=[types.Part.from_text(text="yes")],
        )
        resumed_events = []
        async for event in runner.run_async(
            user_id="test-employee",
            session_id=session.id,
            new_message=approval_message,
        ):
            resumed_events.append(event)

        approved = [
            e for e in resumed_events
            if e.output and isinstance(e.output, dict) and e.output.get("status") == "APPROVED"
        ]
        assert len(approved) == 1, "Expected claim to be approved after 'yes'"
        assert approved[0].output["amount"] == 250.0

    asyncio.run(_test())
