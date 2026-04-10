# -*- coding: utf-8 -*-
"""Aegis quality gate system.

MC-006: Tasks must pass quality review before final completion.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional

from src.runtime.stores.db import get_db


class ReviewStatus(str, Enum):
    APPROVED = "approved"
    REJECTED = "rejected"
    NEEDS_CHANGES = "needs_changes"


@dataclass
class QualityReview:
    id: int
    task_id: str
    reviewer: str
    status: ReviewStatus
    notes: str
    workspace_id: int
    created_at: float


@dataclass
class GateDecision:
    allowed: bool
    reason: str
    latest_review: Optional[QualityReview] = None


class AegisQualityGate:
    """Quality review gate for task completion."""

    def __init__(self):
        self._db = get_db()

    def submit_review(
        self,
        task_id: str,
        reviewer: str,
        status: ReviewStatus,
        notes: str = "",
        workspace_id: int = 1,
    ) -> int:
        """Submit a quality review and auto-transition task state."""
        now = time.time()
        with self._db.transaction() as conn:
            cursor = conn.execute(
                """
                INSERT INTO quality_reviews (task_id, reviewer, status, notes, workspace_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (str(task_id), reviewer, status.value, notes, workspace_id, now),
            )
            review_id = int(cursor.lastrowid)

            # Auto-advance task based on review outcome
            if status == ReviewStatus.APPROVED:
                conn.execute(
                    """
                    UPDATE tasks
                    SET status = 'done', completed_at = COALESCE(completed_at, ?)
                    WHERE id = ?
                    """,
                    (now, str(task_id)),
                )
            else:
                conn.execute(
                    """
                    UPDATE tasks
                    SET status = 'in_progress', error_message = ?
                    WHERE id = ?
                    """,
                    (f"Quality review {status.value} by {reviewer}: {notes}".strip(), str(task_id)),
                )

            return review_id

    def get_reviews(self, task_id: str, workspace_id: int = 1, limit: int = 10) -> List[QualityReview]:
        rows = self._db.execute_fetchall(
            """
            SELECT * FROM quality_reviews
            WHERE task_id = ? AND workspace_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (str(task_id), workspace_id, limit),
        )
        result: List[QualityReview] = []
        for row in rows:
            try:
                row_data = dict(row)
                result.append(
                    QualityReview(
                        id=int(row_data.get("id") or 0),
                        task_id=str(row_data.get("task_id") or ""),
                        reviewer=str(row_data.get("reviewer") or ""),
                        status=ReviewStatus(str(row_data.get("status") or "needs_changes")),
                        notes=str(row_data.get("notes") or ""),
                        workspace_id=int(row_data.get("workspace_id") or workspace_id),
                        created_at=float(row_data.get("created_at") or 0),
                    )
                )
            except Exception:
                continue
        return result

    def get_latest_review(self, task_id: str, workspace_id: int = 1) -> Optional[QualityReview]:
        reviews = self.get_reviews(task_id=task_id, workspace_id=workspace_id, limit=1)
        return reviews[0] if reviews else None

    def check_completion_gate(self, task_id: str, workspace_id: int = 1) -> GateDecision:
        """Check whether task can be considered quality-gate passed."""
        latest = self.get_latest_review(task_id=task_id, workspace_id=workspace_id)
        if latest is None:
            return GateDecision(
                allowed=False,
                reason="No quality review found",
                latest_review=None,
            )

        if latest.status == ReviewStatus.APPROVED:
            return GateDecision(
                allowed=True,
                reason="Quality review approved",
                latest_review=latest,
            )

        return GateDecision(
            allowed=False,
            reason=f"Latest quality review status: {latest.status.value}",
            latest_review=latest,
        )

    def get_latest_by_tasks(
        self,
        task_ids: List[str],
        workspace_id: int = 1,
    ) -> Dict[str, Optional[QualityReview]]:
        """Return latest review per task id."""
        result: Dict[str, Optional[QualityReview]] = {str(tid): None for tid in task_ids}
        for tid in task_ids:
            result[str(tid)] = self.get_latest_review(str(tid), workspace_id=workspace_id)
        return result


_gate: Optional[AegisQualityGate] = None


def get_quality_gate() -> AegisQualityGate:
    global _gate
    if _gate is None:
        _gate = AegisQualityGate()
    return _gate
