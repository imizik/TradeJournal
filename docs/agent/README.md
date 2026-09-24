# Agent documentation

Durable, shared context for anyone — human or agent — working in this
repository. `CLAUDE.md` is the working agreement for every coding agent and
points here rather than restating this; `AGENTS.md` points at `CLAUDE.md`.

| Document | Read it when |
|---|---|
| [architecture.md](architecture.md) | You need the shape of the system: processes, data flow, persistence, cost constraints |
| [domain-rules.md](domain-rules.md) | Before touching PnL, FIFO, fill import, enrichment, Strategy Lab, or TradingView alerts |
| [verification.md](verification.md) | Before claiming a change works — the commands, what they cover, and what they don't |
| [feature-map.md](feature-map.md) | You know the feature but not the file |
| [environments.md](environments.md) | You need to know which database you are on, or are about to run something destructive |
| [roadmap.md](roadmap.md) | You want to know where the foundation stands, what it still lacks, and what is deliberately not being built |

The repository is always the final source of truth. If a document disagrees
with the code, the code wins — and the document should be fixed in the same
change.
