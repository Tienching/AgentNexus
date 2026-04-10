# -*- coding: utf-8 -*-
"""Four-layer evaluation framework for agent outputs.

Provides comprehensive evaluation:
- Output evaluation: Quality of generated outputs
- Trace evaluation: Execution trace analysis
- Component evaluation: Individual component assessment
- Drift detection: Deviation from expected behavior

Usage:
    from src.core.evals.framework import EvaluationFramework, EvalResult

    framework = EvaluationFramework()
    result = await framework.evaluate(
        task="Generate a report",
        output="Generated report text...",
        context={"task_id": "123"},
    )
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from loguru import logger


# ---------------------------------------------------------------------------
# Evaluation types
# ---------------------------------------------------------------------------

class EvalLevel(str, Enum):
    """Evaluation layers."""
    OUTPUT = "output"      # Quality of generated outputs
    TRACE = "trace"        # Execution trace analysis
    COMPONENT = "component"  # Individual component assessment
    DRIFT = "drift"        # Deviation from expected behavior


class EvalSeverity(str, Enum):
    """Severity of detected issues."""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


# ---------------------------------------------------------------------------
# Evaluation result models
# ---------------------------------------------------------------------------

@dataclass
class EvalFinding:
    """A single finding from evaluation."""
    level: EvalLevel
    severity: EvalSeverity
    rule: str
    message: str
    detail: Optional[str] = None
    score_impact: float = 0.0  # How much this affects the overall score


@dataclass
class EvalResult:
    """Result of a comprehensive evaluation."""
    task_id: str
    overall_score: float  # 0.0 to 1.0
    passed: bool
    findings: List[EvalFinding] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    duration_ms: float = 0.0
    evaluated_at: float = field(default_factory=time.time)

    def add_finding(self, finding: EvalFinding) -> None:
        """Add a finding and update score."""
        self.findings.append(finding)
        self.overall_score = max(0.0, self.overall_score + finding.score_impact)
        self.passed = self.overall_score >= 0.7

    def summary(self) -> str:
        """Get a human-readable summary."""
        by_level: Dict[EvalLevel, int] = {}
        for f in self.findings:
            by_level[f.level] = by_level.get(f.level, 0) + 1
        level_str = ", ".join(f"{k.value}:{v}" for k, v in by_level.items())
        return f"Score: {self.overall_score:.2f} ({'PASS' if self.passed else 'FAIL'}) - {level_str}"


# ---------------------------------------------------------------------------
# Evaluation rules
# ---------------------------------------------------------------------------

@dataclass
class EvalRule:
    """A single evaluation rule."""
    name: str
    level: EvalLevel
    severity: EvalSeverity
    check: Callable[["EvaluationFramework", str, Any], Optional[EvalFinding]]
    enabled: bool = True


class EvaluationFramework:
    """Four-layer evaluation framework."""

    def __init__(self):
        self._rules: List[EvalRule] = []
        self._register_default_rules()

    def _register_default_rules(self) -> None:
        """Register the default evaluation rules."""

        # Output evaluation rules
        self.add_rule(EvalRule(
            name="output_length",
            level=EvalLevel.OUTPUT,
            severity=EvalSeverity.INFO,
            check=self._check_output_length,
        ))

        self.add_rule(EvalRule(
            name="output_format",
            level=EvalLevel.OUTPUT,
            severity=EvalSeverity.WARNING,
            check=self._check_output_format,
        ))

        self.add_rule(EvalRule(
            name="output_completeness",
            level=EvalLevel.OUTPUT,
            severity=EvalSeverity.ERROR,
            check=self._check_output_completeness,
        ))

        # Trace evaluation rules
        self.add_rule(EvalRule(
            name="trace_tool_count",
            level=EvalLevel.TRACE,
            severity=EvalSeverity.INFO,
            check=self._check_trace_tool_count,
        ))

        self.add_rule(EvalRule(
            name="trace_error_rate",
            level=EvalLevel.TRACE,
            severity=EvalSeverity.ERROR,
            check=self._check_trace_error_rate,
        ))

        # Component evaluation rules
        self.add_rule(EvalRule(
            name="component_latency",
            level=EvalLevel.COMPONENT,
            severity=EvalSeverity.WARNING,
            check=self._check_component_latency,
        ))

        # Drift detection rules
        self.add_rule(EvalRule(
            name="drift_detected",
            level=EvalLevel.DRIFT,
            severity=EvalSeverity.CRITICAL,
            check=self._check_drift,
        ))

    def add_rule(self, rule: EvalRule) -> None:
        """Add an evaluation rule."""
        self._rules.append(rule)

    def remove_rule(self, name: str) -> bool:
        """Remove a rule by name."""
        for i, rule in enumerate(self._rules):
            if rule.name == name:
                self._rules.pop(i)
                return True
        return False

    async def evaluate(
        self,
        task: str,
        output: Any,
        context: Optional[Dict[str, Any]] = None,
    ) -> EvalResult:
        """Run comprehensive evaluation.

        Args:
            task: Task description
            output: The output to evaluate
            context: Additional context (traces, components, etc.)

        Returns:
            EvalResult with overall score and findings
        """
        start_time = time.time()
        context = context or {}

        result = EvalResult(
            task_id=self._hash_task(task),
            overall_score=1.0,
            passed=True,
        )

        for rule in self._rules:
            if not rule.enabled:
                continue

            try:
                finding = rule.check(self, task, output, context)
                if finding:
                    result.add_finding(finding)
            except Exception as e:
                logger.warning(f"Rule {rule.name} failed: {e}")

        result.duration_ms = (time.time() - start_time) * 1000
        return result

    # ---------------------------------------------------------------------------
    # Built-in evaluation checks
    # ---------------------------------------------------------------------------

    @staticmethod
    def _check_output_length(
        task: str,
        output: Any,
        context: Dict[str, Any],
    ) -> Optional[EvalFinding]:
        """Check if output length is reasonable."""
        if not isinstance(output, str):
            return None

        length = len(output)

        # Too short
        if length < 10:
            return EvalFinding(
                level=EvalLevel.OUTPUT,
                severity=EvalSeverity.WARNING,
                rule="output_length",
                message="Output is suspiciously short",
                detail=f"Only {length} characters",
                score_impact=-0.1,
            )

        # Too long (potential token waste)
        if length > 50000:
            return EvalFinding(
                level=EvalLevel.OUTPUT,
                severity=EvalSeverity.INFO,
                rule="output_length",
                message="Output is very long",
                detail=f"{length} characters - may indicate verbosity",
                score_impact=-0.05,
            )

        return None

    @staticmethod
    def _check_output_format(
        self,
        task: str,
        output: Any,
        context: Dict[str, Any],
    ) -> Optional[EvalFinding]:
        """Check if output matches expected format."""
        if not isinstance(output, str):
            return None

        # Check for common format issues
        if output.startswith(" ") or output.endswith(" "):
            return EvalFinding(
                level=EvalLevel.OUTPUT,
                severity=EvalSeverity.INFO,
                rule="output_format",
                message="Output has leading/trailing whitespace",
                score_impact=-0.02,
            )

        return None

    @staticmethod
    def _check_output_completeness(
        self,
        task: str,
        output: Any,
        context: Dict[str, Any],
    ) -> Optional[EvalFinding]:
        """Check if output appears complete."""
        if not isinstance(output, str):
            return None

        # Check for incomplete indicators
        incomplete_patterns = [
            "...",
            "to be continued",
            "[incomplete]",
            "[not finished]",
            "TODO",
            "FIXME",
        ]

        lower_output = output.lower()
        for pattern in incomplete_patterns:
            if pattern.lower() in lower_output:
                return EvalFinding(
                    level=EvalLevel.OUTPUT,
                    severity=EvalSeverity.ERROR,
                    rule="output_completeness",
                    message=f"Output appears incomplete (found '{pattern}')",
                    score_impact=-0.2,
                )

        return None

    @staticmethod
    def _check_trace_tool_count(
        self,
        task: str,
        output: Any,
        context: Dict[str, Any],
    ) -> Optional[EvalFinding]:
        """Check if trace has reasonable tool count."""
        traces = context.get("traces", [])
        if not traces:
            return None

        tool_count = len([t for t in traces if t.get("type") == "tool_call"])

        if tool_count > 100:
            return EvalFinding(
                level=EvalLevel.TRACE,
                severity=EvalSeverity.INFO,
                rule="trace_tool_count",
                message=f"High tool call count: {tool_count}",
                detail="May indicate excessive iteration",
                score_impact=-0.05,
            )

        return None

    @staticmethod
    def _check_trace_error_rate(
        self,
        task: str,
        output: Any,
        context: Dict[str, Any],
    ) -> Optional[EvalFinding]:
        """Check trace error rate."""
        traces = context.get("traces", [])
        if not traces:
            return None

        errors = len([t for t in traces if t.get("status") == "error"])
        error_rate = errors / len(traces) if traces else 0

        if error_rate > 0.1:
            return EvalFinding(
                level=EvalLevel.TRACE,
                severity=EvalSeverity.ERROR,
                rule="trace_error_rate",
                message=f"High error rate: {error_rate:.1%}",
                score_impact=-0.3,
            )

        return None

    @staticmethod
    def _check_component_latency(
        self,
        task: str,
        output: Any,
        context: Dict[str, Any],
    ) -> Optional[EvalFinding]:
        """Check component latency."""
        components = context.get("components", [])
        if not components:
            return None

        slow_components = [
            c for c in components
            if c.get("latency_ms", 0) > 5000
        ]

        if slow_components:
            names = ", ".join(c.get("name", "unknown") for c in slow_components[:3])
            return EvalFinding(
                level=EvalLevel.COMPONENT,
                severity=EvalSeverity.WARNING,
                rule="component_latency",
                message=f"Slow components detected: {names}",
                score_impact=-0.1,
            )

        return None

    @staticmethod
    def _check_drift(
        self,
        task: str,
        output: Any,
        context: Dict[str, Any],
    ) -> Optional[EvalFinding]:
        """Check for behavioral drift."""
        # Compare with baseline if available
        baseline = context.get("baseline")
        if not baseline:
            return None

        current_hash = self._hash_output(output)
        if current_hash == baseline:
            return None  # No drift

        # Calculate drift severity based on how different
        drift_score = self._calculate_drift(output, baseline)

        return EvalFinding(
            level=EvalLevel.DRIFT,
            severity=EvalSeverity.WARNING if drift_score < 0.5 else EvalSeverity.CRITICAL,
            rule="drift_detected",
            message=f"Behavioral drift detected (score: {drift_score:.2f})",
            detail="Output differs significantly from baseline",
            score_impact=-0.2 if drift_score < 0.5 else -0.4,
        )

    # ---------------------------------------------------------------------------
    # Utility methods
    # ---------------------------------------------------------------------------

    def _hash_task(self, task: str) -> str:
        """Generate a hash for a task."""
        return hashlib.sha256(task.encode()).hexdigest()[:12]

    def _hash_output(self, output: Any) -> str:
        """Generate a hash for output."""
        if isinstance(output, (dict, list)):
            content = json.dumps(output, sort_keys=True)
        else:
            content = str(output)
        return hashlib.sha256(content.encode()).hexdigest()

    def _calculate_drift(self, output: Any, baseline: Any) -> float:
        """Calculate drift score between output and baseline.

        Returns:
            Float between 0.0 (identical) and 1.0 (completely different)
        """
        if output == baseline:
            return 0.0
        return 0.5  # Default moderate drift for now
