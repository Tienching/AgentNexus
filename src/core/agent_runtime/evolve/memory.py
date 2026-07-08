"""Memory system for the self-evolution framework.

Implements a two-tier memory architecture:
  - Archive: JSONL files that grow indefinitely (never compressed)
  - Active: Synthesized markdown files loaded into each session's prompt

Learnings are appended to archives. A daily synthesis job generates
time-weighted summaries for the active context.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger

from src.core.agent_runtime.evolve.models import EvolutionConfig, Lesson, SocialInsight


class MemoryManager:
    """Manages the two-tier memory system (archive + active context)."""

    def __init__(self, config: EvolutionConfig):
        self.config = config
        self._base = Path(config.memory_path).resolve()
        self._base.mkdir(parents=True, exist_ok=True)

    # ── Paths ──

    @property
    def learnings_archive(self) -> Path:
        return self._base / "learnings.jsonl"

    @property
    def social_learnings_archive(self) -> Path:
        return self._base / "social_learnings.jsonl"

    @property
    def active_learnings_path(self) -> Path:
        return self._base / "active_learnings.md"

    @property
    def active_social_learnings_path(self) -> Path:
        return self._base / "active_social_learnings.md"

    # ── Atomic write helper ──

    @staticmethod
    def _atomic_write(path: Path, content: str) -> None:
        """Write content atomically using temp file + rename."""
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
        try:
            os.write(fd, content.encode("utf-8"))
            os.close(fd)
            os.replace(tmp, str(path))
        except Exception:
            os.close(fd) if not os.get_inheritable(fd) else None
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise

    # ── Append operations ──

    def append_learning(self, lesson: Lesson) -> None:
        """Append a learning to the archive."""
        if not lesson.timestamp:
            lesson.timestamp = datetime.now(timezone.utc).isoformat()
        record = {
            "type": lesson.type,
            "day": lesson.day,
            "ts": lesson.timestamp,
            "source": lesson.source,
            "title": lesson.title,
            "context": lesson.context,
            "takeaway": lesson.takeaway,
        }
        self._append_jsonl(self.learnings_archive, record)
        logger.info("Memory: appended learning '{}'", lesson.title[:60])

    def append_social_learning(self, insight: SocialInsight) -> None:
        """Append a social learning to the archive."""
        if not insight.timestamp:
            insight.timestamp = datetime.now(timezone.utc).isoformat()
        record = {
            "type": insight.type,
            "day": insight.day,
            "ts": insight.timestamp,
            "source": insight.source,
            "who": insight.who,
            "insight": insight.insight,
        }
        self._append_jsonl(self.social_learnings_archive, record)
        logger.info("Memory: appended social insight from '{}'", insight.who)

    def _append_jsonl(self, path: Path, record: dict) -> None:
        """Append a JSON record as a line to a JSONL file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record, ensure_ascii=False) + "\n"
        with open(path, "a", encoding="utf-8") as f:
            f.write(line)

    # ── Read operations ──

    def load_archive(self, path: Path) -> list[dict]:
        """Load all records from a JSONL archive."""
        if not path.exists():
            return []
        records = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                logger.warning("Memory: skipping malformed line in {}", path.name)
        return records

    def load_active_learnings(self) -> str:
        """Load the active learnings markdown."""
        if self.active_learnings_path.exists():
            return self.active_learnings_path.read_text(encoding="utf-8")
        return ""

    def load_active_social_learnings(self) -> str:
        """Load the active social learnings markdown."""
        if self.active_social_learnings_path.exists():
            return self.active_social_learnings_path.read_text(encoding="utf-8")
        return ""

    def get_archive_stats(self) -> dict:
        """Get statistics about the archive files."""
        learnings = self.load_archive(self.learnings_archive)
        social = self.load_archive(self.social_learnings_archive)
        return {
            "learnings_count": len(learnings),
            "social_learnings_count": len(social),
            "active_learnings_exists": self.active_learnings_path.exists(),
            "active_social_learnings_exists": self.active_social_learnings_path.exists(),
        }

    # ── Synthesis ──

    def synthesize(self) -> None:
        """Synthesize archive files into active context using time-weighted compression.

        Strategy:
          - Last 2 weeks: full markdown entries
          - 2-8 weeks ago: compressed to 1-2 sentences
          - 8+ weeks ago: grouped by topic into summaries
        """
        self._synthesize_learnings()
        self._synthesize_social_learnings()
        logger.info("Memory: synthesis complete")

    def _synthesize_learnings(self) -> None:
        """Synthesize learnings archive into active_learnings.md."""
        records = self.load_archive(self.learnings_archive)
        if not records:
            self._atomic_write(self.active_learnings_path, "# Active Learnings\n\nNo learnings yet.\n")
            return

        now = time.time()
        two_weeks_ago = now - 14 * 86400
        eight_weeks_ago = now - 56 * 86400

        recent = []
        mid = []
        old = []

        for r in records:
            ts = self._parse_timestamp(r.get("ts", ""))
            if ts >= two_weeks_ago:
                recent.append(r)
            elif ts >= eight_weeks_ago:
                mid.append(r)
            else:
                old.append(r)

        lines = ["# Active Learnings\n"]

        if recent:
            lines.append("## Recent (last 2 weeks)\n")
            for r in recent:
                lines.append(f"### {r.get('title', 'Untitled')}")
                lines.append(f"*Session {r.get('day', '?')} — {r.get('source', 'unknown')}*\n")
                if r.get("context"):
                    lines.append(f"{r['context']}\n")
                lines.append(f"**Takeaway:** {r.get('takeaway', '')}\n")

        if mid:
            lines.append("## Earlier (2-8 weeks ago)\n")
            for r in mid:
                title = r.get("title", "Untitled")
                takeaway = r.get("takeaway", "")
                lines.append(f"- **{title}**: {takeaway}")
            lines.append("")

        if old:
            lines.append("## Archive (8+ weeks ago)\n")
            # Group by source
            by_source: dict[str, list[str]] = {}
            for r in old:
                src = r.get("source", "unknown")
                takeaway = r.get("takeaway", r.get("title", ""))
                by_source.setdefault(src, []).append(takeaway)
            for src, items in by_source.items():
                lines.append(f"### {src}")
                for item in items[-5:]:  # Keep last 5 per source
                    lines.append(f"- {item}")
                if len(items) > 5:
                    lines.append(f"- *(+{len(items) - 5} more)*")
                lines.append("")

        self._atomic_write(self.active_learnings_path, "\n".join(lines))
        logger.info("Memory: synthesized {} learnings ({} recent, {} mid, {} old)",
                     len(records), len(recent), len(mid), len(old))

    def _synthesize_social_learnings(self) -> None:
        """Synthesize social learnings archive into active_social_learnings.md."""
        records = self.load_archive(self.social_learnings_archive)
        if not records:
            self._atomic_write(self.active_social_learnings_path, "# Social Learnings\n\nNo social learnings yet.\n")
            return

        now = time.time()
        two_weeks_ago = now - 14 * 86400

        recent = []
        older = []

        for r in records:
            ts = self._parse_timestamp(r.get("ts", ""))
            if ts >= two_weeks_ago:
                recent.append(r)
            else:
                older.append(r)

        lines = ["# Social Learnings\n"]

        if recent:
            lines.append("## Recent\n")
            for r in recent:
                who = r.get("who", "unknown")
                insight = r.get("insight", "")
                source = r.get("source", "")
                lines.append(f"- **{who}** ({source}): {insight}")
            lines.append("")

        if older:
            lines.append("## Earlier\n")
            for r in older[-10:]:  # Keep last 10
                who = r.get("who", "unknown")
                insight = r.get("insight", "")
                lines.append(f"- **{who}**: {insight}")
            if len(older) > 10:
                lines.append(f"- *(+{len(older) - 10} more)*")
            lines.append("")

        self._atomic_write(self.active_social_learnings_path, "\n".join(lines))

    @staticmethod
    def _parse_timestamp(ts: str) -> float:
        """Parse an ISO timestamp to epoch seconds."""
        if not ts:
            return 0.0
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            return dt.timestamp()
        except (ValueError, TypeError):
            return 0.0
