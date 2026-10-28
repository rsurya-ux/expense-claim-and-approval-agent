# Copyright 2026 Google LLC
# Licensed under the Apache License, Version 2.0

"""Strategic Tiered Model Routing Engine."""

from typing import Dict, Tuple
from app.app_utils.observability import logger

FAST_MODEL = "gemini-2.5-flash"
REASONING_MODEL = "gemini-2.5-pro"


class StrategicModelRouter:
    """Routes agent tasks to appropriate Gemini model tier based on task complexity and risk."""

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
        # Tier 2 (Deep Reasoning): High-value claims, manager disputes, or complex multi-turn flows
        if amount >= 100.0 or is_escalation or is_multi_turn:
            model = REASONING_MODEL
            tier = "Tier-2: Deep Reasoning"
            rationale = (
                f"Routed to {model} for comprehensive policy compliance analysis "
                f"(amount=${amount:.2f} >= $100.00 or escalation={is_escalation})."
            )
        else:
            # Tier 1 (Fast & Economical): Routine intake & auto-approval (< $100)
            model = FAST_MODEL
            tier = "Tier-1: Fast Execution"
            rationale = (
                f"Routed to {model} for low-latency autonomous validation "
                f"(amount=${amount:.2f} < $100.00)."
            )

        logger.info(f"Model Router Decision: {tier} -> Selected: {model} | Reason: {rationale}")
        return model, tier, rationale
