# Conflict Resolution Prompt

You are agent-nexus resolving a git merge conflict.

## Context

- Branch: {{branch_name}}
- Task: {{task_title}}
- Files changed: {{files_changed}}

## Conflicted files

{{conflicted_files}}

## Goal

Produce a clean merge that keeps the worktree improvement while preserving unrelated main-branch changes.

## Rules

- Remove all conflict markers.
- Prefer the incoming task-specific change when in doubt.
- Run tests after resolving.
- Stage with `git add {{git_add_files}}`.
- Commit with `{{commit_msg}}` only if the result is clean.
- Abort the merge if you cannot resolve it safely.
