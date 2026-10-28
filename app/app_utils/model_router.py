# Copyright 2026 Google LLC
# Licensed under the Apache License, Version 2.0

"""Strategic Tiered Model Routing Engine driving Dynamic LLM Invocations."""

import os
from typing import Any, Dict, Optional, Tuple
from google.adk.models import Gemini
from google.genai import types
from app.app_utils.observability import logger

FAST_MODEL = "gemini-2.5-flash"
REASONING_MODEL = "gemini-2.5-pro"


class StrategicModelRouter:
    """Routes agent tasks and drives dynamic LLM invocations based on task complexity."""

    @classmethod
    def resolve_model(
        cls,
        amount: float,
        is_escalation: bool = False,
        is_multi_turn: bool = False,
    ) -> Tuple[str, str, str]:
        """Resolves optimal model according to cost-efficiency and reasoning depth requirements.
        
        Returns:
            Tuple of (model_name, tier_name, routing_rationale)
        """
        # Tier 2 (Deep Reasoning): High-value claims (>= $100), manager disputes, or complex multi-turn flows
        if amount >= 100.0 or is_escalation or is_multi_turn:
            model = REASONING_MODEL
            tier = "Tier-2: Deep Reasoning"
            rationale = (
                f"Dynamically routed to {model} for deep policy reasoning & risk auditing "
                f"(amount=${amount:.2f} >= $100.00 or escalation={is_escalation})."
            )
        else:
            # Tier 1 (Fast & Economical): Routine intake & auto-approval (< $100)
            model = FAST_MODEL
            tier = "Tier-1: Fast Execution"
            rationale = (
                f"Dynamically routed to {model} for high-throughput, low-latency validation "
                f"(amount=${amount:.2f} < $100.00)."
            )

        logger.info(f"Model Router Decision: {tier} -> Selected: {model} | Reason: {rationale}")
        return model, tier, rationale

    @classmethod
    def get_model_instance(cls, model_name: str) -> Gemini:
        """Instantiates an ADK Gemini model wrapper for the routed model."""
        return Gemini(
            model=model_name,
            retry_options=types.HttpRetryOptions(attempts=3),
        )

    @classmethod
    async def invoke_dynamic_model(
        cls,
        model_name: str,
        system_instruction: str,
        prompt: str,
        fallback_text: str = "",
    ) -> str:
        """Executes actual dynamic LLM call with the strategically routed model.
        
        Drives runtime intelligence for policy audits, risk evaluations,
        and manager brief generation. Includes graceful fallback for offline test suites.
        """
        try:
            from google.genai import Client
            client = Client()
            response = await client.aio.models.generate_content(
                model=model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    temperature=0.1,
                ),
            )
            if response and response.text:
                logger.info(f"Dynamic LLM Invocation Successful via [{model_name}]: {response.text[:80]}...")
                return response.text.strip()
        except Exception as exc:
            logger.info(f"Dynamic LLM Invocation fallback active for [{model_name}]: {exc}")

        return fallback_text
