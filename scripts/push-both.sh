#!/bin/bash
#
# push-both.sh - Push current branch to both origin and GitHub mirror
#
# Usage:
#   ./scripts/push-both.sh                # Push current branch
#   ./scripts/push-both.sh <branch>       # Push specified branch
#   ./scripts/push-both.sh --dry-run      # Validate without actual push
#   ./scripts/push-both.sh --with-tags    # Push branch + tags to both remotes
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"

DEFAULT_GITHUB_URL="git@github.com:Tienching/AgentNexus.git"
GITHUB_URL="${GITHUB_MIRROR_URL:-$DEFAULT_GITHUB_URL}"

DRY_RUN=false
WITH_TAGS=false
BRANCH=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --with-tags)
            WITH_TAGS=true
            shift
            ;;
        -h|--help)
            echo "Usage: $0 [--dry-run] [--with-tags] [branch]"
            echo "  --dry-run    Show what would be pushed"
            echo "  --with-tags  Also push tags to both remotes"
            exit 0
            ;;
        *)
            if [[ -z "$BRANCH" ]]; then
                BRANCH="$1"
                shift
            else
                echo "[ERROR] Unexpected argument: $1"
                exit 1
            fi
            ;;
    esac
done

if ! git -C "$REPO_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    echo "[ERROR] Not a git repository: $REPO_DIR"
    exit 1
fi

if [[ -z "$BRANCH" ]]; then
    BRANCH="$(git -C "$REPO_DIR" rev-parse --abbrev-ref HEAD)"
fi

if [[ "$BRANCH" == "HEAD" ]]; then
    echo "[ERROR] Detached HEAD. Please specify a branch explicitly."
    exit 1
fi

if ! git -C "$REPO_DIR" remote get-url origin >/dev/null 2>&1; then
    echo "[ERROR] Remote 'origin' not found."
    exit 1
fi

PUSH_ARGS=()
if [[ "$DRY_RUN" == true ]]; then
    PUSH_ARGS+=(--dry-run)
fi

echo "[INFO] Repository: $REPO_DIR"
echo "[INFO] Branch: $BRANCH"
echo "[INFO] Origin: $(git -C "$REPO_DIR" remote get-url origin)"
echo "[INFO] GitHub mirror: $GITHUB_URL"

# Push branch to origin
echo "[INFO] Pushing to origin..."
git -C "$REPO_DIR" push "${PUSH_ARGS[@]}" origin "$BRANCH"

# Push branch to GitHub mirror
echo "[INFO] Pushing to GitHub mirror..."
git -C "$REPO_DIR" push "${PUSH_ARGS[@]}" "$GITHUB_URL" "$BRANCH"

if [[ "$WITH_TAGS" == true ]]; then
    echo "[INFO] Pushing tags to origin..."
    git -C "$REPO_DIR" push "${PUSH_ARGS[@]}" origin --tags

    echo "[INFO] Pushing tags to GitHub mirror..."
    git -C "$REPO_DIR" push "${PUSH_ARGS[@]}" "$GITHUB_URL" --tags
fi

echo "[INFO] Done. Both remotes are in sync for branch '$BRANCH'."
