# Copyright 2026 Google LLC
# Licensed under the Apache License, Version 2.0

"""Enterprise Observability, Structured JSON Logging, OpenTelemetry Custom Spans, and PII Redaction."""

import json
import logging
import re
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, Generator, Optional

from opentelemetry import trace
from opentelemetry.trace import Span, Status, StatusCode

# OpenTelemetry Custom Tracer
tracer = trace.get_tracer("expense_agent", "1.0.0")

# --- PII Redaction Regex Patterns ---
CREDIT_CARD_REGEX = re.compile(r"\b(?:\d{4}[ -]?){3}\d{4}\b")
SSN_REGEX = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
PHONE_REGEX = re.compile(r"\b(?:\+?1[-. ]?)?\(?([0-9]{3})\)?[-. ]?([0-9]{3})[-. ]?([0-9]{4})\b")
EMAIL_REGEX = re.compile(r"\b([a-zA-Z0-9_.+-])[a-zA-Z0-9_.+-]*@([a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+)\b")


class PIIRedactor:
    """Enterprise PII Redaction Engine for logs, audit events, and agent traces."""

    @staticmethod
    def redact_text(text: str) -> str:
        """Redacts sensitive financial and personal data from free-form text.

        Args:
            text (str): Raw string that may contain sensitive employee or financial PII.

        Returns:
            str: Sanitized string with credit cards, SSNs, phone numbers, and emails masked.
        """
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
        """Recursively traverses dictionaries, lists, and values to redact PII.

        Args:
            data (Any): Arbitrary data structure (dict, list, string, or primitive).

        Returns:
            Any: Scrubbed copy of the data structure with all PII replaced by tokens.
        """
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
        """Formats log record into a structured JSON string for Cloud Logging.

        Args:
            record (logging.LogRecord): The log record to format.

        Returns:
            str: JSON-encoded log line containing severity, component, timestamp, and audit metadata.
        """
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
    """Configures and returns a structured JSON logger with PII scrubbing.

    Args:
        name (str): Identifier for the logger instance. Defaults to 'expense_agent'.

    Returns:
        logging.Logger: Configured logger that formats records with `StructuredJsonFormatter`.
    """
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
    """Explicitly logs user intent vs actual execution outcome for auditing and compliance.

    Args:
        user_intent (str): The inferred or stated user action (e.g., 'submit_claim', 'manager_review').
        execution_outcome (str): The resulting workflow state (e.g., 'AUTO_APPROVED', 'PAUSED_FOR_HITL').
        amount (float): Monetary value associated with the claim in USD.
        claim_id (Optional[str]): Unique claim reference identifier.
        submitter (Optional[str]): Employee email or user identifier.
        discrepancy (bool): True if outcome diverged unexpectedly from requested intent.
        extra_details (Optional[Dict[str, Any]]): Arbitrary supplementary auditing attributes.
    """
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


# ==============================================================================
# OPENTELEMETRY CUSTOM DISTRIBUTED TRACING SPANS
# ==============================================================================

@contextmanager
def trace_span(
    span_name: str,
    attributes: Optional[Dict[str, Any]] = None,
) -> Generator[Span, None, None]:
    """Context manager for creating custom OpenTelemetry distributed tracing spans.

    Args:
        span_name (str): Identifier for the traced operation or workflow step.
        attributes (Optional[Dict[str, Any]]): Key-value attributes to attach to the span.
            Values are automatically screened for PII before being recorded.

    Yields:
        Span: Active OpenTelemetry span instance.
    """
    with tracer.start_as_current_span(span_name) as span:
        if attributes:
            clean_attrs = PIIRedactor.redact_payload(attributes)
            for k, v in clean_attrs.items():
                if isinstance(v, (str, bool, int, float)):
                    span.set_attribute(k, v)
                else:
                    span.set_attribute(k, str(v))
        try:
            yield span
            span.set_status(Status(StatusCode.OK))
        except Exception as exc:
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            span.record_exception(exc)
            raise
