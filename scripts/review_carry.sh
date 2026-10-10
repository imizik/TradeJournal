#!/usr/bin/env bash
# review_carry.sh - decide whether a clean review still covers a branch after
# the target branch was integrated into it (docs/agent/pr-review.md, step 6).
#
#   scripts/review_carry.sh <reviewed-base> <reviewed-head> [<base> <head>]
#
# <base> defaults to the remote-tracking origin/main and <head> to HEAD; pass
# the pushed PR head explicitly after a fetch. Each side's feature patch is the
# diff from merge-base(base, head) to head, so a merge of main into the branch
# drops out and only the branch's own change is compared. The patch uses full
# blob ids, so it is identical only when the feature's files had the same
# content before and after on both sides: if main touched any of those files,
# a merge resolution altered anything, or the branch gained a commit of its
# own, the patch differs. Whitespace counts. A head that does not contain
# <base> is refused: the carry is only for a branch that has caught up.
#
# Prints both patch hashes, whether <head> contains <base>, and the files main
# changed since the review, which the owner must still judge for what the
# feature and its checks rely on.
#
# Exit status: 0 identical, 1 changed or not integrated (re-review or merge
# and rerun), 2 usage or git error.
set -euo pipefail

if [[ $# -ne 2 && $# -ne 4 ]]; then
  echo "usage: $0 <reviewed-base> <reviewed-head> [<base> <head>]" >&2
  exit 2
fi

commit() {
  git rev-parse --verify --quiet "$1^{commit}" || { echo "not a commit: $1" >&2; exit 2; }
}

reviewed_base=$(commit "$1")
reviewed_head=$(commit "$2")
base=$(commit "${3:-refs/remotes/origin/main}")
head=$(commit "${4:-HEAD}")

# --no-relative and --ignore-submodules=none stop a user's diff.relative or
# diff.ignoreSubmodules setting from hiding paths on both sides at once.
diff_args=(--no-relative --no-renames --ignore-submodules=none --no-ext-diff --no-textconv)

patch_hash() {
  git diff "${diff_args[@]}" --binary --full-index "$1" "$2" -- | git hash-object --stdin
}

old_mb=$(git merge-base "$reviewed_base" "$reviewed_head") || { echo "no merge base for the reviewed pair" >&2; exit 2; }
new_mb=$(git merge-base "$base" "$head") || { echo "no merge base for the current pair" >&2; exit 2; }
old_patch=$(patch_hash "$old_mb" "$reviewed_head") || exit 2
new_patch=$(patch_hash "$new_mb" "$head") || exit 2

echo "reviewed: $old_mb..$reviewed_head patch $old_patch"
echo "current:  $new_mb..$head patch $new_patch"
if [[ "$new_mb" != "$base" ]]; then
  echo "head contains base: no"
  echo "result: not integrated (merge $base into the branch, push, and rerun against that head)"
  exit 1
fi
echo "head contains base: yes"

ancestor=0
git merge-base --is-ancestor "$old_mb" "$base" || ancestor=$?
if [[ $ancestor -eq 1 ]]; then
  echo "result: changed (the target branch was rewritten since the review)"
  exit 1
elif [[ $ancestor -ne 0 ]]; then
  exit 2
fi

incoming=$(git diff "${diff_args[@]}" --name-only "$old_mb" "$base" --) || exit 2
echo "incoming files since review: $(grep -c . <<< "$incoming" || true)"
if [[ -n "$incoming" ]]; then
  sed 's/^/  /' <<< "$incoming"
fi

if [[ "$old_patch" == "$new_patch" ]]; then
  echo "result: identical"
  exit 0
fi
echo "result: changed"
exit 1
