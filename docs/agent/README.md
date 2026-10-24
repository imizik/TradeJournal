# Agent documentation

Durable, shared context for anyone — human or agent — working in this
repository. This is an on-demand lookup, not a required reading list.
`CLAUDE.md` is the working agreement for every coding agent and
points here rather than restating this; `AGENTS.md` points at `CLAUDE.md`.

**Current selection:** [Dots functionality first](../product-roadmap.md#selected-priorities--october-11-2026).
The [Dots delivery board](dots-integration.md#current-delivery-board) owns what
is built, activated, observed and accepted, and the next-work sequence. Check it
before starting another roadmap slice.

## Core reference

| Document | Read it when |
|---|---|
| [architecture.md](architecture.md) | You need the shape of the system: processes, data flow, persistence, cost constraints |
| [domain-rules.md](domain-rules.md) | Before touching PnL, FIFO, fill import, enrichment, Strategy Lab, TradingView alerts, or the strategy factory |
| [environments.md](environments.md) | You need to know which database you are on, or are about to run something destructive |
| [feature-map.md](feature-map.md) | You know the feature but not the file |
| [background-jobs.md](background-jobs.md) | You are touching queued work: the worker lanes, job ownership, or restart recovery |
| [verification.md](verification.md) | Focused-check selection and on-demand coverage reference |
| [pr-review.md](pr-review.md) | Risk classification: ordinary work needs no reviewer; broad/consequential review and CI readiness |
| [codex-workflow.md](codex-workflow.md) | Optional bounded delegation in Codex; direct work with the selected model is the default |
| [delegation.md](delegation.md) | Optional bounded delegation in Claude Code to the `engineer` worker |
| [roadmap.md](roadmap.md) | You want to know where the foundation stands, what it still lacks, and what is deliberately not being built |

## Current Dots work

Rows on the delivery board with open gates. Each contract owns its scope,
permissions and acceptance.

| Document | Read it when |
|---|---|
| [dots-integration.md](dots-integration.md) | Current Dots delivery status and functionality priorities; role separation and shadow-runner boundaries |
| [shadow-s1-contract.md](shadow-s1-contract.md) | Shadow Isaac S1: Jo takes or skips scanner setups for its own paper book; tools, visibility cutoff, labels, acceptance and the 50-trade review |
| [setup-scanner-contract.md](setup-scanner-contract.md) | Setup scanner S1: universe, VWAP-fade and opening-range rules, contract choice, rules-only paper baseline, daily health notes, stock awareness and conditional price-plan follow-through |
| [shadow-trader-design.md](shadow-trader-design.md) | The informed shadow trader and setup co-pilot direction that S1–S4 build toward |
| [shadow-build-plan.md](shadow-build-plan.md) | Frozen setup/decision file formats, check-service upgrade and rollback sequence, and the remaining SC/S2–S4 packages |
| [market-watch-design.md](market-watch-design.md) | MW-1 and its scheduled reads; MW-2 event wakes and push (off by default, needs separate approval) |
| [advisor-pretrade-check-contract.md](advisor-pretrade-check-contract.md) | Jo's live pre-trade check service: approved data, tools, isolation, build status and its next-steps table |
| [advisor-forecast-preparation.md](advisor-forecast-preparation.md) | The isolated prospective forecast study: frozen rules, separate connection and the development-session limit |
| [dot-historical-replay-contract.md](dot-historical-replay-contract.md) | Weekend historical replay with original source times, a simulated cutoff, sealed continuation and isolated own paper outcomes |

## Built slices: reference for code and services that still exist

These slices are accepted, closed by the owner, dormant, or waiting only on a
separately stated gate (R4 human usefulness, the prospective MU collection,
A3's timed sessions). Their code, and in several cases an installed service,
remain, so the contract is still the authority on that code's permissions and
isolation. They are not new Dots work; each contract states its own open gate.

| Document | Read it when |
|---|---|
| [cloud-mcp-integration-scope.md](cloud-mcp-integration-scope.md) | Dots cloud connector scope: direct HTTPS with ChatGPT plan usage, OAuth identity, selected reads, UI/tool routing and the D0–D3 slices |
| [cloud-mcp-d0-runbook.md](cloud-mcp-d0-runbook.md) | D0 direct HTTPS/OAuth probe, offline public keys, no model/API spending path and manual trial setup |
| [cloud-mcp-d1-contract.md](cloud-mcp-d1-contract.md) | Two assigned sample Practice reads, backend OAuth checks, Unix bridge and manual activation/rollback |
| [cloud-mcp-d2-contract.md](cloud-mcp-d2-contract.md) | Opt-in own sample choice writes and receipt recovery, separate OAuth permission and demo acceptance |
| [cloud-mcp-historical-contract.md](cloud-mcp-historical-contract.md) | Assigned historical MU/NBIS demo choices on the existing connector |
| [cloud-mcp-journal-contract.md](cloud-mcp-journal-contract.md) | Journal coaching through a bounded approved export, exact statistics, offline OAuth and recorded continuous-access acceptance |
| [cloud-browser-auth-contract.md](cloud-browser-auth-contract.md) | Browser authentication and permissions: owner Tailscale continuity, restricted assistant login, the isolated HTTPS sample trial and live exposure gates |
| [dot-decision-trial-contract.md](dot-decision-trial-contract.md) | First saved Dot decision: scoped sample writer, frozen MU/NBIS evidence and acceptance boundaries |
| [dot-sample-replay-contract.md](dot-sample-replay-contract.md) | Jo's own bounded sample TAKE replay: hidden continuation, scoped start permission and isolated event ledger |
| [dot-market-decision-contract.md](dot-market-decision-contract.md) | Real MU/NBIS evidence handoff, isolated own-decision login, and manual native/browser acceptance |
| [cloud-mcp-advisor-contract.md](cloud-mcp-advisor-contract.md) | Advisor OAuth catalog, singleton Unix backend binding and immutable cited receipt |
| [advisor-assignment-contract.md](advisor-assignment-contract.md) | Repeatable invented advisor questions: owner create/assign/revoke/reopen |
| [advisor-connection-upkeep-contract.md](advisor-connection-upkeep-contract.md) | Advisor key upkeep and owner connection status |
| [advisor-shadow-contract.md](advisor-shadow-contract.md) | Manual invented advisor/shadow session, atomic A3 assignment, disclosure/provenance and separate cloud/forward gates |
| [a3-implementation-contract.md](a3-implementation-contract.md) | A3 daily preparation, independent choices and review acceptance (not fully accepted) |
| [practice-policy.md](practice-policy.md) | The P0 Shadow Isaac practice policy that `app/engine/paper.py` enforces: universe, schedule, costs and the worked example |
| [research-studio-r0.md](research-studio-r0.md) | R0 cache audit, feasibility evidence and the original bounded R1 contract |
| [research-studio-r1.md](research-studio-r1.md) | Discovery source, stop-free event observations, quality masks, CLI preview and frozen R2 parameters |
| [research-studio-r2.md](research-studio-r2.md) | Reproducible analysis, research-only SQLite/artifacts, manual child worker, cancellation/retry and exposure evidence |
| [research-studio-r3.md](research-studio-r3.md) | Owner app workspace, manually connected local research sidecar, linked views and immutable chart inspections |
| [research-studio-r4.md](research-studio-r4.md) | Frozen-parent variants, paired comparisons, append-only conclusions and pending human usefulness acceptance |
| [research-studio-comparison.md](research-studio-comparison.md) | Revealed event endpoints, concentration checks and compatible saved-period comparisons |
| [research-studio-newer-mu.md](research-studio-newer-mu.md) | The fixed MU comparison through October 2026, source approval and protected-period exposure |
| [research-studio-prospective-mu.md](research-studio-prospective-mu.md) | The frozen October 2026–April 2027 MU study, bounded collection and separate operator activation |

## Product plans

| Document | Read it when |
|---|---|
| [../workflow-consolidation-roadmap.md](../workflow-consolidation-roadmap.md) | October 21 owner workflow: post-VWAP Dashboard simplification, Radar peer context in Charts, Macro implementation and optional position/review work; merged Dashboard/VWAP, later releases remain planning |
| [../product-roadmap.md](../product-roadmap.md) | You need the current Dots-first cross-roadmap priorities or the future journal learning workflow |
| [../agentic-trading-roadmap.md](../agentic-trading-roadmap.md) | You want the proposed frozen-decision, alert and paper-review loop, grounded factory/thesis design and 30-day evidence goals; planning only |
| [../radar.md](../radar.md) | You are working on Radar: the five-PR sequence, the quote recorder and its activation boundary |
| [../copilot-lab.md](../copilot-lab.md) | You are working on the owner-only Claude Copilot Lab (off unless `COPILOT_ENABLED=true`): read-only tools, limits, settings, saved investigations, the manual research job and the live-API prerequisites |
| [../charts-roadmap.md](../charts-roadmap.md) | You are working on `/charts`: execution order, dependencies, acceptance gate, provider evidence and the not-building list |
| [../charts-deep-history.md](../charts-deep-history.md) | You need C0.0's implemented SIP cache, pagination, warmup, budget and test contract |

The repository is always the final source of truth. If a document disagrees
with the code, the code wins — and the document should be fixed in the same
change.
