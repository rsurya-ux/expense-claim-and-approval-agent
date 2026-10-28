# Copyright 2026 Google LLC
# Licensed under the Apache License, Version 2.0

"""Advanced Runtime Guardrail Plugins for Input Validation & Output Compliance."""

import re
from typing import Any, Dict, Optional, Tuple
from app.app_utils.observability import logger

# Adversarial prompt injection keywords
INJECTION_PATTERNS = [
    re.compile(r"ignore\s+(all\s+)?(previous|prior)\s+instructions", re.IGNORECASE),
    re.compile(r"system\s+(prompt|override|bypass)", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\s+in\s+developer\s+mode", re.IGNORECASE),
    re.compile(r"jailbreak|dan\s+mode", re.IGNORECASE),
    re.compile(r"auto[_-]?approve\s+everything", re.IGNORECASE),
]


class GuardrailViolationError(ValueError):
    """Raised when runtime input or output fails policy verification."""
    pass


class RuntimeGuardrail:
    """Runtime guardrail plugin for intercepting and screening agent interactions."""

    @classmethod
    def check_input(cls, text: str, amount: Optional[float] = None) -> Tuple[bool, Optional[str]]:
        """Screens incoming prompts and claims against security and fraud policies.
        
        Returns:
            Tuple of (is_valid: bool, error_message: Optional[str])
        """
        # 1. Anti-Fraud & Boundary Checks
        if amount is not None and amount < 0:
            msg = f"Guardrail Alert: Negative expense amount (${amount:.2f}) rejected by financial policy."
            logger.warning(msg)
            return False, msg

        # 2. Prompt Injection Screening
        if text:
            for pattern in INJECTION_PATTERNS:
                if pattern.search(text):
                    msg = f"Security Alert: Potential adversarial prompt injection pattern detected in input: '{text[:60]}...'"
                    logger.warning(msg)
                    return False, "Input rejected by security guardrail: Unsafe prompt pattern."

        return True, None

    @classmethod
    def check_output(cls, decision_payload: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        """Screens agent output to ensure strict compliance with fiscal policy."""
        status = decision_payload.get("status")
        amount = decision_payload.get("amount", 0.0)

        # Invariant check: Claims >= $100 cannot be auto-approved
        approver = decision_payload.get("approver")
        if amount >= 100.0 and approver == "auto_approve_policy":
            msg = f"Integrity Failure: Claim (${amount:.2f}) >= $100 cannot have approver='auto_approve_policy'."
            logger.error(msg)
            return False, msg

        if status not in {"APPROVED", "REJECTED", "PENDING_REVIEW"}:
            msg = f"Output Failure: Unrecognized decision status '{status}'."
            logger.error(msg)
            return False, msg

        return True, None
