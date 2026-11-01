# TradeJournal AI intelligence and product architecture review

**Date:** 2026-10-31. **Scope:** every AI integration and AI-related workflow in the repository at `9572a919` (#628). **Nature:** research and assessment only. No application code was changed, nothing was deployed, no production service was read.

**How this review was made.** Six read-only audits of the code, tests, docs and git history (Copilot core; Jo/Dots/MCP/Shadow; reviews, monitors and feedback loops; Radar, research jobs and labs; data providers and AI reach; frontend experience), each cross-checked on its load-bearing claims. Production activation could not be verified directly: the read-only SSH check to the VPS was refused by this session's permission mode. Every statement about what is live therefore carries one of these labels:

- **VERIFIED** — read in code or tests in this worktree.
- **CLAIM** — a dated statement in the docs, a PR description or the owner's session notes; not checked against the host.
- **INFERENCE** — follows from the code but was not observed running.
- **HYPOTHESIS** — plausible, untested, needs an experiment.
- **RECOMMENDATION / EXPERIMENT** — what to do, and how to find out.

Supporting audit notes (file:line citations for everything below) are in the session scratchpad; the citations repeated here are the ones that carry the argument.

---

## A. Executive diagnosis

**The verdict in one paragraph.** TradeJournal has an unusually strong deterministic substrate and the right design instincts for its conversational AI, but it is accumulating disconnected AI features faster than it can measure any of them. Between October 20 and October 30, 253 merges landed, 108 of them touching the copilot, adding 53 environment flags. In the same period the only quality signals the product collects (Helped/Didn't on answers, alert feedback, Radar ratings) were either never aggregated by any code, or stood at zero. The one surface that should be the brain of the product, the Copilot, is the most data-starved AI in the app: the nightly Daily Review and the external Jo both see more market and journal context than it does. The direction stated in the end goal (copilot as the primary interface, deterministic monitoring, Jo as slow background research) is correct. The execution problem is consolidation and measurement, not missing features.

### What is being done well (VERIFIED unless noted)

1. **The journal is the moat, and it is built to be trusted.** Fills are authoritative; trades, path metrics (MFE/MAE, give-back, post-exit continuation), fill-time market context (VWAP distance, RVOL, chase/trend flags, trader-state sequence) and exit-habit scorecards are all deterministic, cached, and reconciled. The behaviour audit (`backend/reports/behavior_audit_2026-10-21.md`) and the invalidation study are exactly the kind of personal evidence no external tool can offer.
2. **The copilot's reasoning contract is sound.** The four-question frame (thesis, setup, instrument, decision now), verdict-first answers, a mandatory "Against" line, "Unsupported:" for claims no evidence backs, provenance labels on every tool result (`copilot_tools.py:899-906`), SIMULATED markers that survive truncation, and memories that only exist after the owner confirms a card. These are the right primitives.
3. **Safety and boundaries are real, not aspirational.** Read-only tools, browser-side confirmation for every write, no order path anywhere, injection-hardened system prompt, an offline adversarial suite (33 tests), research jobs with citation checks and hindsight detection under replay, and a frozen-clock replay mode (`copilot_replay.py`) that refuses to run off a local database.
4. **Monitoring is deterministic and recorded.** Position alerts, plan alerts, time stops, thesis watch, Radar and the ping policy all write rows with reasons; the outcomes engine (#623) records what followed each ping with explicit "counts, not causation" framing.
5. **Research hygiene when it is applied is excellent.** Pre-registered protocols, day-clustered bootstraps, both-halves replication, explicit refusal to claim edge. The counterfactual study rejected all three mechanical exits; the opening lab was stopped when it showed no edge.

### What is weak

1. **Nothing closes the loop.** Helped/Didn't is stored inside each investigation's transcript JSON and read by no backend code (`copilot_investigations.py:130`; `routers/copilot.py:317`). Alert feedback, Radar ratings and outcomes are display-only. The only "learning" is model-to-model: yesterday's `next_session_rules` are checked by tonight's review. No prompt, threshold, sender or tool selection is ever adjusted by evidence.
2. **The Copilot is withheld data the app already has.** Implied volatility and Greeks are parsed from the Tradier chain (`options_chain.py:139-145`) and deliberately replaced with "unavailable" before the model sees them (`copilot_options.py:84`), while the system prompt asserts they do not exist. No tool exposes VIX, rates, sector ETFs, the macro calendar, fundamentals, the Radar feed, the Proof, the outcomes, the alert scorecards, the setup record, or Jo's checks and plans. The Daily Review (`review_context.py`) sees most of these; the conversational AI sees none.
3. **Continuity is thin and partly in-memory.** Follow-up evidence lives in a process-local dict with a two-hour TTL, six items of 2,500 characters each (`copilot.py:1259-1320`), lost on reload, resume or restart. History is text-only, clipped at 23 messages, and never re-sends cards or whether they were confirmed. Telegram questions and "Why?" answers are not saved as threads at all (`telegram_replies.py:278-318`). Other threads are visible only as titles.
4. **The same job is done in several places.** Two Shadow-Isaacs (Jo S1 on scanner emails; the Copilot shadow book on Radar events). Three to four morning briefs (Jo 09:00, copilot 08:30, Practice "Morning brief", on-demand Prep the day; Duet would be a fifth). Four ways to capture a plan. Four unlinked "one rule to practise" systems (daily rules, weekly rule, practice goal, monthly commitment). Four to six "what followed an alert" calculators with two valuation bases (bid vs mid). Two per-trade reviews. Two memory-approval paths into one store. Two phone channels, because Jo's senders call ntfy directly and bypass the ping policy (`stock_watch.py:154`, `conditional_plans.py:89`, `market_watch_wakes.py:495`).
5. **The Jo/Dots estate is far larger than its evidence.** Seven MCP servers, 61 unique tools (34 on Check alone), roughly 18 auth principals or profiles, 22 contract documents (about 6,400 lines), and a delivery board with 18 rows of which 4 are accepted. No pre-trade grade, no market-read score, no S1 selection result and no morning rating is committed anywhere in the repository. S1 recorded 8 setups and 8 skips. The morning brief tally is "delivery 1/5". On October 29 the owner moved Jo off the time-critical path (`docs/agent/dots-integration.md:91-95`); `CLAUDE.md` still says "Dots functionality first".
6. **Off-goal research volume.** Strategy factory: about 85 judged candidates, 0 passes, paused October 16 (CLAIM) but still scheduled and undocumented as paused. Opening lab: four rounds, no edge, judged drift on October 29. Research Studio MU: every interval includes zero. Scanner S1: 0 of 17 rule exits. These consumed real build time and feed nothing the trader uses.
7. **Operational drift already costs money and signal.** The 08:30 brief and the Friday week review run model turns outside the daily spend cap and are never recorded (`premarket_prep.py:420-457`; no `copilot_spend` reference in either module). The `prep` ping budget of one is shared with the week review and Watch-your-day, so the Friday review is held whenever the morning brief went out, and a test enshrines it (`test_notification_policy.py:170-171`). On October 29 the shared ping pool was spent before 09:50 and Radar, one of the two things under proof, delivered nothing to the phone.

### Are we moving toward the product or accumulating features?

Both, and the second is winning on volume. The coherent core exists: desk + plan card + deterministic alerts + Radar + outcomes. Around it sit two generations of earlier experiments (Dots/advisor/shadow/practice/factory/studio) that were never retired, and a third generation (companion, interrupts, shadow book, Jo research role, Duet) added in the last ten days before the first two proofs produced a number. The end goal says "prove two things first, then connect the loop." The repository shows the loop being connected and extended while the proofs remain unmeasured and confounded (six interventions launched inside the same 30-trade Proof window).

---

## B. Current AI architecture map

### B.1 Where a model is actually called

| System | Model and path | Trigger | Flag (default) | Live state | Evidence of usefulness |
|---|---|---|---|---|---|
| **Copilot chat** (`app/ai/copilot.py`, `routers/copilot.py`) | Messages API, adaptive thinking, effort medium; or Agent SDK on the Claude plan (`copilot_plan.py`). 18 read-only tools, 4 rounds, 8 calls, 120 s, $0.25/turn, $2/day | owner message (desk, Charts dock, Radar drawer, Telegram) | `COPILOT_ENABLED` (off) | CLAIM on since 10-24; default backend `plan`, Opus 5.5 since 10-26 (owner notes) | none aggregated; ratings unread |
| Position companion (`position_companion.py`) | copilot backend, `COMPANION_MODEL` | unplanned long-option entry; updates on pings/Radar/3%/60 min/15:30 | `POSITION_COMPANION_ENABLED` (off) | #622 merged 10-30 | none |
| Telegram replies (`telegram_replies.py`) | copilot backend, single-message history | typed question or "Why?" | Telegram configured | #620 merged 10-29 | none; not saved |
| Pre-market prep (`premarket_prep.py`) | copilot backend, one turn, 10 lines | 08:30 NY | `PREMARKET_PREP_ENABLED` (off) | CLAIM on since 10-25 | none |
| Automatic week review (`week_review_auto.py`) | copilot backend; deterministic `get_week_review` | Fri 16:45 | `WEEK_REVIEW_AUTO_ENABLED` (off) | unknown | none |
| Research job + queue (`research_job.py`, `research_queue.py`) | Agent SDK, Sonnet 5.5 default, WebSearch/WebFetch + 7 lab tools, 24 turns/600 s/$0.50 | owner POST, "Research deeper", revisit, thesis watch, optional Radar/reassess triggers | `RESEARCH_QUEUE_ENABLED` (off) | CLAIM on since 10-24 ($0.40/job, $1/day) | 2 manual runs documented |
| Shadow book (`shadow_book.py`, `shadow_turn.py`) | Agent SDK on the plan only, 8 tools, no web | "strong" Radar or dip events, ≤12 turns/session | `SHADOW_BOOK_ENABLED` (off) | CLAIM on since 10-27; 12 turns spent by 10:05 on 10-29 | none; no success criterion |
| Daily / monthly / per-trade reviews (`daily_reviewer.py`, `monthly_reviewer.py`, `reviewer.py`, `plan_runner.py`) | `claude -p` on the plan, `sonnet` alias, JSON schema; or Messages API `claude-opus-4-7` when `AI_REVIEW_BACKEND=api` | button, or nightly timer 20:10 | timer opt-in | unknown | none |
| Practice agent A3 (`practice_agent.py`) | direct Messages API subprocess | 08:50 timer | `PRACTICE_SCHEDULE_ENABLED` (off) | CLAIM never enabled | none |
| Strategy factory ideas (`scripts/strategy_factory.py`) | `claude -p` Opus on the plan (Mac launchd) | Sundays | launchd | CLAIM paused 10-16 | 0 passes |
| Opening lab (`research/opening_lab`) | Sonnet 5.5 API or `claude -p` | manual | — | archived in spirit | no edge |
| Radar outcomes review (`scripts/radar_outcomes_review.py`) | research job on the plan | Fri 18:30 hand-installed timer | — | CLAIM first run scored 0 | — |
| **Jo (OpenAI Dots)** via Check MCP | external model on ChatGPT; TradeJournal computes, Jo narrates | ChatGPT scheduled tasks, Gmail wakes | Check config flags | CLAIM morning 1/5; owner deprioritised 10-29 | none committed |
| **Claude Duet** via Check + journal MCP | external Claude; same tools under a client-bound profile | Duet standing instructions | profile `enabled` | CLAIM server ready 10-27, instructions not sent | none |

Everything else that looks like AI is deterministic Python: Radar rules, pre-trade check verdicts, position alerts, plan nudges, time stops, thesis watch triggers, level alerts, fill interrupts, the ping policy, outcomes, Proof, scorecards, the weekly rule page, the evening review, Research Studio, the scanner, the scalper, the Market Map port.

### B.2 Context assembled for a copilot turn (VERIFIED)

1. Context line from the UI (page, symbol, timeframe, chart levels or a "Plan a trade:" / "Review this position:" / "Explain this candle:" prefix).
2. Owner context pack (`copilot_context.py`, ≤5,500 chars, shed in a fixed order): open positions with hold time, DTE, give-back state, phone alerts and the captured plan; closed trades in the symbol (≤4) and totals; the four exit habits against baseline; ≤8 approved memories; today's journal entries; saved investigations (titles, plus one-line conclusions for copilot records only); armed watches and waiting research jobs.
3. "Earlier evidence" carry: up to six previous tool results, clipped to 2,500 characters each, from an in-process dict.
4. Text-only history (≤23 messages, ≤38k chars), cards and outcomes omitted, screenshots reduced to a marker.
5. System prompt (16.6k chars, ≈4k tokens) and 18 tool schemas (≈4-5k tokens). Typical first round ≈10-12k input tokens; worst case ≈40k.

### B.3 Information flows between systems

- **Memories.** One store (`JoMemoryRevision`). Jo proposes into a review queue; the copilot card writes directly as an active owner statement. Readers: copilot pack, Jo packet, prep, thesis watch.
- **Saved investigations.** One table, three writers (copilot, research job, Jo research). The copilot reads findings via `get_saved_research`; transcripts are never shared across threads.
- **Plans.** Copilot `trade_plan` card → capture + two level alerts + time stop (browser-orchestrated, non-atomic). Jo `conditional_plan_create` → Check ledger → app monitor. Separate pages.
- **Radar → AI.** Copilot: group comparison and candle moments only, no feed. Jo: nightly dossier (#608, not yet live). Shadow book: strong events. Companion: events on held symbols.
- **Outcomes.** Sync pipeline writes an `Outcome` row for each ping, plan, Radar event, Jo research and shadow decision; read by Proof, the trade page and the week review. Nothing reads it to change behaviour.
- **Phone.** Copilot-side senders → `notification_policy` → Telegram/ntfy. Jo-side senders and the scanner → ntfy directly.

---

## C. Ideal future architecture

Design principle: **one conversational brain, one context service, one monitoring layer, one review loop, one outcomes ledger**, with external agents as optional slow contributors. Most of it exists; the work is to connect and prune.

### C.1 Components and their jobs

1. **Copilot (primary interface, Messages API).** The only place the trader talks to an AI about markets and positions. Interactive, fast, read-only, proposes cards. It must know, without asking, everything in the Trader Context Service for the symbol in front of it.
2. **Trader Context Service (server-side, deterministic).** The owner pack grown up and shared. One function returns, for a symbol and moment: positions and their *thesis objects* (the plan or the companion's adopted thesis, with entry conditions, invalidation, horizon, revisions), what changed since entry (price vs levels, group vs SPY, news matched to the thesis symbols, IV, time, alerts fired, decisions taken), the regime strip (SPY/QQQ/VIX/10y/sector ETF from Radar's own recorded passes), today's Radar events, the trader's record for this setup, open proofs. Consumers: copilot, companion, prep, week review, Telegram, research jobs, Jo dossier. Today five copies of this assembly exist with different staleness.
3. **Evidence store.** Saved investigations as the single memory of conversations, with tool results persisted per message (not a process dict), cards and their outcomes re-sent as compact structured lines in history, and symbol-level rollups ("what we concluded about NBIS this week") generated deterministically from closed threads.
4. **Monitoring layer (deterministic).** Position alerts, plan alerts, time stops, thesis watch, Radar, interrupts. All through one ping policy, including Jo's and the scanner's senders. One "position change detector" that owns the 60-minute mark, the close, the wrong-way check and the companion's echo, emitting one message per meaningful change with the original plan quoted.
5. **Review loop.** Close the day collects decisions and ratings → the nightly review reads what Close the day collected (pings, feedback, outcomes, practice score) → the week review proposes exactly one practice → the monthly review grades the practice. One rule system, the practice goal.
6. **Background research (Agent SDK).** Research jobs for deep dives with web, triggered by the owner, by a thesis-matched trigger, or by a strong Radar event. Results land in the evidence store and reach the copilot by default when they concern a symbol in front of the trader.
7. **External agents (optional, slow, never on the phone).** Jo as a nightly dossier and red team, Duet only if five rated mornings show value. Neither touches intraday.
8. **Shadow (one, or none).** Keep the copilot shadow book only with a pre-registered criterion and a comparable baseline; otherwise turn it off.

### C.2 What stays deterministic

Prices, levels, group comparisons, Greeks, sizing, time stops, every trigger, every outcome, every scorecard, the plan ladder, the ping budget, the "what changed since entry" diff. The LLM interprets, debates, drafts plans from levels the code found, explains candles from evidence the code aligned, writes review prose over numbers the code computed, and extracts memories the owner confirms. Nothing the LLM says changes a computation.

### C.3 How evidence, decisions, plans and outcomes flow

Radar/news/levels (deterministic observation) → context service → copilot conversation → plan card (owner confirms) → thesis object + alerts → monitoring layer emits change messages → owner decision recorded (Holding/Exiting/Why) → fills link to the plan → outcomes engine scores the ping, the plan and the decision → Close the day and the week review read the scores → practice goal → next week's context service carries the practice as a memory the copilot can raise when the situation resembles it.

### C.4 Background intelligence vs time-sensitive responses

Time-sensitive (seconds): copilot turns, change messages, plan alerts. These must never wait on web research or a background queue; the copilot answers from the context service and its fast tools, and offers "Research deeper" when a question needs the web.
Background (minutes to hours): research jobs, nightly dossier, nightly review, outcomes scoring, Radar outcome scoring, practice scoring. These write to the evidence store and surface as "New since you looked" in the thread, not as pings, unless a material-change check passes.

---

## D. Context and data gap analysis

### D.1 Gaps that matter, ranked by what they block

| Gap | Why it matters | Where the data already is | How to provide it |
|---|---|---|---|
| IV and Greeks hidden from the copilot (VERIFIED) | Contract fit, theta cost, break-even and sizing at invalidation are impossible; the prompt lies to the model about availability | Tradier chain (`options_chain.py:139-145`), position marks (`quotes.py:195-211`), Alpaca snapshots in `pre_trade_check` | Pass `mid_iv`, `delta`, `theta`, `vega` with `greeks_updated_at` through `copilot_options`; expose position Greeks in the pack; delete the prompt sentence |
| No regime context | "Why is NBIS moving" cannot be separated from "the market is moving" | Radar records SPY/QQQ/IWM/RSP and 11 sector SPDRs every minute; VIX and TNX via Tradier; macro calendar JSON | A `get_market_regime` tool and a two-line regime strip in the pack (SPY/QQQ/VIX/10y/sector ETF of the symbol, from recorded passes) |
| Copilot cannot see the Radar feed | "What did Radar see today?" is unanswerable; Jo's dossier will see more than the copilot | Radar store; `radar_movers`, `radar_comparison` | A `get_radar_today` tool (events, movers, group summaries, as-of) |
| Thesis chain missing for positions | "What has changed since entry" is the monitor goal; today the model sees a plan's wording but not the revisions, decisions or alerts since | captures, capture_links, level alerts, outcomes, day-journal decisions, companion rows | The thesis object in the context service: plan + revisions + alerts fired + decisions + what the levels and group did since entry |
| Cards and outcomes absent from history | The model does not know a plan was confirmed or dismissed two turns ago | investigation transcript holds cards and outcomes | Re-send one structured line per card: `[card trade_plan NBIS entry 95.9 inv 93.4 — confirmed 10:41]` |
| Carry is process-local and tiny | Follow-ups re-read after a reload or restart; clipped JSON reaches the model | tool results exist only in the SSE stream | Persist per-message tool results in the investigation (bounded, compacted), key the carry on the investigation, not a 2-hour dict |
| Fundamentals, events, filings, estimates | "What is the catalyst" and "when is earnings, BMO or AMC" | `symbol_info_*` (Tradier/Morningstar, SEC, Yahoo, Webull); `compact_events` drops dividends/splits; news sentiment dropped | One compact `get_symbol_profile` tool (valuation, next earnings with confirmed/estimated, dividends, short interest, analyst range); keep sentiment in `compact_news` |
| Proof, outcomes, scorecards | The copilot cannot discuss whether alerts or Radar are helping, which is the stated proof | `exit_habits`, `plan_proof`, `radar_proof`, `outcomes`, `alert_scorecard` | `get_proof` tool returning the three Proof cards and the outcome table for the symbol or the week |
| Jo's checks and conditional plans | Two systems hold the trader's plans; the copilot sees one | Check ledger via owner reader | Either retire Jo plans or publish them into `copilot_plans.board()` |
| Analytics by setup | "How do I do on dip-buys after a gap down" uses `fill_market_context` cohorts Jo already has | `analytics.analyze`, `pretrade_features` cohorts, `setup_record` | Extend `get_level_history`/`setup_record` into a `get_my_record(setup filters)` tool |

### D.2 What the AI should know automatically, retrieve on demand, remember long-term

- **Automatically (pack):** positions with thesis objects and "since entry" diffs; today's regime strip; today's Radar events for the symbol's group; approved memories for the symbol; the practice goal; today's decisions; what is armed.
- **On demand (tools):** chart context and levels, group comparison, news with sentiment, candle moments, option candidates with Greeks and expected move, symbol profile, trade and week reviews, level history and setup record, saved research, Radar today, market regime, proof.
- **Long-term (confirmed memory):** beliefs, preferences, lessons and theses the owner confirmed; the active practice; symbol-level conclusions rolled up from closed threads. Never measured counts restated as traits.

### D.3 Structured memory, retrieval, shared services

- **Do not add embeddings or RAG.** One user, about 1,500 trades, a few hundred threads, symbol-keyed and date-keyed retrieval is exact and already indexed. Semantic search would add a dependency and fabricate relevance where exact lookup exists.
- **Do build the shared context service** (D.1 rows 2–5), because five assembly paths already diverge (owner pack, Jo packet, prep pack, Check published file with a 10-minute lag, Daily Review context).
- **Do make memory one path.** Both Jo and the copilot should propose; the owner should approve in one place; the copilot's direct active write (`frontend/lib/copilot.ts:765-774`) should go through the same proposed state with a one-tap confirm, so provenance stays uniform.
- **Guard against fabrication and leakage.** Keep the provenance labels; add `as_of` to the pack's since-entry diff; keep research findings out of the pack text (as today); never let a model-written conclusion become a "measured" fact (the current `saved` label does this correctly).

---

## E. Model, API and integration recommendations

### E.1 Models and backends

- **Interactive copilot: stay on the Messages API.** The plan backend as a production service remains against Anthropic's published guidance; the owner accepted that risk knowingly for research jobs, and the desk runs on it by default since October 26 (CLAIM). Recommendation: make the API the default for the desk and keep plan auth for background jobs only. Budget: at a measured $0.013–0.023 per Sonnet 5.5 turn (CLAIM, 10-24) and roughly double on Opus 5.5 ($4/$20 per MTok), 30 turns a day on Opus is about $1.50–2.00; the current $2/day cap and the $100/month credit fit if the two unrecorded senders are brought under the cap.
- **Routing.** Sonnet 5.5 at effort `low` or `medium` for follow-ups that reuse carried evidence and for Telegram replies; Opus 5.5 at `medium` for first reads, plan drafting, trade and week reviews; Haiku 5.5 ($0.10/$0.50) for the cheap classifiers the system lacks (does this headline touch this thesis; extract a memory candidate from the owner's words; is this follow-up answerable from carried evidence). Do not route by regex; route by the context line's kind and by whether carry covers the question.
- **Latency levers to test (EXPERIMENT).** The 7–11 s post-tool burst on Sonnet 5.5 is documented (CLAIM). Levers in order: (1) a proper cache breakpoint after tools+system and the pack placed *before* the volatile user text so cross-turn cache reads become non-zero (today they are probably near zero, INFERENCE); (2) `thinking: {type: "between_tools"}` on Sonnet 5.5 for follow-up turns, which turns off thinking before the final answer; (3) effort `low` on follow-ups; (4) parallel pack assembly and a pack pre-warm when a thread opens. Measure `first_text_ms` before and after on the same 20 replay prompts.
- **Structured output.** Use `output_config.format` for the Verdict/Read/Against lines instead of prompt-only formatting and substring tests; the UI already parses them.

### E.2 Data and providers

| Candidate | Question it improves | Existing source adequate? | Verdict |
|---|---|---|---|
| IV, Greeks, expected move, skew | contract choice, theta, break-even, "is the move priced in" | Yes: Tradier/ORATS hourly in the chain; `options_implied.straddle` computed; skew computable from per-strike IV | **Expose, no new provider** |
| IV rank / term structure | "is premium rich today" | No history anywhere; `options_recorder` stores OI/volume only | Add `iv`, `iv_smoothed` and ATM straddle per expiry to the recorder now ($0); a paid backfill (ORATS/ThetaData) only if IV rank proves decision-relevant after months of use (HYPOTHESIS) |
| Sector/ETF relative strength, VIX, rates | regime | Yes: Radar passes, Tradier indices | **Expose** |
| Unusual options activity / flow | discover | Partial: contract volume vs overnight OI in chains, daily OI deltas; Tradier options time-and-sales unprobed; Unusual Whales API $150–375/mo (CLAIM from vendor post, May 2025) | Probe a volume/OI scan over ~30 Radar names within the 30/min Tradier options budget first; **no paid vendor before that** |
| Breadth (A/D, highs/lows) | regime | No; RSP vs SPY and the 169-name sample are proxies | Try a batched Alpaca/Tradier snapshot over a wider list before any vendor (HYPOTHESIS) |
| Economic calendar | monitor, understand | Static hand-kept FOMC/CPI/jobs file | **FRED (free, key)**: cheap, justified |
| Earnings time (BMO/AMC), estimates | decide | Dates from Tradier; estimates from Yahoo/Webull (unofficial); no time of day | Keep; try Benzinga headlines for call times (HYPOTHESIS); no paid estimates |
| 8-K / Form 4 / filings text | understand | EDGAR submissions free, not built | Later, after a VPS probe; no paid provider |
| Alpaca options feed OPRA vs indicative | contract liquidity | indicative is derived and 15-min delayed on trades (vendor docs); Tradier is real-time | Prefer Tradier for the copilot; do not pay for OPRA now |
| Institutional / 13F, sentiment, social, Level 2, moomoo, Polygon upgrade | — | Low marginal value for short-dated options; social declared not wanted | **Avoid** |

### E.3 Integrations to avoid

New agents (do not build for Duet; judge it from five rated mornings with the connectors already set), new MCP servers, embeddings/RAG, fine-tuning, a second conversational interface, and any new ping sender outside the policy.

---

## F. Prioritised improvement roadmap

Scores: value to the trader (V), intelligence gain (I), complexity (C), operating cost (\$), risk (R), confidence that it helps (K); 1 low to 5 high.

| # | Opportunity | V | I | C | $ | R | K | Notes |
|---|---|---|---|---|---|---|---|---|
| 1 | Measurement: link turns to threads, aggregate ratings, eval harness, latency table | 5 | 2 | 2 | 1 | 1 | 5 | Prerequisite for every other claim |
| 2 | Expose withheld data: Greeks/IV, regime, Radar today, symbol profile, proof | 5 | 5 | 2 | 1 | 1 | 5 | Mostly plumbing; no provider |
| 3 | Trader Context Service with thesis objects and since-entry diff | 5 | 5 | 3 | 1 | 2 | 4 | Replaces five assembly paths |
| 4 | Persist carry and card outcomes in history; symbol rollups | 4 | 4 | 2 | 1 | 1 | 4 | Fixes continuity |
| 5 | Consolidate the loop: one outcomes engine, one practice system, Close the day → nightly review, retire per-trade reviewer | 4 | 3 | 3 | 1 | 2 | 4 | Removes four duplicates |
| 6 | One ping policy for all senders; fix prep/nudge budget sharing; dedupe the 60-minute stack | 4 | 1 | 2 | 1 | 1 | 5 | Directly protects the Radar proof |
| 7 | Bring prep and week review under the spend cap; one shared turn wrapper | 3 | 1 | 1 | 1 | 1 | 5 | Fixes a live accounting hole |
| 8 | Radar discovery v2: relative volume vs ADV, gap/premarket, multi-day RS, catalyst sweep, wider universe | 4 | 3 | 4 | 2 | 3 | 3 | Only after the v0 proof reads out |
| 9 | Latency: cache layout, `between_tools`, effort routing, parallel pack | 4 | 1 | 2 | 1 | 1 | 3 | Measure first (needs #1) |
| 10 | Thesis watch relevance: match headlines to the thesis and symbols, not "any headline" | 3 | 3 | 2 | 1 | 1 | 4 | Haiku classifier or keyword overlap |
| 11 | Retire the Jo time-critical stack and dormant servers; one current-state doc | 3 | 1 | 3 | 1 | 2 | 4 | Owner already decided the direction |
| 12 | Jo nightly dossier and red team | 2 | 3 | 1 | 1 | 1 | 2 | Cheap; judge by whether the copilot cites it |
| 13 | Shadow book criterion or off | 2 | 1 | 1 | 1 | 1 | 4 | Decide, do not extend |
| 14 | IV recording for a future IV rank | 2 | 2 | 1 | 1 | 1 | 3 | $0 now, pays off in months |
| 15 | FRED macro calendar | 2 | 2 | 1 | 1 | 1 | 4 | Free |

Deliberately not on the list: more plan-card features, more phone ping kinds, more labs, Duet build-out, paid flow data, new MCP tools for Jo.

---

## G. Five highest-impact implementation proposals

### G.1 Measure the copilot before changing it

**Problem.** Ratings exist but no code reads them; `copilot_turn` records cost and tokens but no investigation id, tool names, first-text latency or cache writes (`copilot_spend.py:24-41`, `models.py:883-900`); prep and week review bypass it entirely. Every quality test is a fixture; no eval scores answers.

**Design.**
1. Add `investigation_id`, `tool_names`, `first_text_ms`, `max_silence_ms`, `cache_creation_input_tokens` and `kind` (chat, prep, week_review, companion, telegram, shadow) to `copilot_turn`; record every model turn through one shared wrapper (today copy-pasted five times).
2. `GET /copilot/answer-scorecard`: Helped/Didn't rate by kind, symbol, backend, model and tool mix; pushback rate; follow-up rate; median first text; cost per thread. Show it in the desk Briefing's "This week" tab next to the Proof.
3. Eval harness `backend/scripts/copilot_eval.py`: a case file of 30–50 prompts drawn from real threads (the owner's words, anonymised symbol context kept), each run under `COPILOT_EVIDENCE=replay` at the thread's original moment where a Radar snapshot exists, else fixture. Deterministic checks: Verdict line present and from the fixed set; every number in the body traceable to a tool result's value and `as_of`; no tool re-read when carry covers the question; "Unsupported:" used when the prompt plants a rumour; Against line present. Rubric checks by an Opus 5.5 judge with a fixed rubric (decision relevance, uses the position and plan, separates thesis from position, length). Report per model/effort/backend with cost and latency.
4. A weekly deterministic "Verdict vs what followed" table from `outcomes.py` for Verdict lines on positions (Hold/Broken/Wait), replacing the planned Jo Friday audit.

**Files.** `app/ai/copilot_spend.py`, `app/models.py` (additive migration), `app/ai/copilot.py` (metrics), `routers/copilot.py`, `engine/premarket_prep.py`, `engine/week_review_auto.py`, `engine/position_companion.py`, `engine/telegram_replies.py`, `app/ai/shadow_turn.py`, new `scripts/copilot_eval.py`, `frontend/components/copilot/Inspector.tsx`.
**Dependencies.** None. **Acceptance.** All six turn kinds write one row with a kind; scorecard route returns rates over the last 7 days; eval runs 30 cases offline under $0.50 with a reproducible report; a prep turn past the daily cap is refused and recorded.
**Expected benefit.** The first number for "is the copilot helping": a Helped rate by kind within one week of use, plus a regression gate for every prompt change.

### G.2 Give the copilot the data the app already holds

**Problem.** Greeks and IV are stripped; no regime, Radar, profile or proof tools; `get_quotes` is price-only and mislabels its source (`copilot_tools.py:874`).

**Design.**
- `get_option_candidates`: pass `mid_iv`, `smv_vol`, `delta`, `theta`, `vega`, `greeks_updated_at`, bid/ask sizes, and the ATM straddle expected move for the chosen expiry (`options_implied.straddle`); delete the "no IV or Greeks" sentence from the prompt; fill the plan card's `delta` field.
- New `get_market_regime(as_of?)`: SPY/QQQ/IWM/RSP day and 15-minute change, VIX, 10-year, the symbol's sector ETF vs SPY, next macro event, all from recorded Radar passes and Tradier indices with `as_of`.
- New `get_radar_today(group?)`: today's events (first seen, direction, points vs SPY, revision), movers leaders/laggards, group summaries.
- New `get_symbol_profile(symbol)`: valuation line, beta, next earnings with confirmed/estimated and time if known, dividends/splits within 30 days, short interest, analyst target range, labelled official/unofficial.
- New `get_proof(scope)`: the three Proof cards and the outcome table for a symbol or the week.
- `compact_news` keeps Polygon sentiment; `get_quotes` returns change % and volume and names the real provider; `get_positions` carries position IV and delta.
- Replay support for each new tool (refuse or freeze; never leak).

**Files.** `app/ai/copilot_tools.py`, `app/ai/copilot_options.py`, `app/ai/copilot.py` (prompt lines 76-81 and 1112-1126), `app/ai/copilot_replay.py`, `app/ai/copilot_fixture.py`, `engine/radar_movers.py`, `engine/radar_comparison.py`, `engine/chart_indices.py`, `engine/symbol_info_*`, `tests/test_copilot_option_candidates.py`, new tests per tool, `research_job.JOB_TOOLS` (add regime and profile, not proof).
**Dependencies.** G.1 for before/after measurement. **Acceptance.** Each tool returns bounded JSON with provenance under 10 s; fixture and replay variants exist; the adversarial suite passes; a replay NBIS prompt cites the sector ETF and IV in its body; the eval's "numbers traceable" check stays at 100%.
**Expected benefit.** The copilot can answer the three example questions in the brief (why is it moving vs the group and market; is this contract priced for the move; what is the catalyst) from evidence instead of saying the data is unavailable.

### G.3 A Trader Context Service with thesis objects and "since entry"

**Problem.** Five assembly paths; the model sees a plan's wording but not what changed since; the companion guesses a thesis; the Daily Review never sees pings or feedback.

**Design.**
- `engine/trader_context.py`: `for_symbol(symbol, now)` and `for_day(now)` returning one typed, provenance-labelled structure built from existing readers (`copilot_book`, `capture_links`, `position_alerts`, `level_alerts`, `outcomes`, `day_journal`, Radar passes, `exit_habits`, `practice_goal`, `jo_briefing.memories`).
- A thesis object per open position: source (plan card, PlanSheet, companion adoption, none), thesis text, entry trigger, invalidation, time stop, horizon, revisions (owner edits, companion updates), alerts fired, decisions recorded (Holding/Exiting/Why), and a deterministic "since entry" diff: underlying vs entry and vs invalidation, group vs SPY since entry, IV now vs at entry (from `*_at_fill`), thesis-matched headlines since entry, time held vs horizon.
- The owner pack becomes a renderer over this service; prep, week review, companion, Telegram and the Jo dossier publisher call it instead of their own collectors; the Daily Review context adds the day's pings, feedback, decisions and practice score from the same service.
- Cards and outcomes are re-sent as one structured line each in history; tool results are persisted per message in the investigation and the carry is keyed by investigation id (bounded, compacted), so a reload or restart does not re-read.

**Files.** New `engine/trader_context.py`; `app/ai/copilot_context.py`, `app/ai/copilot.py` (carry), `engine/copilot_investigations.py` (per-message evidence), `routers/copilot.py`, `frontend/lib/copilot.ts` (history lines), `engine/premarket_prep.py`, `engine/week_review_auto.py`, `engine/position_companion.py`, `engine/telegram_replies.py`, `engine/jo_research.py`, `app/ai/review_context.py`, tests for each consumer.
**Dependencies.** G.2 (regime and Radar readers). **Acceptance.** One service call per turn; the pack shows the since-entry diff for a held symbol with `as_of`; a follow-up after a server restart makes no new tool calls when the carried evidence covers it (test); the companion's adopted thesis and the plan card use the same object; the Daily Review prompt receives the day's pings and feedback.
**Expected benefit.** "Understand my original plan and what has changed since" becomes a measured fact the model is handed, not a reconstruction. Removes five diverging context assemblies and the 10-minute-stale copy Jo reads.

### G.4 One loop: outcomes, practice, review, pings

**Problem.** Four rule systems, four alert-outcome calculators with two valuation bases, two per-trade reviews, six end-of-day surfaces, a prep budget that holds the Friday review, Jo and scanner senders outside the policy, three mechanisms at the 60-minute mark that the counterfactual says is uninformative.

**Design.**
- `outcomes.py` becomes the single source for "what followed"; `alert_scorecard`, policy `FollowUps` and `radar_scorecard` read its rows; one valuation basis (midpoint, with bid shown as a sensitivity).
- The practice goal is the one rule system: retire the deterministic weekly rule page; the daily review's `next_session_rules` are replaced by "practice check" against the active goal; the monthly `one_commitment` reads the practice history.
- Retire `ai/reviewer.py` and `Trade.ai_review`; the trade page's review button calls the copilot's `get_trade_review` turn.
- Close the day is the one end-of-day surface: Watch your day and the evening ping fold into it; the nightly review reads what Close the day collected.
- Every sender goes through `notification_policy.decide`: `stock_watch`, `conditional_plans`, `market_watch_wakes`, `setup_scanner`, `paper`. Separate budgets for `prep`, `week_review` and `day_replay`; `companion_adopt` leaves the `nudge` budget. The companion's 60-minute floor and drafted 60-minute stop yield to `hold_hour`, and its echo update after a deterministic alert is merged into that alert's message.

**Files.** `engine/outcomes.py`, `engine/alert_scorecard.py`, `engine/notification_policy.py` (BUDGETS, ALIASES), `engine/radar_scorecard.py`, `engine/weekly_review.py` (retire), `app/ai/daily_reviewer.py`, `app/ai/monthly_reviewer.py`, `app/ai/reviewer.py` (retire), `routers/trades.py`, `engine/evening_review.py`, `engine/day_replay.py`, `engine/position_companion.py`, the five ungated senders, `frontend/components/WeeklyReviewPanel.tsx` (retire), tests.
**Dependencies.** G.1. **Acceptance.** `test_notification_policy` asserts the week review is *sent* after the morning brief; a Jo stock alert is held by the daily ceiling in a test; one long option across a full day produces at most one message per distinct event in a replayed fixture; the scorecard and outcomes agree to the cent on a fixture; the daily review's prompt no longer coaches on entry flags the audit found non-predictive.
**Expected benefit.** Fewer, truer pings during the Radar proof; one number for every alert's aftermath; one rule the trader is practising instead of four.

### G.5 Radar discovery v2 and a copilot that can read it

**Problem.** Radar detects intraday price vs SPY/sector over 169 names from the owner's own buckets; no relative volume, no gaps, no multi-day strength, no catalyst sweep. The strong-event bar (7 points) sits above nearly every first-sighting reading in calibration (INFERENCE), so phone singles and the shadow book starve. The copilot cannot see the feed.

**Design.** After the v0 proof reads out (20 certified sessions, late November at the earliest):
- Deterministic detectors on the existing recorder: relative volume vs the 20-session same-time average (from cumulative volume already recorded); gap at the open from recorded open vs prior close (promote the premarket pilot or delete it); 5-day relative strength vs sector from Radar's own retained sessions; catalyst flag when `symbol_info_events` has earnings within 2 days.
- Universe: keep the curated groups, add a daily top-N by premarket dollar volume from a batched Tradier/Alpaca snapshot (within budget), so names outside the watchlist can appear.
- Expose `get_radar_today` (G.2) and let a strong event or dip event start a research job only when the trader taps "Investigate", not automatically for every event.
- One outcome scorer (G.4) with the frozen decision rule; a new rule version restarts the count.

**Files.** `engine/radar_rules.py`, `engine/radar_dip.py`, `engine/radar_premarket.py`, `engine/radar_movers.py`, `app/data/radar_universe.json` (merge `peer_groups.json`), `scripts/radar_outcomes.py`, `engine/research_queue.py`, tests.
**Dependencies.** v0 proof read-out; G.2; G.4. **Acceptance.** Replay over the retained 20 sessions reports events, quick fades and outcome vs Movers per detector; no new detector is activated without its own frozen criterion; the copilot answers "what did Radar see today" from the tool.
**Expected benefit.** Discovery that matches the end goal's words (unusual activity, momentum, names outside the watchlist), measured before it pings.

---

## H. What we should stop doing

**Stop building ahead of the two proofs.** The end goal's own ordering. Freeze new senders, new card features and new labs until Proof #1 (alerts) and Proof #2 (Radar) have a number, and stop launching interventions inside the Proof window; each one confounds the read.

**Retire or archive (no demonstrated benefit, or superseded):**
- Strategy factory scheduling and `factory_paper_replay.py` (0 of ~85 passes; paused in practice, not in docs); keep the ledger and the evidence note.
- `research/opening_lab` (no edge in four rounds); keep `setup_record.py`.
- Research Studio's prospective MU collector unless it is confirmed installed; the studio itself is frozen.
- The manual A1–A3 advisor fixtures (`advisor_shadow.py`, `AdvisorShadowPanel`, `AdvisorOwnerReview`), the D0/D1/D2 sample servers and the `TJ_DOT_TRIAL_*`/`TJ_CLOUD_MCP_*` flags, the advisor fixture server, the forecast study server: all dormant, sample-only or invented data.
- The A3 practice stack (`practice_agent.py`, `practice_schedule.py`, `routers/decisions.py`, the practice lane): never enabled, separately billed.
- `tradingview_analysis.py` and its 16 tests (dead since C5.2); the Pine `market_map` port once its bar primitives are split out.
- The per-trade AI review (`reviewer.py`) and the deterministic weekly rule page, in favour of the copilot's reviews and the practice goal.
- `GET /copilot/threads`, `getOpenThreads`, `getPlansBoard`, `DESK_GROUPS` (no callers); the `MOMENT` regex outside the FakeAdapter; `backend/prompts/market_report.md` (unreferenced).
- One of the two Shadow-Isaacs. The copilot shadow book has server-side control and an observable trigger; S1 has zero takes and admitted non-independence. Whichever stays needs a pre-registered criterion.

**Switch off or demote (owner already decided the direction on October 29):** Jo's scheduled market reads, MW-2 wakes, setup emails and conditional price watches; keep Jo for the nightly dossier and red team if the copilot ends up citing them, otherwise stop. Record the switch-off on the board.

**Shrink the paperwork.** Fold the 22 Jo/advisor/shadow contracts into one current-state page plus an archive; update `CLAUDE.md`'s "Dots first" priority to the October 29 decision; fix the stale sentences (`radar.md:12,16`, `copilot-lab.md:2421-2423`, the "five/eight tools" counts).

**Stop asking twice.** Every alert and Radar hit asks for a decision and then for proof feedback; "Skip" and "No plan" answers live only in one browser. Record the decision once, server-side, and derive the feedback.

---

## I. Recommended next 30 days

Gates are proof gates: no step expands scope until its gate passes.

**Week 1 — measure and plug (G.1, part of G.4).**
- One turn wrapper; `copilot_turn` gets kind, investigation id, tool names, latency, cache writes; prep and week review under the cap.
- Answer scorecard route and Briefing tile; eval harness with 30 real prompts under replay/fixture; baseline numbers for Helped rate (if any ratings exist), first-text latency, cost per kind.
- Separate `prep`/`week_review`/`day_replay` budgets; route Jo and scanner senders through the policy.
- *Gate:* a week of real use produces rated answers and a latency table; the Friday review is delivered.

**Week 2 — expose what exists (G.2).**
- Greeks/IV/expected move in option candidates; regime, Radar-today, symbol-profile and proof tools; quotes with change and volume; news sentiment kept.
- Re-run the eval; compare Opus vs Sonnet and effort levels on the same cases for traceability, decision relevance, latency and cost.
- *Gate:* traceability stays 100%; Helped rate does not fall; the NBIS-style question cites IV, sector and group.

**Week 3 — context and continuity (G.3).**
- Trader Context Service with thesis objects and since-entry diff; persisted carry; cards in history; prep, week review, companion and Telegram on the service.
- *Gate:* follow-ups after restart make no redundant reads (test); the companion and the plan card share one thesis object; the Daily Review sees pings and feedback.

**Week 4 — consolidate the loop (rest of G.4) and decide the labs (H).**
- Single outcomes source; practice goal as the one rule; retire the per-trade reviewer and the weekly rule page; Close the day as the one end-of-day surface; 60-minute de-duplication.
- Decisions: shadow book criterion or off; Jo time-critical stack off and recorded; archive the factory and opening lab; delete dormant servers behind a user-gated PR.
- *Gate:* ping count per position per day falls in a replayed fixture; one scorecard; the board and `CLAUDE.md` describe the actual state.

**Not in the 30 days:** Radar v2 (waits for the v0 proof), any new provider, Duet build-out, new card features. Proof read-outs on alerts and Radar happen on their own frozen schedules and are reported, not acted on, until they conclude.

---

## Supporting sections

### 1. Audit summaries by system (what it does, receives, invokes, stores, cannot do)

**Copilot chat.** Receives the context line, owner pack, carry, text history. Invokes Messages API (or plan) with 18 tools; tools run in parallel within a round, rounds sequential; 10 s per tool, no cancellation of the worker thread on timeout. Stores one `copilot_turn` row and, from the browser, the investigation transcript with cards, outcomes and ratings. Cannot: see Greeks, regime, Radar feed, fundamentals, proof, other threads' content, Jo's checks; schedule anything except through a confirmed card; act server-side (Confirm is 3–5 browser POSTs across four subsystems; a closed tab mid-confirm leaves a half-armed plan, `frontend/lib/copilot.ts:725-793`). Redundant: `get_positions`/`get_trades`/`get_memories`/`get_owner_context` largely duplicate the pack; ~480 lines of FakeAdapter live in the production module.

**Copilot desk and Charts dock (frontend).** Home when the lab is on, but the installed PWA still opens on `/` (`manifest.ts`). Threads: Main plus one row per ticker; Plans view; Waiting-for-you as a dot only. Answers: verdict chip, Read line, body, Compare block, Against, Changes if, Push back per line, Sources fold, Helped/Didn't. Cards: watch, revisit, memory, practice, trade_plan with 7–9 editable fields. Context pane: server PNG chart, timeline, history at invalidation. Decision bar: Holding/Exiting/Ask why → day-journal entries; close question; exit review. Pings land on seven different surfaces; only position alerts land on the decision bar. "Skip" and "No plan" are browser-only. Telegram turns never appear on the desk.

**Jo / Dots.** Seven MCP servers; Check holds 34 tools on one Jo identity plus an optional client-bound Duet profile. Every read tool is deterministic; Jo narrates and writes back verdicts, briefings, memories, market reads, stock alerts, conditional plans, follow-ups, research. Context Jo gets: a frozen morning packet (≤80 items/96 KB), a published positions/captures file 10 minutes stale, a feature file for cohorts. TradeJournal cannot observe Jo's trigger (`origin` always unknown). Delivery honesty and watchdog exist. Evidence of value: none committed.

**Pre-trade check.** Pure function; intraday verdict comes from the scalper engine with history and risk allowed only to downgrade; swing rules are textbook and "not fitted to Isaac's trades" (`pretrade_check.py:24`). Cohorts: same setup (underlying, side, time bucket, VWAP bucket), minimum 8 trades; `rvol_bucket` computed but unused. Grading built; nothing graded in the repo.

**Shadow.** Jo S1 (scanner emails, TAKE/SKIP, 8/8 skips, pipeline accepted Oct 17, independence unverifiable); copilot shadow book (Radar strong events, Agent SDK on the plan, no criterion, probably starved by the 7-point bar); S2 display-only; A1–A3 invented fixtures.

**Reviews.** Daily (every trade of the day, three prior reviews' rules, baseline 20 days, rich market context, ~30 prompt lines on entry flags the audit found non-predictive); monthly (stats only, one commitment); per-trade (prose over deterministic inputs); weekly rule page (no model, "not yet used on real weeks" CLAIM); Review my week (copilot turn over a deterministic review, proposes one practice); evening review (no model, counts what waits). Nightly timer reviews only the latest day, never backfills.

**Monitors.** Position alerts (give-back arms at +10%/$50, fires at +3%; last-day 90/30 min; day-before 15:30; hold-hour; wrong-way at 30 min), plan nudges (3 min after an unplanned entry), time stops, thesis watch (any new headline, 4% move, earnings ≤2 days; up to 25 symbols every 15 min), level alerts (at-least-once, 6-hour expiry, so a stale invalidation can arrive hours late), fill interrupts (four rules, off), position companion (model; adopt, ≤4 updates/day, close; ≤6 positions). All on one sequential loop in the API process except thesis watch and the companion.

**Ping policy.** Priority order, quiet window, never-capped ranks 0–2, per-kind budgets, pre-open allowance, daily ceiling 12, never-held evening review, every decision a row, follow-ups recorded. Defects: shared `prep` and `nudge` budgets; five ungated senders; companion updates outside the ceiling.

**Feedback loops.** Alert feedback, scorecard, ratings, Radar ratings, outcomes, exit habits, plan proof, plan streak, practice goal, daily rules, companion/interrupt answers: all stored; none changes behaviour except model-to-model. Proof confounded by overlapping launches; bid vs mid bases disagree.

**Radar.** Recorder (169 symbols/min, Tradier, 20-session retention), v0 rules (4.5 points vs SPY, 3 passes), v1 candidate, dip rule, digests and strong singles, movers, group comparison, news nearby, premarket pilot (off), outcome scorer (weekly, 20-session decision), /proof (0 ratings Oct 26). No model calls. Cannot detect volume vs ADV, gaps, multi-day strength, catalysts, names outside the curated list.

**Research jobs.** Agent SDK, Sonnet 5.5, web plus seven lab tools, citation and hindsight checks, saved as open investigations, one runner, retries, budgets. Triggers: owner, revisit, thesis watch; Radar trigger (every event, no strength filter) and reassess are off. Two documented live runs.

**Company Research / AI Buildout.** Two disconnected fundamental workspaces; model-free server side; filled by a Claude skill outside the repo or by Duet/Dots through Check; invisible to the copilot.

**Labs.** Factory (0 passes), opening lab (no edge), Research Studio (nulls), scanner S1 (deterministic, Jo external, 0/17), four separate frozen-packet replay engines for Jo plus the copilot's own replay.

**Data providers.** Tradier (real-time quotes, chains with hourly ORATS Greeks, fundamentals, VIX/TNX; 120/min, ~70 allocated), Alpaca (IEX bars, SIP history to 2016, indicative options, Benzinga news; 60/min), Polygon Basic (enrichment, news with sentiment, peers, short data; 5/min), SEC companyfacts, Yahoo (unofficial default quotes, analysts, insiders), Webull (dormant), Gmail (fills), local Whisper, hand-kept macro/peer/universe JSON. TradingView webhook is retired in code despite a session note saying "live".

### 2. Workflows reimagined (what the AI should know, do, explain, save, follow up)

1. **Morning open.** Know: regime strip, overnight headlines matched to held and watched symbols, each position's thesis object and since-entry diff, today's earnings and macro, the active practice. Do: one brief of at most ten lines that leads with what changed for *his* positions, then two outside names from Radar premarket or news only when they carry a number; arm plans in one checklist. Explain: why each line is there (source, time). Save: the brief as the day's Main thread. Follow up: nothing until a change detector fires. One brief, not three.
2. **A stock moves unexpectedly.** Know: the symbol's group vs SPY now and over the session, sector ETF, news in the last two hours with publish times, Radar event state, the trader's record in the name, IV change. Do: order the explanations by evidence (headline → group → level → unknown), name what would change the read. Save: a thread with evidence refs. Follow up: offer "watch for X" as a card.
3. **Follow-up on a trade idea.** Know: the carried evidence and the cards already confirmed. Do: answer from carry unless stale or disputed; say "as of 10:41". Save: ratings. No re-reads.
4. **Chart or screenshot.** Know: the chart's symbol, timeframe, drawn levels, position. Do: read levels from the image, compare with computed levels, draft entry and invalidation from the drawing. Save: the drawing as the plan's levels (exists today, #519).
5. **Short-dated option entry.** Know: Greeks, IV, expected move to expiry vs the thesis's required move, spread, the trader's record for this DTE and time bucket, the opened-while-green and put-entry patterns. Do: name the mismatch between horizon and expiry, quote break-even and theta per day, propose one plan. Save: the plan with contract. Follow up: wrong-way at 30 minutes and the invalidation, once each.
6. **Holding while conditions change.** Know: the thesis object; which of its conditions changed (level, group, news, IV, time). Do: one message per meaningful change quoting the plan's own words, never an order. Save: the decision (Holding/Exiting/Why) once. Follow up: the outcome row.
7. **Actionable notification.** Know: everything in 6. Do: land on the decision bar, always the same surface; one tap records the decision; feedback is derived, not asked again.
8. **After a trade closes.** Know: plan vs path (entry, peak, give-back, exit vs invalidation and time stop), the alerts and what followed, the exit lesson if given. Do: a short review that keeps thesis and execution apart; propose a memory only in the trader's words. Save: the exit review on the plan thread.
9. **Weekly review.** Know: planned vs unplanned, follow-through, alerts and outcomes, practice score, long holds, exit lessons. Do: one practice for next week with its count. Save: the practice goal. Follow up: next week scores it.
10. **Investigate a theme.** Know: the saved research on the symbols, the group's recent Radar behaviour, held exposure to the theme. Do: queue a research job with web access, return with cited findings and counterpoints, and come back to the decision the thread started from. Save: the research as findings the copilot can cite. Follow up: a revisit card with a date.

### 3. Speed, cost, reliability and safety assessment

- **Latency (CLAIM 10-24; INFERENCE).** First tool feedback 1.4–1.9 s; first text 7.9–11.3 s on Sonnet 5.5 because the post-tool answer arrives in one burst; follow-ups with the hard length rule reached 0.9 s first text and 4.6 s total (CLAIM 10-29). The owner pack adds a DB and marks read to every turn before round one. The desk runs Opus 5.5 on the plan (CLAIM), for which no timings exist. Fixes are in E.1 and G.3.
- **Sequential calls.** Tool calls in a round are parallel; rounds are sequential; the pack is built serially; `propose_plan` adds a quote read. Most turns are two rounds (read, then write).
- **Context size and cost.** ≈4k tokens system, ≈4–5k tool schemas, ≤5.5k chars pack, ≤15k chars carry, ≤40k chars history, ≤6k chars per tool result. Prompt caching is top-level ephemeral only; cross-turn reuse is probably near zero (INFERENCE; check `cache_read_input_tokens`). $0.013–0.023 per Sonnet turn (CLAIM); companion turns share the $2/day cap; prep and week review are uncounted.
- **API vs subscription.** The plan backend as a hosted service conflicts with Anthropic's published guidance (quoted in `docs/copilot-lab.md`); the owner accepted the risk for research jobs and later made it the desk default. Recommendation in E.1.
- **Caching and freshness.** Quotes 60 s in memory, chains 60–600 s, events cached, habits 600 s, pack rebuilt per turn, Check's copy of positions 10 minutes stale. `as_of` on `get_quotes` understates age (`copilot_tools.py:802-804`).
- **Failure handling.** Each pack section fails independently; tool failures become `unavailable` results the prompt tells the model to name; a budget stop between rounds leaves no final answer; plan-backend failures carry Claude Code's reason; the nightly review never backfills.
- **Hallucination and citation.** Strong: tool-only evidence, provenance labels, "Unsupported:", research citation checks. Weak: no eval measures it; the prompt's false "no Greeks" statement is itself a planted untruth; replay `get_symbol_events` can leak a later-confirmed earnings date (`copilot_replay.py:143-147`).
- **Provenance and hindsight.** Replay freezes Radar passes, quotes and news; chart, book, peers, options and reviews are refused under replay; enrichment uses completed bars only. Good.
- **Safety.** No order path; writes only through owner confirmation; research jobs have no acting tools; prompt-injection defences and tests. Keep confirmation for every consequential change; do not add any trading authority.

### 4. Evaluation suite (design)

- **Cases.** 30–50 prompts from real threads across the ten workflows, each with the moment, symbol, position state and the owner's actual follow-up. Time-frozen via `COPILOT_EVIDENCE=replay` where a Radar snapshot covers the moment (October 22 onward), fixture otherwise; extend replay to freeze the book from fills and the chart from the SIP cache so position and chart questions can be replayed without leakage.
- **Deterministic graders.** Format (Verdict word from the set, Read/Against/Changes-if present when required, length); traceability (every number in the body appears in a tool result with its `as_of`); no redundant reads when carry covers the question; `Unsupported:` on planted rumours; no advice phrased as an order; latency and cost from the metrics line.
- **Model grader.** Opus 5.5 with a fixed rubric: decision relevance, uses the position and plan, separates thesis from position, strongest counter-case present, says what would change the view. Score 1–5 per item, with the rubric and judge pinned in the repo so runs compare.
- **Prospective signals (real use).** Helped rate by kind; pushback rate and what the pushback said; follow-up rate; plan-confirm rate after "Plan a trade"; decisions recorded after alerts; time to first text. Report weekly beside the Proof.
- **Keep two questions apart.** Explanation quality (graders above) and trading outcomes (Proof, outcomes engine, prospective only). Never let an eval score claim an edge.
- **Testable against the current implementation now:** cache layout change, effort and model routing, `between_tools`, Greeks exposure, regime tool, persisted carry (redundant-read count), ping consolidation (messages per position per day in a replayed fixture).

---

## Appendix: numbers behind the diagnosis (VERIFIED unless noted)

| Measure | Value |
|---|---|
| Merges Oct 20–30 | 253 (peak 55 on Oct 24, 37 on Oct 29) |
| Merges since Oct 1 | 694 |
| PRs touching copilot code since Oct 20 | 108 |
| New environment flags since Oct 20 | 53 (≈150 in total) |
| Engine modules / systemd units / backend tests / e2e specs | 187 / 59 / 274 / 78 |
| Agent docs / Jo-subsystem contracts | 46 files / 22 (~6,400 lines) |
| MCP servers / unique tools / Check tools / auth principals | 7 / 61 / 34 / ≈18 |
| Copilot tools / system prompt / tool schemas | 18 / 16.6k chars / 16.6k chars |
| Copilot limits | 4 rounds, 8 calls, 10 s/tool, 120 s, $0.25/turn, $2/day |
| Carry | in-process, 2 h, 6 items × 2,500 chars |
| History sent | ≤23 messages / 38k chars, text only |
| Radar | 169 symbols, 31 groups, 60 s passes, v0 4.5 pts/3 passes |
| Radar proof inputs | 0 ratings (Oct 26 report); 0 certified sessions (Oct 28 CLAIM) |
| Jo delivery board | 18 rows, 4 accepted; morning 1/5 (CLAIM) |
| Shadow S1 | 8 setups, 8 skips, 0 takes (CLAIM) |
| Strategy factory | ~85 judged, 0 passes |
| Behaviour audit | 1,528 trades; 1 h→close −$17,558; 53 up-10% losers −$15,304; opened-while-green −$8,942 |
| Counterfactual exits | give-back +$2,891 (CI −14.6k..+21.8k); hour −$10,170; expiry −$2,848 |
| Measured copilot cost (CLAIM) | $0.013–0.023 per Sonnet 5.5 turn; $0.10–0.11 per two-turn check |
| Current list prices | Opus 5.5 $4/$20; Sonnet 5.5 $2/$10; Haiku 5.5 $0.10/$0.50 per MTok |
