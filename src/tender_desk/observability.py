"""JSON logs and Prometheus metrics. Neither ever contains the API token, an API key, tender text or model output."""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from collections.abc import Callable
from functools import wraps
from typing import Any

from prometheus_client import CollectorRegistry, Counter, Histogram

REGISTRY = CollectorRegistry()
_LAT = (0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60)
HTTP_REQUESTS = Counter("tender_http_requests_total", "HTTP requests", ["method", "route", "status"], registry=REGISTRY)
HTTP_SECONDS = Histogram("tender_http_request_seconds", "HTTP request latency", ["route"], buckets=_LAT, registry=REGISTRY)
LLM_CALLS = Counter("tender_llm_calls_total", "Model calls", ["model", "purpose"], registry=REGISTRY)
LLM_COST = Counter("tender_llm_cost_usd_total", "Model spend in US dollars", ["model", "purpose"], registry=REGISTRY)
LLM_TOKENS = Counter("tender_llm_tokens_total", "Model tokens", ["model", "purpose"], registry=REGISTRY)
LLM_SECONDS = Histogram("tender_llm_call_seconds", "Model call latency", ["model", "purpose"], buckets=_LAT, registry=REGISTRY)
STEP_SECONDS = Histogram("tender_workflow_step_seconds", "Workflow step latency", ["step"], buckets=_LAT, registry=REGISTRY)
TENDERS = Counter(
    "tender_workflow_events_total", "Workflow events", ["event"], registry=REGISTRY
)  # created, approved, rejected, stopped, failed
PII_REDACTIONS = Counter(
    "tender_pii_redactions_total",
    "Personal-data values replaced before the model call, by type (a count, never a value)",
    ["type"],
    registry=REGISTRY,
)


def observe_llm(model: str, purpose: str, seconds: float, cost: float, tokens: int) -> None:
    LLM_CALLS.labels(model, purpose).inc()
    LLM_COST.labels(model, purpose).inc(cost)
    LLM_TOKENS.labels(model, purpose).inc(tokens)
    LLM_SECONDS.labels(model, purpose).observe(seconds)


def timed_step(name: str, fn: Callable[..., Any]) -> Callable[..., Any]:
    """Wrap a workflow node so its duration is recorded."""

    @wraps(fn)
    def inner(*a: Any, **k: Any) -> Any:
        t = time.perf_counter()
        try:
            return fn(*a, **k)
        finally:
            STEP_SECONDS.labels(name).observe(time.perf_counter() - t)

    return inner


class JsonFormatter(logging.Formatter):
    _SKIP = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {"message", "asctime", "taskName"}

    def format(self, record: logging.LogRecord) -> str:
        out: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        out.update({k: v for k, v in record.__dict__.items() if k not in self._SKIP})
        if record.exc_info:
            out["exc_type"] = record.exc_info[0].__name__ if record.exc_info[0] else None  # type only: messages can carry data
        return json.dumps(out, default=str)


def configure_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(os.environ.get("TENDER_DESK_LOG_LEVEL", "INFO").upper())
    for noisy in (
        "httpx",
        "httpcore",
        "uvicorn.access",
    ):  # httpx logs full request URLs; uvicorn.access is replaced by our own line
        logging.getLogger(noisy).setLevel(logging.WARNING)
