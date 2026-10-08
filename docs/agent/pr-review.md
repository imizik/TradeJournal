# Independent PR review

The owner finishes implementation and required deterministic checks, commits,
then calls the other provider's CLI on a fresh read-only snapshot. Findings
return directly to the active owning session. The owner fixes valid findings,
verifies and commits, then repeats. The user merges. No runner command merges,
enables auto-merge or changes production.

## Normal automatic workflow

Read [CLAUDE.md](../../CLAUDE.md) and the task's requirements. On a feature
branch, register ownership early so interruption does not lose the assignment:

```bash
python3 scripts/pr_review.py begin --owner codex --session SESSION_ID --contract docs/path-to-contract.md
```

For Claude ownership use `--owner claude`. SessionStart hook feedback supplies
the actual session id; Codex CLI also supplies `CODEX_THREAD_ID`. Use the exact
id, never `--last` or a guessed id. The contract points to agreed requirements,
not an author's narrative. Record requirements in existing task documentation
when they are not already in the repository.

After verification, commit the finished changes, then:

```bash
python3 scripts/pr_review.py review --owner codex --session SESSION_ID
```

Codex ownership selects Claude Opus; Claude ownership selects GPT-6.1 Sol.
Only the reviewer reads the disposable snapshot; it has no journal database,
ignored environment files, broad MCP adapter, inherited conversation or write
tools. The runner supplies the full diff and both head/ancestor source trees.
Configuration files stay available as evidence inside those trees but are not
the client's working-root settings. Claude's tools are Read/Grep/Glob only;
Codex uses a read-only sandbox. The reviewer must mark unavailable essential
evidence incomplete. It never executes tests, fixes, or another review loop.

Read the returned findings and saved result. Fix verified problems; challenge
incorrect findings with code/test evidence so the independent reviewer can
reassess them. Do not silently discard findings. Run relevant checks, commit,
and invoke the same command again. Each pass inspects the complete current diff
and verifies previous fixes. There are at most three passes total, with a
ten-minute process deadline per pass. Failures consume a pass too.

After a clean result, push the feature branch and open/update its draft PR.
Then publish and finish:

```bash
python3 scripts/pr_review.py publish --owner codex --session SESSION_ID --pr PR_NUMBER
python3 scripts/pr_review.py finish --owner codex --session SESSION_ID --pr PR_NUMBER
```

`finish` waits up to twenty minutes for all reported CI checks and requires
Backend, Frontend, Browser, Postgres parity and Ubuntu package/systemd jobs to
be present. It permits deliberate skipped checks. A failure, cancellation or
missing check cannot produce readiness. It rechecks the PR identity, marks a
draft ready, and reports its URL. CI repairs that change code require re-review.
The owner attaches any PR it creates using its client's artifact tool.

A draft PR can exist earlier for visibility: publish its pending status, then
pass `--pr PR_NUMBER` to review. Once bound, later review passes publish their
progress/results automatically. Push each new reviewed head before reviewing
against the bound PR, because publication refuses a mismatched remote head.
For a local review before push, leave the PR unbound until publication.

## Completion hooks and state

[Codex hooks](../../.codex/hooks.json) and
[Claude settings](../../.claude/settings.json) install SessionStart and Stop
handlers. SessionStart saves a baseline. Stop enrolls work changed during that
session and returns pending work to its owner, using provider-native hook
feedback. Read-only sessions with no changed work are left alone. Explicit
`begin` also enrolls an existing unfinished branch.

The hooks only inspect state and direct the owner to commands; they do not
make model calls inside a ten-second hook timeout. The reviewer disables hooks
and carries a reviewer-role marker to prevent recursion. Three identical
no-progress continuations become an attention outcome. Terminal failures get
one final continuation to report the blocker, then allow the session to end.

Ignored `.review-loop/` contains atomic state, owner/session identity, per-pass
results and diagnostic logs. A worktree lock prevents simultaneous runner
operations. Another session cannot silently take over this branch. Receipts
include the exact committed head, current base and diff ancestor; dirty work,
new commits or a changed base invalidate clean/ready results. Refresh
`origin/main` before review and reconcile it when the remote base changes.

Use `status` to inspect state. After the user explicitly authorizes recovery,
`retry` can recover an error with remaining budget; it never resets passes.
For a replacement session, `takeover --previous-session OLD --session NEW`
preserves all passes and findings and requires the previous owner/provider.
It requires human authorization. Exhaustion or a correctness disagreement is
reported to the user, never automatically reset. A dead reviewer process is
an error, not a clean pass.

## Subscription setup and activation

Both CLIs must be on PATH. Run `claude auth login --claudeai` and `codex login`
using the existing subscription accounts. The runner checks subscription auth
before inference and removes API-key, alternate-provider, GitHub-token and
inherited OAuth-token environment variables from reviewer processes. It does
not use `--bare`, which skips Claude subscription login, or fall back to API
billing. Usage consumes normal subscription allowances. Account-configured
extra usage/credits remain subject to the user's provider settings; the runner
cannot promise an allowance size or purchase credits.

Codex requires explicit trust for new/changed hooks: open `/hooks`, review and
trust the repository definitions. Restart local Codex/Claude sessions after
adoption so SessionStart and configuration loading occur. Existing sessions
must use the commands explicitly until restarted. Check the actual clients;
cloud-owned sessions are outside this local hook workflow.

Create the `review-loop` label once in GitHub. The runner adds it to enrolled
PRs. Publication uses the owner's normal `gh` authentication. Model credentials
never go to GitHub. No admin rights or background service on macOS are needed.

## GitHub gate and watchdog

[The gate script](../../scripts/review_gate.cjs) runs from trusted main through
[its workflow](../../.github/workflows/review-gate.yml), without checking out
or executing PR code. It validates the latest `tradejournal/review-receipt`
from the repository owner's login, the exact head/base, provider identity and
bounded pass count. It publishes `tradejournal/independent-review`.
Malformed, untrusted, missing or stale receipts never pass. A clean receipt is
an operational attestation, not cryptographic proof against a malicious owner.

PR events, receipt status updates and main pushes reevaluate the gate. A
fifteen-minute scheduled watchdog flags receipts pending/stale for over
forty-five minutes. Managed PRs receive one failure comment per head from
GitHub Actions. Schedules may be delayed by GitHub. The watchdog runs only
after the workflow lands on main, including manual dispatch. Before adoption,
exercise the script against API stand-ins and a live PR from the local runner.
A sleeping Mac cannot continue a local agent;
the gate stays incomplete and recovery resumes the owner after it returns.

Make the review status plus Backend, Frontend, Browser, Postgres parity and
Ubuntu package/systemd checks required on main, with up-to-date branches.
This turns missing review/CI into a merge block. The repository owner may
override protection intentionally; the agents must never do so or merge.
Protection is a GitHub setting, not something a workflow file enables by itself.

## Verification boundaries

`backend/tests/test_pr_review.py` plants failures in real temporary repositories
and fake CLI processes: absent/incorrect auth, incomplete results, denied tools,
stale/during-review changes, owner conflicts, process deadlines, budget caps and
early completion. `backend/tests/test_review_gate.py` exercises the GitHub gate
against stand-ins, including stale bases, missing receipts, pagination and
watchdog notification deduplication. These checks spend no model allowance.

Live subscription calls, actual client hook continuation, GitHub publication,
watchdog dispatch and protection settings are additional observations. Report
which were actually tested during rollout; fixture tests cannot prove them.
