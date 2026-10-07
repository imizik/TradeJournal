# Agent documentation

Durable, shared context for anyone — human or agent — working in this
repository. `CLAUDE.md` is the working agreement for every coding agent and
points here rather than restating this; `AGENTS.md` points at `CLAUDE.md`.

| Document | Read it when |
|---|---|
| [architecture.md](architecture.md) | You need the shape of the system: processes, data flow, persistence, cost constraints |
| [domain-rules.md](domain-rules.md) | Before touching PnL, FIFO, fill import, enrichment, Strategy Lab, TradingView alerts, or the strategy factory |
| [verification.md](verification.md) | Before claiming a change works — the commands, what they cover, and what they don't |
| [codex-workflow.md](codex-workflow.md) | How Sol leads substantial Codex work, delegates bounded tasks to Luna, and checks the result; when Luna can work directly |
| [feature-map.md](feature-map.md) | You know the feature but not the file |
| [delegation.md](delegation.md) | You are a Claude Code session on Opus deciding what to hand to a Sonnet worker, or you are that worker |
| [environments.md](environments.md) | You need to know which database you are on, or are about to run something destructive |
| [background-jobs.md](background-jobs.md) | You are touching queued work: the worker lanes, job ownership, or restart recovery |
| [../product-roadmap.md](../product-roadmap.md) | You want the future trading-improvement workflow and its usage gates, without changing active feature-roadmap priorities |
| [../agentic-trading-roadmap.md](../agentic-trading-roadmap.md) | You want the proposed frozen-decision, alert and paper-review loop, grounded factory/thesis design, first three slices and 30-day evidence goals; planning only |
| [../charts-roadmap.md](../charts-roadmap.md) | You are working on `/charts`: execution order, dependencies, acceptance gate, provider evidence and the not-building list |
| [../charts-deep-history.md](../charts-deep-history.md) | You need C0.0's implemented SIP cache, pagination, warmup, budget and test contract |
| [roadmap.md](roadmap.md) | You want to know where the foundation stands, what it still lacks, and what is deliberately not being built |

The repository is always the final source of truth. If a document disagrees
with the code, the code wins — and the document should be fixed in the same
change.
