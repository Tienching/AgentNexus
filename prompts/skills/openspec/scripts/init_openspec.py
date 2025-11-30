#!/usr/bin/env python3
"""
OpenSpec Project Initialization Script

This script initializes OpenSpec in a project by:
1. Creating the openspec/ directory structure
2. Copying template files (AGENTS.md, project.md)
"""

import os
import sys
import shutil
from pathlib import Path


def get_skill_dir():
    """Get the path to the openspec skill directory."""
    # Script is in ~/.claude/skills/openspec/scripts/
    script_path = Path(__file__).resolve()
    return script_path.parent.parent


def get_templates_dir():
    """Get the path to the templates directory."""
    return get_skill_dir() / "assets" / "templates"


def create_directory_structure(project_root):
    """Create the openspec directory structure."""
    openspec_dir = project_root / "openspec"

    # Create main directories
    openspec_dir.mkdir(exist_ok=True)
    (openspec_dir / "specs").mkdir(exist_ok=True)
    (openspec_dir / "changes").mkdir(exist_ok=True)
    (openspec_dir / "changes" / "archive").mkdir(exist_ok=True)

    print(f"✓ Created directory structure at {openspec_dir}")
    return openspec_dir


def copy_agents_md(openspec_dir):
    """Copy AGENTS.md template to project."""
    templates_dir = get_templates_dir()
    source = templates_dir / "AGENTS.md"
    dest = openspec_dir / "AGENTS.md"

    if dest.exists():
        print(f"  Skipping AGENTS.md (already exists)")
        return

    shutil.copy2(source, dest)
    print(f"✓ Copied AGENTS.md")


def copy_project_md(openspec_dir):
    """Copy project.md template to project."""
    templates_dir = get_templates_dir()
    source = templates_dir / "project.md"
    dest = openspec_dir / "project.md"

    if dest.exists():
        print(f"  Skipping project.md (already exists)")
        return

    shutil.copy2(source, dest)
    print(f"✓ Copied project.md template")


def check_existing_openspec(project_root):
    """Check if openspec is already initialized."""
    openspec_dir = project_root / "openspec"
    agents_md = openspec_dir / "AGENTS.md"

    if openspec_dir.exists() and agents_md.exists():
        return True
    return False


def init_openspec(project_path):
    """Initialize OpenSpec in the given project."""
    project_root = Path(project_path).resolve()

    # Validate project path
    if not project_root.exists():
        print(f"Error: Project path does not exist: {project_root}", file=sys.stderr)
        return 1

    if not project_root.is_dir():
        print(f"Error: Project path is not a directory: {project_root}", file=sys.stderr)
        return 1

    # Check if already initialized
    if check_existing_openspec(project_root):
        print(f"OpenSpec is already initialized at {project_root}/openspec/")
        print(f"Skipping initialization to preserve existing configuration.")
        return 0

    print(f"Initializing OpenSpec in: {project_root}")
    print()

    # Create directory structure
    openspec_dir = create_directory_structure(project_root)

    # Copy template files
    copy_agents_md(openspec_dir)
    copy_project_md(openspec_dir)

    print()
    print("OpenSpec initialization complete!")
    print()
    print("Next steps:")
    print("1. Fill out openspec/project.md with your project details")
    print("2. Review openspec/AGENTS.md for workflow guidance")
    print("3. Create your first change proposal")

    return 0


def main():
    if len(sys.argv) != 2:
        print("Usage: init_openspec.py <project-root-path>", file=sys.stderr)
        print()
        print("Example:")
        print("  python init_openspec.py /path/to/my-project")
        return 1

    project_path = sys.argv[1]
    return init_openspec(project_path)


if __name__ == "__main__":
    sys.exit(main())
