# -*- coding: utf-8 -*-
"""Unified Observability Pipeline for Agent Nexus.

Provides structured telemetry, API latency/TTFT/cost metrics, event sampling,
and a diagnostics endpoint. Inspired by Claude Code's observability layer
(ch39/ch40/ch42).

Components:
  - TelemetryCollector: In-memory metrics with time-windowed aggregation
  - APILatencyTracker: Request-scoped latency/TTFT tracking via middleware
  - CostAccumulator: Per-model token usage and cost tracking
  - EventSampler: Rate-limited event sampling for high-frequency signals

Usage:
    from src.server.services.observability import (
        telemetry, track_api_latency, record_token_usage,
    )

    # Record API latency
    track_api_latency("POST", "/api/nexus/tasks", status_code=201, duration_ms=45.2)

    # Record token usage
    record_token_usage("gpt-4o", prompt_tokens=1200, completion_tokens=350)

    # Get metrics snapshot
    snapshot = telemetry.snapshot()
"""

from __future__ import annotations

import math
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from threading import Lock
from typing import Any, Deque, Dict, List, Optional

from loguru import logger


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

class MetricType(str, Enum):
    COUNTER = "counter"
    GAUGE = "gauge"
    HISTOGRAM = "histogram"


@dataclass
class LatencyRecord:
    """A single latency measurement."""
    method: str
    path: str
    status_code: int
    duration_ms: float
    ttft_ms: Optional[float] = None  # Time to first token (for streaming)
    timestamp: float = field(default_factory=time.time)


@dataclass
class TokenUsageRecord:
    """A single token usage measurement."""
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    estimated_cost_usd: float = 0.0
    timestamp: float = field(default_factory=time.time)


@dataclass
class SampledEvent:
    """A rate-sampled event."""
    event_type: str
    payload: Dict[str, Any]
    timestamp: float = field(default_factory=time.time)
    sample_rate: float = 1.0


# ---------------------------------------------------------------------------
# Cost estimation (approximate, per 1M tokens)
# ---------------------------------------------------------------------------

# Approximate pricing per 1M tokens as of 2025.
# Keys are lowercase model family prefixes.
_MODEL_PRICING: Dict[str, Dict[str, float]] = {
    "gpt-4o": {"prompt": 2.50, "completion": 10.00},
    "gpt-4-turbo": {"prompt": 10.00, "completion": 30.00},
    "gpt-4-": {"prompt": 30.00, "completion": 60.00},
    "gpt-3.5": {"prompt": 0.50, "completion": 1.50},
    "claude-3-opus": {"prompt": 15.00, "completion": 75.00},
    "claude-3-sonnet": {"prompt": 3.00, "completion": 15.00},
    "claude-3-haiku": {"prompt": 0.25, "completion": 1.25},
    "claude-3.5-sonnet": {"prompt": 3.00, "completion": 15.00},
    "claude-3.5-haiku": {"prompt": 0.80, "completion": 4.00},
    "deepseek": {"prompt": 0.14, "completion": 0.28},
    "glm": {"prompt": 0.50, "completion": 0.50},
    "qwen": {"prompt": 0.50, "completion": 1.00},
}

_DEFAULT_PRICING = {"prompt": 1.00, "completion": 3.00}


def _estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Estimate cost in USD based on model family pricing."""
    model_lower = model.lower()
    pricing = _DEFAULT_PRICING
    for prefix, rates in _MODEL_PRICING.items():
        if model_lower.startswith(prefix):
            pricing = rates
            break
    prompt_cost = (prompt_tokens / 1_000_000) * pricing["prompt"]
    completion_cost = (completion_tokens / 1_000_000) * pricing["completion"]
    return prompt_cost + completion_cost


# ---------------------------------------------------------------------------
# Percentile helper
# ---------------------------------------------------------------------------

def _percentile(sorted_values: List[float], p: float) -> float:
    """Calculate percentile from a sorted list."""
    if not sorted_values:
        return 0.0
    k = (len(sorted_values) - 1) * p / 100.0
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return sorted_values[int(k)]
    d0 = sorted_values[int(f)] * (c - k)
    d1 = sorted_values[int(c)] * (k - f)
    return d0 + d1


# ---------------------------------------------------------------------------
# TelemetryCollector — core metrics aggregator
# ---------------------------------------------------------------------------

class TelemetryCollector:
    """In-memory metrics collector with time-windowed aggregation.

    Thread-safe. All public methods are safe to call from any thread.

    Metrics are retained in sliding windows:
      - latency: last 10,000 records
      - token_usage: last 10,000 records
      - sampled_events: last 1,000 events
    """

    WINDOW_LATENCY = 10_000
    WINDOW_TOKENS = 10_000
    WINDOW_EVENTS = 1_000

    def __init__(self) -> None:
        self._lock = Lock()
        self._latency: Deque[LatencyRecord] = deque(maxlen=self.WINDOW_LATENCY)
        self._token_usage: Deque[TokenUsageRecord] = deque(maxlen=self.WINDOW_TOKENS)
        self._sampled_events: Deque[SampledEvent] = deque(maxlen=self.WINDOW_EVENTS)
        self._counters: Dict[str, int] = {}
        self._gauges: Dict[str, float] = {}
        self._started_at: float = time.time()

    # -- Counters / Gauges --------------------------------------------------

    def increment(self, name: str, value: int = 1) -> None:
        """Increment a named counter."""
        with self._lock:
            self._counters[name] = self._counters.get(name, 0) + value

    def set_gauge(self, name: str, value: float) -> None:
        """Set a named gauge value."""
        with self._lock:
            self._gauges[name] = value

    # -- Latency tracking ---------------------------------------------------

    def record_latency(
        self,
        method: str,
        path: str,
        status_code: int,
        duration_ms: float,
        ttft_ms: Optional[float] = None,
    ) -> None:
        """Record an API latency measurement."""
        rec = LatencyRecord(
            method=method,
            path=path,
            status_code=status_code,
            duration_ms=duration_ms,
            ttft_ms=ttft_ms,
        )
        with self._lock:
            self._latency.append(rec)
        self.increment("api.requests.total")
        if status_code >= 500:
            self.increment("api.errors.5xx")
        elif status_code >= 400:
            self.increment("api.errors.4xx")

    # -- Token / cost tracking ----------------------------------------------

    def record_token_usage(
        self,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
    ) -> None:
        """Record token usage and estimated cost."""
        total = prompt_tokens + completion_tokens
        cost = _estimate_cost(model, prompt_tokens, completion_tokens)
        rec = TokenUsageRecord(
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total,
            estimated_cost_usd=cost,
        )
        with self._lock:
            self._token_usage.append(rec)
        self.increment("tokens.prompt", prompt_tokens)
        self.increment("tokens.completion", completion_tokens)
        self.increment("tokens.total", total)
        self.increment("cost.estimated_usd_cents", int(cost * 100))

    # -- Event sampling -----------------------------------------------------

    def sample_event(
        self,
        event_type: str,
        payload: Dict[str, Any],
        sample_rate: float = 1.0,
    ) -> None:
        """Record a sampled event.

        Args:
            event_type: Category of event (e.g. "tool_call", "agent_loop")
            payload: Event data dict
            sample_rate: Fraction of events to keep (0.0-1.0). 1.0 = all.
        """
        if sample_rate < 1.0 and (hash(str(payload)) % 10000) / 10000 > sample_rate:
            return  # Dropped by sampling
        evt = SampledEvent(
            event_type=event_type,
            payload=payload,
            sample_rate=sample_rate,
        )
        with self._lock:
            self._sampled_events.append(evt)

    # -- Snapshot -----------------------------------------------------------

    def snapshot(self) -> Dict[str, Any]:
        """Get a point-in-time snapshot of all metrics."""
        with self._lock:
            uptime_s = time.time() - self._started_at
            latency_records = list(self._latency)
            token_records = list(self._token_usage)
            event_records = list(self._sampled_events)
            counters = dict(self._counters)
            gauges = dict(self._gauges)

        return {
            "uptime_seconds": round(uptime_s, 1),
            "counters": counters,
            "gauges": gauges,
            "latency": self._compute_latency_stats(latency_records),
            "tokens": self._compute_token_stats(token_records),
            "events": {
                "total_sampled": len(event_records),
                "by_type": self._count_by(event_records, lambda e: e.event_type),
            },
        }

    def latency_for_path(self, path_prefix: str) -> Dict[str, Any]:
        """Get latency stats filtered by path prefix."""
        with self._lock:
            records = [r for r in self._latency if r.path.startswith(path_prefix)]
        return self._compute_latency_stats(records)

    # -- Internal stats computation -----------------------------------------

    @staticmethod
    def _compute_latency_stats(records: List[LatencyRecord]) -> Dict[str, Any]:
        if not records:
            return {"count": 0, "avg_ms": 0, "p50_ms": 0, "p95_ms": 0, "p99_ms": 0}

        durations = sorted(r.duration_ms for r in records)
        ttft_values = [r.ttft_ms for r in records if r.ttft_ms is not None]

        result: Dict[str, Any] = {
            "count": len(durations),
            "avg_ms": round(sum(durations) / len(durations), 1),
            "p50_ms": round(_percentile(durations, 50), 1),
            "p95_ms": round(_percentile(durations, 95), 1),
            "p99_ms": round(_percentile(durations, 99), 1),
            "by_status": {},
            "by_path": {},
        }

        if ttft_values:
            ttft_sorted = sorted(ttft_values)
            result["ttft"] = {
                "count": len(ttft_sorted),
                "avg_ms": round(sum(ttft_sorted) / len(ttft_sorted), 1),
                "p50_ms": round(_percentile(ttft_sorted, 50), 1),
                "p95_ms": round(_percentile(ttft_sorted, 95), 1),
            }

        # Breakdown by status code class
        for r in records:
            status_class = f"{r.status_code // 100}xx"
            key = result["by_status"].setdefault(status_class, {"count": 0, "total_ms": 0.0})
            key["count"] += 1
            key["total_ms"] += r.duration_ms
        for v in result["by_status"].values():
            v["avg_ms"] = round(v["total_ms"] / v["count"], 1) if v["count"] else 0

        # Breakdown by path (top 10)
        path_counts: Dict[str, List[float]] = {}
        for r in records:
            path_counts.setdefault(r.path, []).append(r.duration_ms)
        top_paths = sorted(path_counts.items(), key=lambda x: -len(x[1]))[:10]
        for path, durs in top_paths:
            sorted_durs = sorted(durs)
            result["by_path"][path] = {
                "count": len(durs),
                "avg_ms": round(sum(durs) / len(durs), 1),
                "p50_ms": round(_percentile(sorted_durs, 50), 1),
            }

        return result

    @staticmethod
    def _compute_token_stats(records: List[TokenUsageRecord]) -> Dict[str, Any]:
        if not records:
            return {"count": 0, "total_tokens": 0, "total_cost_usd": 0.0, "by_model": {}}

        total_prompt = sum(r.prompt_tokens for r in records)
        total_completion = sum(r.completion_tokens for r in records)
        total_cost = sum(r.estimated_cost_usd for r in records)

        by_model: Dict[str, Dict[str, Any]] = {}
        for r in records:
            entry = by_model.setdefault(r.model, {
                "count": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "cost_usd": 0.0,
            })
            entry["count"] += 1
            entry["prompt_tokens"] += r.prompt_tokens
            entry["completion_tokens"] += r.completion_tokens
            entry["total_tokens"] += r.total_tokens
            entry["cost_usd"] = round(entry["cost_usd"] + r.estimated_cost_usd, 6)

        return {
            "count": len(records),
            "prompt_tokens": total_prompt,
            "completion_tokens": total_completion,
            "total_tokens": total_prompt + total_completion,
            "total_cost_usd": round(total_cost, 6),
            "by_model": by_model,
        }

    @staticmethod
    def _count_by(items: List[Any], key_fn) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for item in items:
            k = key_fn(item)
            counts[k] = counts.get(k, 0) + 1
        return counts


# ---------------------------------------------------------------------------
# Module-level singleton and convenience functions
# ---------------------------------------------------------------------------

telemetry = TelemetryCollector()


def track_api_latency(
    method: str,
    path: str,
    status_code: int,
    duration_ms: float,
    ttft_ms: Optional[float] = None,
) -> None:
    """Convenience: record an API latency measurement."""
    telemetry.record_latency(method, path, status_code, duration_ms, ttft_ms)


def record_token_usage(
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
) -> None:
    """Convenience: record token usage."""
    telemetry.record_token_usage(model, prompt_tokens, completion_tokens)


def record_sampled_event(
    event_type: str,
    payload: Dict[str, Any],
    sample_rate: float = 1.0,
) -> None:
    """Convenience: record a sampled event."""
    telemetry.sample_event(event_type, payload, sample_rate)
