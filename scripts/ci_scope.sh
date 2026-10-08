#!/usr/bin/env bash
# ci_scope.sh - classify a pull request's changed paths for CI and Deployment
# package, so both workflows skip their disposable environments on exactly the
# same documentation-only diffs.
#
#   scripts/ci_scope.sh [<base> <head>]
#
# With no arguments it compares the two parents of the merge commit GitHub
# checks out for a pull request: the base branch as it is now, and the merge
# result. That is the pull request's own change, however far main has moved
# since the branch was cut. Rename detection is off, so moving runtime code
# into docs/ still counts the runtime side. A failed diff fails the script.
#
# Prints, for $GITHUB_OUTPUT:
#   runtime=true|false   false only when every path is in the documentation
#                        allowlist below
#   frontend=true|false  whether anything under frontend/ changed
set -euo pipefail

files=$(git diff --no-renames --name-only "${1:-HEAD^1}" "${2:-HEAD}" --)

runtime=false
frontend=false
while IFS= read -r file; do
  case "$file" in
    # A case pattern's * also matches "/", so docs/*.md covers every folder
    # under docs/.
    "" | docs/*.md | README.md | AGENTS.md | CLAUDE.md | .github/pull_request_template.md) ;;
    *) runtime=true ;;
  esac
  case "$file" in
    frontend/*) frontend=true ;;
  esac
done <<< "$files"

echo "runtime=$runtime"
echo "frontend=$frontend"
