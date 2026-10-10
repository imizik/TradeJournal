# Prompt for the new Sol chat

Paste the following into a new TradeJournal chat with Sol selected as the lead.
The full acceptance contract is `docs/agent/a3-implementation-contract.md`.
These handoff and A2 acceptance documents are currently local, unpushed files
in `/Users/user/.codex/worktrees/4025/TradeJournal`; a new worktree will not
inherit them automatically.

```text
Implement A3 for TradeJournal: the short daily preparation → frozen choices
→ after-work practice review loop. Use Sol as the accountable orchestrator;
delegate bounded work to Luna only when it helps, following the repository's
Codex workflow. Do not assume the chat's model changed automatically.

Read CLAUDE.md first. Then read docs/agent/codex-workflow.md,
docs/agent/a3-implementation-contract.md, the A3 section and morning pipeline
in docs/agentic-trading-roadmap.md, docs/agent/practice-policy.md,
docs/agent/dots-integration.md, and applicable domain, environment, job and
verification guidance. Inspect current owning code before settling design.

The scoped contract and A2 acceptance evidence are unpushed local documents
in /Users/user/.codex/worktrees/4025/TradeJournal. If your checkout lacks them,
read and carry only those documentation changes into your owned branch:
docs/agent/a3-implementation-contract.md, docs/agent/a3-sol-handoff.md,
docs/agent/practice-policy.md, docs/agent/feature-map.md, and
docs/agentic-trading-roadmap.md. Preserve existing work; do not reset or delete
that checkout. Base implementation on current main in a codex/ branch.

Starting evidence: PR #152 merged and deployed as d00257286dd0 on 2026-10-08.
A late-session SPY operational test completed human-confirmed phone receipt
and exact-card opening, accepted paper entry, API restart while open with
unchanged events, and one fixed-stop exit. Independent base/3× cost and
frozen-risk R checks passed. The follow-up was paused. This proves the core
A2 live mechanism, not an on-time strategy cohort or profitable policy. A1
human comprehension timing remains unobserved. Verify current state without
unnecessarily repeating the completed live test.

Scope A3 only. Build the durable daily-run/opportunity model and manual-first
Today/review workflow first, then independent choice/reveal, one replaceable
bounded agent adapter, and opt-in 08:50 America/New_York scheduling using the
existing JobRun/systemd patterns. Reuse A1 validation and A2 paper events;
keep arming explicit. No Dots is required. Paid calls and scheduling ship
disabled until I approve the exact runtime/model, daily limits and enablement.

Before delegation, Sol settles canonical run/retry/revision semantics,
calendar/deadline handling, the frozen common-opportunity/outcome benchmark,
runner identity/access isolation, and budget/failure behavior. Do not invent
unspecified consequential rules in a worker brief. The independent runner
must not receive human decisions, journal activity, broad journal MCP, or
raw HTTP/shell access; UI hiding or a prompt is not sufficient isolation.
Use service/payload negative tests. Failure of preparation/model calls must
not stop existing paper monitoring.

Use the contract's AC1–AC10 as the acceptance checklist: durable/idempotent
session status; desktop/phone valid capture; bounded, source-linked three-part
brief; honest no-setup/failure/late states and usage; enforced independence;
choice/reveal/nonresponse integrity; complete deterministic review; opt-in
calendar-aware scheduling and restart safety; required local/CI checks;
and three observed live sessions with real five-minute routine timings.
Manual runs cannot validate scheduling, assisted runs cannot validate blind
comparison, and fixtures cannot satisfy human/live gates.

Delegate only clear bounded outcomes, with one writer per shared subsystem,
self-contained briefs and explicit acceptance evidence. Sol retains schema,
security, timing/price/risk semantics, integration and final verification.
Do not delegate by default merely because the task is substantial.

Do not change P0 execution/costs/universe, auto-arm, add broker orders, connect
Dots, expose the private API, modify journal/FIFO/P&L, expand factory/Workbench,
or start another roadmap slice. Keep operational probes outside strategy
results and preserve missing/unobserved distinctions.

Progress autonomously through implementation and deterministic verification.
Run scripts/verify.sh --fast while working and the full suite before claiming
code readiness; obtain relevant Postgres and Ubuntu deployment CI evidence.
Ask before pushing, opening a PR, merging/deploying, paid calls or live schedule
enablement. Earlier A2 deployment approval does not authorize A3 deployment.
If approval or a runtime-budget choice blocks a dependent step, finish all
independent work first and present the concrete result for review.

Update owning docs and report briefly: changes, tests, code/deployment/live
acceptance status, unresolved gates and risks. Do not mark A3 fully accepted
until its required three-session evidence exists. Stop at A3.
```
