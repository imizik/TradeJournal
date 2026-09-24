---
name: docs-drift
description: Find and fix documentation that no longer matches the code. Use after a run of merged PRs, at the end of a working session, or when a doc's claim looks suspicious. Checks the claims a link-checker cannot see - stale numbers, decisions still labelled open, commands whose flags changed, missing content.
---

# Documentation drift

`CLAUDE.md` says the repository is the source of truth: a document that
disagrees with the code gets fixed in the same change. That rule gets skipped,
because drift is invisible from inside the change that caused it. This is the
catch-up pass.

**The mechanical half is already a test.** `backend/tests/test_docs_links.py`
fails when a document names a file or a heading that no longer exists. Do not
re-do it by hand; run it and move on. What it cannot see is a sentence that is
still well-formed and no longer true, and that is everything below.

**What sends you here is usually the other test.**
`backend/tests/test_docs_freshness.py` fails when more than 30 code commits
have landed since `docs/agent/last-reconciled.json`, and its failure message
carries the commit range to reconcile. Use that range as `<since>` below; if
you arrived some other way, the marker file still says where to start.

## The method

### 1. Find what changed

Drift follows merges, so start from them rather than from the docs.

```bash
git log --oneline <since>..HEAD          # the range since docs were last reconciled
git diff --stat <since>..HEAD            # which subsystems moved
```

Read the commit messages. They say what the author believed they were
changing, which is the fastest index into what a document might now
misdescribe.

### 2. Sweep for the shapes drift takes

These recur. Grep for them across `docs/`, `README.md`, `AGENTS.md` and
`CLAUDE.md`:

- **Numbers quoted from code.** Rates, limits, timeouts, test counts, job
  counts, port numbers. A constant moves and the prose keeps the old value.
  (`13.4s at the free-tier default` survived the change that deleted the fixed
  rate it described.)
- **Status words.** "Open decision", "still needed", "not yet", "TODO",
  "planned", "done". A decision gets made in a commit and the planning
  document never hears about it.
- **Command descriptions.** Every `bash scripts/...` and `pytest ...` line in
  a doc: run it, or at least read the script, and check the comment beside it
  still lists what it does. Added checks are the usual miss.
- **Counts of things the reader can recount.** "two parallel jobs", "seven
  entries", "three processes". Count them.
- **Module and symbol names** in prose, where a rename would not break a link.

### 3. Read the code behind each claim, not the previous text

This is the whole job. For every suspect sentence, open the file it describes
and decide whether the sentence is still true. Rewriting prose from other
prose is how a wrong statement survives five editing passes.

When a number was load-bearing, replace it with a current one rather than
deleting it. `13.4s per call` was telling the reader what an extra API call
costs; the replacement says the same thing in the new units ("about eight
minutes across a 38-ticker week") instead of dropping the intuition.

### 4. Check what is missing, not only what is wrong

A document is also stale when something real happened and it says nothing.
Ask of each doc in `docs/agent/`: does the last set of merges belong in here?
New architectural rules belong in `architecture.md` and `domain-rules.md`; new
checks in `verification.md`; completed or invalidated plans in `roadmap.md`;
new test modules in `feature-map.md`'s Proof column.

### 5. Verify and report

```bash
bash scripts/verify.sh --fast
```

Then record what you reconciled to, which is what clears the freshness test:

```json
{"commit": "<the full 40-character sha you read up to>", "date": "<YYYY-MM-DD>", "note": "..."}
```

in `docs/agent/last-reconciled.json`. Write it after the pass, not before —
nothing detects a marker bumped on its own, so it is the one shortcut that
quietly disables the whole mechanism.

Then say plainly what you could not check. Prose accuracy is not machine
verifiable: the honest report is "each claim was re-read against the code it
describes", not "docs pass".

## What not to do

- Do not rewrite for tone, tighten wording, or reorganise sections. Drift
  fixes only. Formatting churn buries the real change and this repository's
  working agreement asks against it.
- Do not delete a claim you cannot verify. Check it, or leave it and say so.
- Do not add a document. Fix the ones that exist.
