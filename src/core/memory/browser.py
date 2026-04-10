# -*- coding: utf-8 -*-
"""Memory browser with filesystem tree and relationship graph.

MC-014: Browse memory files and infer relations between notes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class MemoryNode:
    name: str
    path: str
    is_dir: bool
    size: int = 0
    children: List["MemoryNode"] = field(default_factory=list)


@dataclass
class MemoryEdge:
    source: str
    target: str
    relation: str = "references"


@dataclass
class MemoryGraph:
    nodes: List[MemoryNode] = field(default_factory=list)
    edges: List[MemoryEdge] = field(default_factory=list)


class MemoryBrowser:
    """Memory filesystem browser and relation graph builder."""

    LINK_PATTERNS = [
        re.compile(r"\[\[([^\]]+)\]\]"),                # wiki links
        re.compile(r"\[[^\]]+\]\(([^)]+)\)"),          # markdown links
    ]

    def __init__(self, root: str):
        self.root = Path(root).resolve()

    def get_tree(self, max_depth: int = 4) -> MemoryNode:
        """Return hierarchical memory tree."""
        return self._build_tree(self.root, current_depth=0, max_depth=max_depth)

    def _build_tree(self, path: Path, current_depth: int, max_depth: int) -> MemoryNode:
        if not path.exists():
            return MemoryNode(name=path.name, path=str(path), is_dir=path.is_dir())

        node = MemoryNode(
            name=path.name or str(path),
            path=str(path),
            is_dir=path.is_dir(),
            size=path.stat().st_size if path.is_file() else 0,
        )

        if not path.is_dir() or current_depth >= max_depth:
            return node

        try:
            entries = sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        except OSError:
            return node

        for child in entries:
            if child.name.startswith("."):
                continue
            node.children.append(self._build_tree(child, current_depth + 1, max_depth))
        return node

    def build_graph(self, glob_pattern: str = "**/*.md") -> MemoryGraph:
        """Build graph from markdown note links."""
        files = [p for p in self.root.glob(glob_pattern) if p.is_file()]

        node_map: Dict[str, MemoryNode] = {}
        for f in files:
            rel = str(f.relative_to(self.root))
            node_map[rel] = MemoryNode(
                name=f.name,
                path=rel,
                is_dir=False,
                size=f.stat().st_size,
            )

        edges: List[MemoryEdge] = []
        for f in files:
            source = str(f.relative_to(self.root))
            try:
                content = f.read_text(encoding="utf-8")
            except Exception:
                continue

            refs = self._extract_links(content)
            for ref in refs:
                target = self._normalize_target(source, ref)
                if target and target in node_map:
                    edges.append(MemoryEdge(source=source, target=target, relation="references"))

        return MemoryGraph(nodes=list(node_map.values()), edges=edges)

    def _extract_links(self, content: str) -> List[str]:
        refs: List[str] = []
        for pattern in self.LINK_PATTERNS:
            refs.extend(pattern.findall(content or ""))
        return refs

    def _normalize_target(self, source: str, raw_target: str) -> Optional[str]:
        t = (raw_target or "").strip()
        if not t:
            return None

        # Strip anchors/query
        t = t.split("#", 1)[0].split("?", 1)[0].strip()
        if not t:
            return None

        if t.endswith(".md"):
            target = (Path(source).parent / t).resolve()
            try:
                return str(target.relative_to(self.root))
            except Exception:
                return None

        # wiki style [[note-name]] => try note-name.md in same dir
        target = (Path(self.root) / Path(source).parent / f"{t}.md").resolve()
        try:
            return str(target.relative_to(self.root))
        except Exception:
            return None
