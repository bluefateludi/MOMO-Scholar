from __future__ import annotations

import re
import math
from collections.abc import Mapping
from typing import Any

from paper_agent.observability.tracing_models import (
    EVALUATION_EVENT_NAMES,
    PIPELINE_EVENT_NAMES,
)

REDACTED = "[REDACTED]"

class TraceDataPolicyError(ValueError):
    pass


_PROHIBITED_TRACE_KEYS = frozenset(
    {
        'prompt',
        'prompt_text',
        'response',
        'response_text',
        'abstract',
        'pdf_text',
        'evidence_quote',
        'authorization',
        'cookie',
        'stack_trace',
        'exception',
        'exception_message',
        'endpoint_url',
        'provider_request',
        'provider_response',
        'raw_request',
        'raw_response',
        'request_body',
        'response_body',
    }
)
_EVENT_ATTRIBUTE_ALLOWLISTS = {
    'paper_agent.pipeline.run.started': frozenset(
        {'requested_limit', 'no_pdf'}
    ),
    'paper_agent.pipeline.retrieval': frozenset(
        {
            'operation',
            'returned_paper_count',
            'paper_id',
            'requested_mode',
            'actual_mode',
            'evidence_count',
            'failure_stage',
        }
    ),
    'paper_agent.pipeline.fulltext': frozenset(
        {
            'operation',
            'paper_id',
            'document_available',
            'chunk_count',
            'warning_count',
            'failure_stage',
        }
    ),
    'paper_agent.pipeline.rerank': frozenset(
        {'paper_id', 'actual_mode', 'returned_evidence_count'}
    ),
    'paper_agent.pipeline.analysis': frozenset(
        {
            'paper_id',
            'attempts',
            'evidence_count',
            'failure_stage',
            'model_name',
        }
    ),
    'paper_agent.pipeline.citation_validation': frozenset(
        {
            'scope',
            'paper_id',
            'sanitized_reference_count',
            'dropped_finding_count',
            'sanitized_claim_count',
        }
    ),
    'paper_agent.pipeline.synthesis': frozenset(
        {'analysis_count', 'evidence_count', 'attempts', 'failure_stage'}
    ),
    'paper_agent.pipeline.output': frozenset(
        {'published', 'paper_count', 'document_count'}
    ),
    'paper_agent.pipeline.degradation': frozenset(
        {'degradation_count'}
    ),
    'paper_agent.pipeline.run.finished': frozenset(
        {
            'selected_paper_count',
            'analysis_count',
            'evidence_count',
            'failure_stage',
        }
    ),
    'paper_agent.evaluation.metrics': frozenset(
        {
            'metric_count',
            'model_name',
            'duration_ms',
            'prompt_tokens',
            'completion_tokens',
            'total_tokens',
        }
    ),
}


_CREDENTIAL_KEY_SUFFIXES = (
    "api_key",
    "apikey",
    "authorization",
    "credential",
    "credentials",
    "password",
    "passwd",
    "secret",
    "token",
)
_RAW_PAYLOAD_KEYS = frozenset(
    {
        "provider_request",
        "provider_response",
        "raw_request",
        "raw_request_body",
        "raw_response",
        "raw_response_body",
        "request_body",
        "response_body",
    }
)


def sanitize_event_data(value: Any, *, secrets: tuple[str, ...]) -> Any:
    """Return a JSON-compatible copy with secrets and raw payloads redacted."""
    known_secrets = tuple(
        sorted({secret for secret in secrets if secret}, key=lambda item: (-len(item), item))
    )
    return _sanitize(value, secrets=known_secrets)


def validate_trace_attributes(
    attributes: Mapping[str, Any],
    *,
    secrets: tuple[str, ...] = (),
) -> dict[str, str | bool | int | float | None]:
    _reject_prohibited_trace_data(attributes)
    sanitized = sanitize_event_data(attributes, secrets=secrets)
    if not isinstance(sanitized, dict):
        raise TraceDataPolicyError('trace attributes must be a mapping')
    result: dict[str, str | bool | int | float | None] = {}
    for key, value in sanitized.items():
        if not isinstance(key, str) or not key.strip():
            raise TraceDataPolicyError('trace attribute keys must be nonblank')
        if type(value) not in (str, bool, int, float, type(None)):
            raise TraceDataPolicyError('trace attributes must contain safe scalars')
        if isinstance(value, float) and not math.isfinite(value):
            raise TraceDataPolicyError('trace attributes must contain finite values')
        result[key] = value
    return result


def validate_event_attributes(
    event_name: str,
    attributes: Mapping[str, Any],
    *,
    secrets: tuple[str, ...] = (),
) -> dict[str, str | bool | int | float | None]:
    if event_name not in PIPELINE_EVENT_NAMES | EVALUATION_EVENT_NAMES:
        raise TraceDataPolicyError('trace event name is not allowlisted')
    allowed = _EVENT_ATTRIBUTE_ALLOWLISTS[event_name]
    if not set(attributes) <= allowed:
        raise TraceDataPolicyError('trace event attribute is not allowlisted')
    return validate_trace_attributes(attributes, secrets=secrets)


def _reject_prohibited_trace_data(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise TraceDataPolicyError('trace attribute keys must be strings')
            normalized = re.sub(r'[^a-z0-9]+', '_', key.casefold()).strip('_')
            if (
                normalized in _PROHIBITED_TRACE_KEYS
                or _is_sensitive_key(key)
            ):
                raise TraceDataPolicyError('prohibited trace attribute')
            _reject_prohibited_trace_data(item)
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            _reject_prohibited_trace_data(item)


def _sanitize(value: Any, *, secrets: tuple[str, ...]) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        sanitized = value
        for secret in secrets:
            sanitized = sanitized.replace(secret, REDACTED)
        return sanitized
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            safe_key = key if isinstance(key, str) else _unsupported_type(key)
            if _is_sensitive_key(safe_key):
                result[safe_key] = REDACTED
            else:
                result[safe_key] = _sanitize(item, secrets=secrets)
        return result
    if isinstance(value, (list, tuple)):
        return [_sanitize(item, secrets=secrets) for item in value]
    return _unsupported_type(value)


def _is_sensitive_key(key: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", "_", key.casefold()).strip("_")
    return normalized in _RAW_PAYLOAD_KEYS or any(
        normalized == suffix or normalized.endswith(f"_{suffix}")
        for suffix in _CREDENTIAL_KEY_SUFFIXES
    )


def _unsupported_type(value: Any) -> str:
    value_type = type(value)
    return f"[UNSUPPORTED_TYPE:{value_type.__module__}.{value_type.__qualname__}]"
