# -*- coding: utf-8 -*-
"""Agent trust scoring system.

MC-016: Calculates and explains trust scores based on agent behavior history.
Backed by `agent_trust_scores` and `security_events` tables introduced in MC-015.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from src.runtime.stores.db import get_db
from src.core.security.auditor import TRUST_WEIGHTS


@dataclass
class TrustScoreBreakdown:
    agent_name: str
    workspace_id: int
    trust_score: float
    trust_level: str
    auth_failures: int
    injection_attempts: int
    rate_limit_hits: int
    secret_exposures: int
    successful_tasks: int
    failed_tasks: int
    risk_signals: int
    positive_signals: int
    rationale: List[str]


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _trust_level(score: float) -> str:
    if score >= 0.90:
        return "high"
    if score >= 0.70:
        return "medium"
    if score >= 0.40:
        return "low"
    return "critical"


class AgentTrustScoringService:
    """Trust scoring service with explainable scoring outputs."""

    def __init__(self):
        self._db = get_db()

    def ensure_agent(self, agent_name: str, workspace_id: int = 1) -> None:
        """Ensure trust score row exists for an agent."""
        with self._db.transaction() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO agent_trust_scores (agent_name, workspace_id, trust_score, updated_at)
                VALUES (?, ?, 1.0, strftime('%s','now'))
                """,
                (agent_name, workspace_id),
            )

    def apply_event(self, agent_name: str, event_type: str, workspace_id: int = 1) -> Optional[float]:
        """Apply an event to trust scoring and return updated score.

        Returns None if event_type is not tracked.
        """
        weight = TRUST_WEIGHTS.get(event_type)
        if not weight:
            return None

        self.ensure_agent(agent_name, workspace_id)

        with self._db.transaction() as conn:
            conn.execute(
                f"""
                UPDATE agent_trust_scores
                SET {weight['field']} = {weight['field']} + 1,
                    updated_at = strftime('%s','now')
                WHERE agent_name = ? AND workspace_id = ?
                """,
                (agent_name, workspace_id),
            )

            row = conn.execute(
                """
                SELECT * FROM agent_trust_scores
                WHERE agent_name = ? AND workspace_id = ?
                """,
                (agent_name, workspace_id),
            ).fetchone()

            if not row:
                return None

            score = self._compute_score_from_row(dict(row))
            conn.execute(
                """
                UPDATE agent_trust_scores
                SET trust_score = ?,
                    last_anomaly_at = CASE WHEN ? THEN strftime('%s','now') ELSE last_anomaly_at END,
                    updated_at = strftime('%s','now')
                WHERE agent_name = ? AND workspace_id = ?
                """,
                (score, 1 if weight["delta"] < 0 else 0, agent_name, workspace_id),
            )
            return score

    def get_agent_breakdown(self, agent_name: str, workspace_id: int = 1) -> Optional[TrustScoreBreakdown]:
        """Get explainable trust score breakdown for one agent."""
        row = self._db.execute_fetchone(
            """
            SELECT * FROM agent_trust_scores
            WHERE agent_name = ? AND workspace_id = ?
            """,
            (agent_name, workspace_id),
        )
        if not row:
            return None

        score = float(row.get("trust_score") or self._compute_score_from_row(row))
        auth_failures = int(row.get("auth_failures") or 0)
        injection_attempts = int(row.get("injection_attempts") or 0)
        rate_limit_hits = int(row.get("rate_limit_hits") or 0)
        secret_exposures = int(row.get("secret_exposures") or 0)
        successful_tasks = int(row.get("successful_tasks") or 0)
        failed_tasks = int(row.get("failed_tasks") or 0)

        risk_signals = auth_failures + injection_attempts + rate_limit_hits + secret_exposures + failed_tasks
        positive_signals = successful_tasks

        rationale: List[str] = []
        if secret_exposures > 0:
            rationale.append(f"secret_exposures={secret_exposures} significantly lowers trust")
        if injection_attempts > 0:
            rationale.append(f"injection_attempts={injection_attempts} lowers trust")
        if successful_tasks > 0:
            rationale.append(f"successful_tasks={successful_tasks} improves trust")
        if failed_tasks > 0:
            rationale.append(f"failed_tasks={failed_tasks} slightly lowers trust")
        if not rationale:
            rationale.append("no significant events recorded")

        return TrustScoreBreakdown(
            agent_name=agent_name,
            workspace_id=workspace_id,
            trust_score=round(score, 4),
            trust_level=_trust_level(score),
            auth_failures=auth_failures,
            injection_attempts=injection_attempts,
            rate_limit_hits=rate_limit_hits,
            secret_exposures=secret_exposures,
            successful_tasks=successful_tasks,
            failed_tasks=failed_tasks,
            risk_signals=risk_signals,
            positive_signals=positive_signals,
            rationale=rationale,
        )

    def list_ranked_agents(self, workspace_id: int = 1, limit: int = 100) -> List[TrustScoreBreakdown]:
        """List agents sorted by trust score ascending (highest risk first)."""
        rows = self._db.execute_fetchall(
            """
            SELECT *
            FROM agent_trust_scores
            WHERE workspace_id = ?
            ORDER BY trust_score ASC, updated_at DESC
            LIMIT ?
            """,
            (workspace_id, limit),
        )

        result: List[TrustScoreBreakdown] = []
        for row in rows:
            breakdown = self.get_agent_breakdown(row["agent_name"], workspace_id)
            if breakdown:
                result.append(breakdown)
        return result

    @staticmethod
    def _compute_score_from_row(row: Dict[str, Any]) -> float:
        score = 1.0
        score += float(row.get("auth_failures") or 0) * -0.05
        score += float(row.get("injection_attempts") or 0) * -0.15
        score += float(row.get("rate_limit_hits") or 0) * -0.03
        score += float(row.get("secret_exposures") or 0) * -0.20
        score += float(row.get("successful_tasks") or 0) * 0.02
        score += float(row.get("failed_tasks") or 0) * -0.01
        return _clamp01(score)


_service: Optional[AgentTrustScoringService] = None


def get_trust_scoring_service() -> AgentTrustScoringService:
    global _service
    if _service is None:
        _service = AgentTrustScoringService()
    return _service
