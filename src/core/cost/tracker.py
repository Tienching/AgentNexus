# -*- coding: utf-8 -*-
"""Token usage tracking and cost analysis.

Provides persistent token usage tracking with per-model breakdown,
trend analysis, and cost estimation.

Usage:
    from src.core.cost.tracker import TokenTracker, get_token_tracker

    tracker = get_token_tracker()
    tracker.record(model="gpt-4o", prompt_tokens=1200, completion_tokens=350)
    stats = tracker.get_stats()
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
from collections import defaultdict

from src.runtime.stores.db import get_db


# Model pricing (approximate, per 1M tokens as of 2025)
MODEL_PRICING: Dict[str, Dict[str, float]] = {
    # OpenAI
    "gpt-4o": {"prompt": 5.00, "completion": 15.00},
    "gpt-4-turbo": {"prompt": 10.00, "completion": 30.00},
    "gpt-4": {"prompt": 30.00, "completion": 60.00},
    "gpt-3.5-turbo": {"prompt": 0.50, "completion": 1.50},
    # Anthropic
    "claude-3-opus": {"prompt": 15.00, "completion": 75.00},
    "claude-3-sonnet": {"prompt": 3.00, "completion": 15.00},
    "claude-3-haiku": {"prompt": 0.25, "completion": 1.25},
    "claude-2": {"prompt": 8.00, "completion": 24.00},
    # Google
    "gemini-pro": {"prompt": 0.125, "completion": 0.375},
    "gemini-ultra": {"prompt": 1.25, "completion": 5.00},
    # DeepSeek
    "deepseek-chat": {"prompt": 0.14, "completion": 0.28},
    "deepseek-coder": {"prompt": 0.14, "completion": 0.28},
    # Local/Others (generic estimate)
    "local": {"prompt": 0.01, "completion": 0.01},
}

# Default pricing for unknown models
DEFAULT_PRICING = {"prompt": 1.00, "completion": 3.00}


@dataclass
class TokenRecord:
    """A single token usage record."""
    id: Optional[int] = None
    model: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: float = 0.0
    timestamp: float = field(default_factory=time.time)


@dataclass
class ModelStats:
    """Token usage statistics for a single model."""
    model: str
    request_count: int = 0
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    avg_prompt_tokens: float = 0.0
    avg_completion_tokens: float = 0.0
    avg_latency_ms: float = 0.0


@dataclass
class TokenStats:
    """Overall token usage statistics."""
    total_requests: int = 0
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    by_model: Dict[str, ModelStats] = field(default_factory=dict)


class TokenTracker:
    """Persistent token usage tracker with cost analysis.

    Stores token usage records in SQLite and provides aggregated statistics.
    """

    def __init__(self):
        self._db = get_db()
        self._ensure_table()

    def _ensure_table(self) -> None:
        """Create the token_usage table if it doesn't exist."""
        self._db.execute("""
            CREATE TABLE IF NOT EXISTS token_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                model TEXT NOT NULL,
                prompt_tokens INTEGER NOT NULL,
                completion_tokens INTEGER NOT NULL,
                total_tokens INTEGER NOT NULL,
                cost_usd REAL NOT NULL DEFAULT 0,
                latency_ms REAL NOT NULL DEFAULT 0,
                timestamp REAL NOT NULL
            )
        """)
        self._db.execute("""
            CREATE INDEX IF NOT EXISTS idx_token_usage_model
            ON token_usage (model)
        """)
        self._db.execute("""
            CREATE INDEX IF NOT EXISTS idx_token_usage_timestamp
            ON token_usage (timestamp DESC)
        """)

    def _estimate_cost(self, model: str, prompt_tokens: int, completion_tokens: int) -> float:
        """Estimate cost for a model based on token counts."""
        pricing = MODEL_PRICING.get(model, DEFAULT_PRICING)
        prompt_cost = (prompt_tokens / 1_000_000) * pricing["prompt"]
        completion_cost = (completion_tokens / 1_000_000) * pricing["completion"]
        return prompt_cost + completion_cost

    def record(
        self,
        model: str,
        prompt_tokens: int,
        completion_tokens: int = 0,
        latency_ms: float = 0.0,
    ) -> TokenRecord:
        """Record token usage for a single request.

        Args:
            model: Model name (e.g., "gpt-4o")
            prompt_tokens: Number of prompt tokens
            completion_tokens: Number of completion tokens
            latency_ms: Request latency in milliseconds

        Returns:
            The created TokenRecord
        """
        total = prompt_tokens + completion_tokens
        cost = self._estimate_cost(model, prompt_tokens, completion_tokens)

        record = TokenRecord(
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total,
            cost_usd=cost,
            latency_ms=latency_ms,
        )

        with self._db.transaction() as conn:
            cursor = conn.execute(
                """
                INSERT INTO token_usage (model, prompt_tokens, completion_tokens, total_tokens, cost_usd, latency_ms, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (model, prompt_tokens, completion_tokens, total, cost, latency_ms, record.timestamp),
            )
            record.id = cursor.lastrowid

        return record

    def get_stats(
        self,
        since: Optional[float] = None,
        model: Optional[str] = None,
    ) -> TokenStats:
        """Get aggregated token statistics.

        Args:
            since: Unix timestamp to filter records (default: last 7 days)
            model: Optional model filter

        Returns:
            TokenStats with aggregated data
        """
        if since is None:
            since = time.time() - (7 * 24 * 60 * 60)  # 7 days ago

        sql = """
            SELECT
                model,
                COUNT(*) as request_count,
                SUM(prompt_tokens) as total_prompt,
                SUM(completion_tokens) as total_completion,
                SUM(total_tokens) as total_tokens,
                SUM(cost_usd) as total_cost,
                AVG(latency_ms) as avg_latency
            FROM token_usage
            WHERE timestamp >= ?
        """
        params: List[Any] = [since]

        if model:
            sql += " AND model = ?"
            params.append(model)

        sql += " GROUP BY model"

        try:
            rows = self._db.execute_fetchall(sql, tuple(params))
        except Exception:
            return TokenStats()

        stats = TokenStats()
        stats.total_requests = sum(r["request_count"] for r in rows)
        stats.total_prompt_tokens = sum(r["total_prompt"] or 0 for r in rows)
        stats.total_completion_tokens = sum(r["total_completion"] or 0 for r in rows)
        stats.total_tokens = sum(r["total_tokens"] or 0 for r in rows)
        stats.total_cost_usd = sum(r["total_cost"] or 0.0 for r in rows)

        for row in rows:
            model_name = row["model"]
            count = row["request_count"] or 0
            model_stats = ModelStats(
                model=model_name,
                request_count=count,
                total_prompt_tokens=row["total_prompt"] or 0,
                total_completion_tokens=row["total_completion"] or 0,
                total_tokens=row["total_tokens"] or 0,
                total_cost_usd=row["total_cost"] or 0.0,
                avg_prompt_tokens=(row["total_prompt"] or 0) / count if count > 0 else 0,
                avg_completion_tokens=(row["total_completion"] or 0) / count if count > 0 else 0,
                avg_latency_ms=row["avg_latency"] or 0,
            )
            stats.by_model[model_name] = model_stats

        return stats

    def get_daily_breakdown(self, days: int = 7) -> List[Dict[str, Any]]:
        """Get daily token usage breakdown.

        Args:
            days: Number of days to include (default 7)

        Returns:
            List of daily summaries with date, tokens, and cost
        """
        since = time.time() - (days * 24 * 60 * 60)

        sql = """
            SELECT
                date(timestamp, 'unixepoch') as date,
                model,
                SUM(prompt_tokens) as prompt,
                SUM(completion_tokens) as completion,
                SUM(total_tokens) as total,
                SUM(cost_usd) as cost
            FROM token_usage
            WHERE timestamp >= ?
            GROUP BY date, model
            ORDER BY date DESC, model
        """

        try:
            rows = self._db.execute_fetchall(sql, (since,))
        except Exception:
            return []

        # Group by date
        by_date: Dict[str, Dict[str, Any]] = defaultdict(lambda: {
            "date": "",
            "total_prompt": 0,
            "total_completion": 0,
            "total_tokens": 0,
            "total_cost": 0.0,
            "by_model": {},
        })

        for row in rows:
            date = row["date"]
            if not by_date[date]["date"]:
                by_date[date]["date"] = date
            by_date[date]["total_prompt"] += row["prompt"] or 0
            by_date[date]["total_completion"] += row["completion"] or 0
            by_date[date]["total_tokens"] += row["total"] or 0
            by_date[date]["total_cost"] += row["cost"] or 0.0
            by_date[date]["by_model"][row["model"]] = {
                "prompt": row["prompt"] or 0,
                "completion": row["completion"] or 0,
                "total": row["total"] or 0,
                "cost": row["cost"] or 0.0,
            }

        return list(by_date.values())

    def get_model_list(self) -> List[str]:
        """Get list of all models that have usage records."""
        sql = "SELECT DISTINCT model FROM token_usage ORDER BY model"
        try:
            rows = self._db.execute_fetchall(sql)
            return [r["model"] for r in rows]
        except Exception:
            return []


# Global tracker instance
_token_tracker: Optional[TokenTracker] = None


def get_token_tracker() -> TokenTracker:
    """Get the global TokenTracker instance."""
    global _token_tracker
    if _token_tracker is None:
        _token_tracker = TokenTracker()
    return _token_tracker


def record_token_usage(
    model: str,
    prompt_tokens: int,
    completion_tokens: int = 0,
    latency_ms: float = 0.0,
) -> TokenRecord:
    """Convenience function to record token usage."""
    return get_token_tracker().record(
        model=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        latency_ms=latency_ms,
    )
