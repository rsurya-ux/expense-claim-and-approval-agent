# Copyright 2026 Google LLC
# Licensed under the Apache License, Version 2.0

"""Enterprise Observability, Structured JSON Logging, and PII Redaction."""

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, Optional

# --- PII Redaction Regex Patterns ---
CREDIT_CARD_REGEX = re.compile(r"\b(?:\d{4}[ -]?){3}\d{4}\b")
SSN_REGEX = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
PHONE_REGEX = re.compile(r"\b(?:\+?1[-. ]?)?\(?([0-9]{3})\)?[-. ]?([0-9]{3})[-. ]?([0-9]{4})\b")
EMAIL_REGEX = re.compile(r"\b([a-zA-Z0-9_.+-])[a-zA-Z0-9_.+-]*@([a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+)\b")


class PIIRedactor:
    """Enterprise PII Redaction Engine for logs, audit events, and agent traces."""

    @staticmethod
    def redact_text(text: str) -> str:
        """Redacts sensitive financial and personal data from free-form text."""
        if not text or not isinstance(text, str):
            return text

        # Redact Credit Cards and SSNs
        redacted = CREDIT_CARD_REGEX.sub("[REDACTED_CARD]", text)
        redacted = SSN_REGEX.sub("[REDACTED_SSN]", redacted)
        redacted = PHONE_REGEX.sub("[REDACTED_PHONE]", redacted)
        
        # Mask emails: e.g. alice@company.com -> a***@company.com
        redacted = EMAIL_REGEX.sub(r"\1***@\2", redacted)
        return redacted

    @classmethod
    def redact_payload(cls, data: Any) -> Any:
        """Recursively traverses dictionaries, lists, and values to redact PII."""
        if isinstance(data, str):
            return cls.redact_text(data)
        elif isinstance(data, dict):
            return {k: cls.redact_payload(v) for k, v in data.items()}
        elif isinstance(data, list):
            return [cls.redact_payload(item) for item in data]
        return data


class StructuredJsonFormatter(logging.Formatter):
    """Google Cloud Logging RFC-compliant Structured JSON Log Formatter."""

    def format(self, record: logging.LogRecord) -> str:
        log_payload: Dict[str, Any] = {
            "severity": record.levelname,
            "message": PIIRedactor.redact_text(record.getMessage()),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "component": "expense_agent",
            "logger": record.name,
            "source_location": {
                "file": record.filename,
                "line": record.lineno,
                "function": record.funcName,
            },
        }

        # Extract audit intent vs outcome data if present
        if hasattr(record, "audit"):
            raw_audit = getattr(record, "audit")
            log_payload["audit"] = PIIRedactor.redact_payload(raw_audit)

        if record.exc_info:
            log_payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_payload)


def get_structured_logger(name: str = "expense_agent") -> logging.Logger:
    """Configures and returns a structured JSON logger with PII scrubbing."""
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(StructuredJsonFormatter())
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return logger


# Global logger instance
logger = get_structured_logger()


def log_intent_vs_outcome(
    user_intent: str,
    execution_outcome: str,
    amount: float,
    claim_id: Optional[str] = None,
    submitter: Optional[str] = None,
    discrepancy: bool = False,
    extra_details: Optional[Dict[str, Any]] = None,
) -> None:
    """Explicitly logs user intent vs actual execution outcome for auditing and compliance."""
    audit_data = {
        "user_intent": user_intent,
        "execution_outcome": execution_outcome,
        "amount": amount,
        "claim_id": claim_id or "UNKNOWN",
        "submitter": submitter or "anonymous",
        "discrepancy": discrepancy,
        "details": extra_details or {},
    }
    
    # Redact before logging
    clean_audit = PIIRedactor.redact_payload(audit_data)
    
    logger.info(
        f"Audit Intent vs Outcome: Intent={user_intent} -> Outcome={execution_outcome} (${amount:.2f})",
        extra={"audit": clean_audit},
    )
