# -*- coding: utf-8 -*-
"""Skill security scanner.

MC-008: Detects security risks in skill code/content, including:
- Prompt injection markers
- Credential leakage
- Data exfiltration behavior
- Obfuscated content
- Dangerous runtime execution patterns
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Literal

SecurityRiskValue = Literal["low", "medium", "high", "critical"]


@dataclass(frozen=True)
class ScanFinding:
    category: str
    pattern: str
    description: str
    risk: SecurityRiskValue


_RISK_ORDER: Dict[SecurityRiskValue, int] = {
    "low": 1,
    "medium": 2,
    "high": 3,
    "critical": 4,
}


def _max_risk(current: SecurityRiskValue, candidate: SecurityRiskValue) -> SecurityRiskValue:
    return candidate if _RISK_ORDER[candidate] > _RISK_ORDER[current] else current


class SkillSecurityScanner:
    """Scans skills for security issues and returns structured findings."""

    # Prompt injection / jailbreak patterns
    PROMPT_INJECTION_PATTERNS = [
        (r"ignore\s+(all\s+)?previous\s+instructions", "Attempts to override instruction hierarchy", "high"),
        (r"reveal\s+(the\s+)?system\s+prompt", "Attempts to exfiltrate system prompt", "high"),
        (r"jailbreak|DAN\s+mode", "Jailbreak-style instruction", "high"),
        (r"bypass\s+(security|safety|guardrails?)", "Explicit safety bypass directive", "critical"),
        (r"do\s+not\s+follow\s+the\s+above\s+rules", "Rule override attempt", "high"),
    ]

    # Hardcoded credentials / secrets
    CREDENTIAL_PATTERNS = [
        (r"api[_-]?key\s*=\s*['\"][A-Za-z0-9_\-]{16,}['\"]", "Hardcoded API key", "critical"),
        (r"secret[_-]?key\s*=\s*['\"][^'\"]{12,}['\"]", "Hardcoded secret key", "critical"),
        (r"password\s*=\s*['\"][^'\"]{8,}['\"]", "Hardcoded password", "critical"),
        (r"token\s*=\s*['\"][A-Za-z0-9_\-\.]{16,}['\"]", "Hardcoded token", "critical"),
        (r"-----BEGIN\s+(RSA|EC|OPENSSH)\s+PRIVATE\s+KEY-----", "Embedded private key", "critical"),
    ]

    # Data exfiltration behavior
    DATA_EXFIL_PATTERNS = [
        (r"requests\.(post|put)\s*\(", "Outbound HTTP write request", "medium"),
        (r"urllib\.request\.(urlopen|Request)\s*\(", "Outbound urllib request", "medium"),
        (r"socket\.(socket|create_connection)\s*\(", "Raw socket communication", "high"),
        (r"(base64\.b64encode|binascii\.hexlify).{0,120}(requests\.|socket\.)", "Encoded outbound payload", "high"),
    ]

    # Obfuscation / hidden execution
    OBFUSCATION_PATTERNS = [
        (r"base64\.b64decode\s*\(", "Base64 decode at runtime", "medium"),
        (r"marshal\.loads\s*\(", "Bytecode payload loading", "high"),
        (r"zlib\.decompress\s*\(", "Compressed payload expansion", "medium"),
        (r"exec\s*\(\s*eval\s*\(", "Nested dynamic execution", "critical"),
        (r"__import__\s*\(", "Dynamic import construction", "high"),
        (r"chr\s*\(.+\)\s*\+\s*chr\s*\(", "Character-concatenation obfuscation", "medium"),
    ]

    # Dangerous runtime operations
    DANGEROUS_PATTERNS = [
        (r"os\.system\s*\(", "Shell command execution", "high"),
        (r"subprocess\.(run|Popen|call|check_output)\s*\(", "Subprocess execution", "high"),
        (r"eval\s*\(", "Dynamic eval execution", "high"),
        (r"exec\s*\(", "Dynamic exec execution", "high"),
        (r"pickle\.loads?\s*\(", "Unsafe deserialization via pickle", "high"),
        (r"open\s*\([^\)]*['\"]w['\"]", "File write operation", "medium"),
    ]

    def scan(self, skill_code: str) -> Dict[str, Any]:
        """Scan a skill source string and return risk report."""
        text = skill_code or ""
        findings: List[Dict[str, Any]] = []
        max_risk: SecurityRiskValue = "low"

        for category, rules in (
            ("prompt_injection", self.PROMPT_INJECTION_PATTERNS),
            ("credential_leakage", self.CREDENTIAL_PATTERNS),
            ("data_exfiltration", self.DATA_EXFIL_PATTERNS),
            ("obfuscated_content", self.OBFUSCATION_PATTERNS),
            ("dangerous_runtime", self.DANGEROUS_PATTERNS),
        ):
            for pattern, description, risk in rules:
                if re.search(pattern, text, flags=re.IGNORECASE | re.MULTILINE | re.DOTALL):
                    findings.append(
                        {
                            "category": category,
                            "pattern": pattern,
                            "description": description,
                            "risk": risk,
                        }
                    )
                    max_risk = _max_risk(max_risk, risk)  # type: ignore[arg-type]

        category_summary: Dict[str, int] = {}
        for item in findings:
            category_summary[item["category"]] = category_summary.get(item["category"], 0) + 1

        return {
            "risk": max_risk,
            "findings": findings,
            "category_summary": category_summary,
            "finding_count": len(findings),
            "scanned_at": time.time(),
        }
