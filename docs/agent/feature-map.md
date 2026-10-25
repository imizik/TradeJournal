# Feature map

How to get from a feature to its screen, its endpoints, its code and its
proof. The code is the source of truth; this shortens the search and says
where the evidence for a change comes from.

Backend paths are relative to `backend/`, frontend paths to `frontend/`.

For Charts changes, use the [roadmap's execution order](../charts-roadmap.md#status-board)
and [C0.0 implementation contract](../charts-deep-history.md). The tables below
describe shipped code, including deep-history pagination, the split-adjusted price basis and daily/weekly depth.

## The screens

The private sidebar and phone More menu (`components/Nav.tsx`) put the everyday
pages first (Dashboard, Charts, Daily Review, Jo, Trades, Analytics, Fills), then
**Signals & practice** (Signals, Scanner, Radar, Daily Practice, Advisor review),
then **Labs** (Strategy Lab, Research Studio, Level 2 lab and AI Buildout). Assistant access remains available when enabled. A **Sync**
button opens a drawer on any page.

| Sidebar | Route | Page | Loads | Then, from the browser |
|---|---|---|---|---|
| Daily Practice | `/practice` | `app/practice/page.tsx` | `GET /decisions`, `/decisions/{id}`, `/practice/runs` | Existing Practice choice, reveal, timing, feedback and paper-plan actions |
| Personal Decision Replay Lab | `/practice/replay`, from Daily Practice | `app/engine/personal_replay.py`, `app/routers/personal_replay.py`, `components/PersonalReplay.tsx`, existing `FrozenSampleChart` | `/practice/replay/scenarios`, `/practice/replay/attempts`, attempt read/choice/reveal | Synthetic two-checkpoint exercise with server-sealed continuation; [workflow, reuse and data limits](../personal-decision-replay.md); `tests/test_personal_replay.py`, `frontend/e2e/personal-replay.spec.ts` |
| Owner thoughts | `/morning`, `/daily/{YYYY-MM-DD}` | `components/DayJournal.tsx`, `DayReviewWorkflow.tsx`, `lib/dayJournal.ts`; `app/engine/day_journal.py`, `app/routers/day_journal.py`, `DayJournalEntry` | Owner-only `GET /day-journal/{day}`, `POST /day-journal/{day}/entries`; original outlook, timestamped updates, ideas and reflections; optional symbol, no trade/account required | Retry-safe append-only entries and local draft recovery; thought/capture days appear in Daily Review even without trades; optional expectation checks cite original thoughts separately from plan adherence; `tests/test_day_journal.py`, `frontend/e2e/day-journal.spec.ts` |
| Dashboard | `/` | `app/page.tsx` | `GET /stats`, `/trades`, `/accounts`, `/trades/fills/bulk`, `/quotes?tickers=`, `POST /quotes/positions`; Attention: `GET /charts/alerts`, `/sync/jobs`, `/gmail/health`, `/charts/symbol/{symbol}/events` | `DashboardActions`: `GET /sync/summary`, `/sync/jobs`, `/sync/runs`, `/health`, `/auth/gmail/start`; `POST /sync/pipeline/run`, `/sync/jobs/{job_type}/run`, `/sync/advanced/rebuild-all`, `/sync/advanced/resync-all` |
| Charts | `/charts` | `app/charts/page.tsx`, `components/charts/`, `components/AppMain.tsx` | — | the page fills the window beside a navigation rail (C7.3): one toolbar row, a drawing-tool rail, a side dock (watchlist or layers; a bottom sheet on a phone) and a status strip, charts sized by the browser; dividers between the main chart and the smaller row, between the smaller charts and at the dock's edge, and Maximize on each chart (C7.4, `components/charts/Splitter.tsx`; proportions shared, dock width and maximize per device); `GET /charts/workspace` every 15s while visible for Tradier today/quotes; `GET /charts/history` on scroll: intraday pages from completed Alpaca SIP sessions, 1D/1W pages from Tradier's whole daily history (read once per day); prices are split-adjusted with a basis chip and a warning when splits are unknown, and saved levels move with later splits; private stream, linked timeframes, fill markers, countdown, full screen, symbol search; `GET`/`PUT /charts/settings` shares levels, watchlist and layout across devices with a revision check (browser copy offline); smaller charts can hold their own symbol (three symbols at most, one request and one stream); named layouts (intervals, held symbols, chart sizes, linked ranges) are saved with those settings and switched from the Layouts menu (`components/charts/LayoutMenu.tsx`); hotkeys (`lib/hotkeys.ts`: typed minutes on Enter, H/4/D/W, Space watchlist steps, Alt+R reset, End to realtime, Delete and ⌘/Ctrl+Z undo for levels and drawings) listed by the `?` sheet (`components/charts/HotkeySheet.tsx`); the drawing layer (`lib/drawings.ts`): levels and drawings (horizontal ray, trend line, rectangle zone, text note from the tool buttons beside Undo/Redo, magnet to OHLC) select by click or tap, drag, restyle from the selection bar (`components/charts/SelectionBar.tsx`), delete and undo/redo; right-click or a long press opens the chart menu (`components/charts/ChartMenu.tsx`): add a level or copy the price there, reset that chart's scale, Layers (hide levels, drawings, fills and studies on every chart; show hidden items), and on a level or drawing its label and color inline, lock, hide, duplicate and delete; the Layers button opens the layers panel (`components/charts/LayersPanel.tsx`, a bottom sheet on a phone): hide My levels, Drawings, Journal or Indicators on every chart, lock or delete all levels or drawings (one undo step), hide/lock/delete one item, or click it to bring the chart to it; Layers → Options levels shows option walls, ranked strikes and max pain with their filters, Layers → Expected move the option-implied levels; Indicators or Layers → VWAP bands independently shows VWAP ±1σ, and the dock's Strike ladder tab (`components/charts/OptionsLadder.tsx`) lists strikes around the price and marks one on the charts |
| Symbol info / You, News, Events, Forecast, Short | `/charts`, below the watchlist | `components/charts/SymbolInfo.tsx`, `components/charts/SymbolInfoYou.tsx`, `components/charts/SymbolInfoNews.tsx`, `components/charts/SymbolInfoEvents.tsx`, `components/charts/SymbolInfoForecast.tsx`, `lib/symbolInfo.ts`; `app/engine/symbol_info_reactions.py` | — | `GET /charts/symbol/{symbol}/you`: all-account completed-trade stats, open records and recent links; `GET /charts/symbol/{symbol}/events`: next earnings with confirmed/estimated status, the last eight reports, dividends and splits; `GET /charts/symbol/{symbol}/forecast?spot=`: T2.1 implied moves; `GET /charts/symbol/{symbol}/reactions`: T2.2 inferred earnings reactions from the latest eight confirmed reports, using completed split-adjusted Tradier daily bars; `GET /charts/symbol/{symbol}/news`: merged Alpaca (Benzinga) and Polygon headlines with per-source status and Polygon-supplied sentiment; `GET /charts/symbol/{symbol}/short`: T3.1 FINRA short interest, short volume and the hard-to-borrow flag; T1.3 Overview with the T3.3 Ownership section (13F from the overview payload; `GET /charts/symbol/{symbol}/insiders`: 90-day open-market insider buys and sells from Yahoo, unofficial, cached a day); device-local tab choice and collapsed phone panel; `tests/test_symbol_info.py`, `tests/test_symbol_info_reactions.py`, `tests/test_symbol_info_events.py`, `tests/test_symbol_info_news.py`, `tests/test_symbol_info_insiders.py`, `tests/test_options_feed.py`, `e2e/symbol-info.spec.ts` |
| Journal on the chart (trade card, position lines, historical mode) | `/charts`: hover or click a fill arrow; lines for open positions; **Open on chart** on a trade or fill page | `components/charts/TradeCard.tsx`, `lib/chartJournal.ts`, the arrows' hover and click in `components/charts/PriceChart.tsx`, the past-trade banner in `components/charts/ChartWorkspace.tsx`, `app/trades/[id]/page.tsx`, `app/fills/[id]/page.tsx` | — | `GET /charts/journal/fills/{id}`, `GET /charts/journal/trades/{id}` (`/mark` for an open option), `positions` in `GET /charts/workspace`; `tests/test_chart_journal.py`, `e2e/chart-journal.spec.ts` |
| Plans linked to trades | `/charts`: **Needs linking** on the saved-plan strip; the trade card and trade page show a linked plan | `components/charts/LinkReview.tsx`, `components/charts/PlanSummary.tsx`, `components/charts/PlanStrip.tsx`, `lib/captures.ts` | — | `/charts/captures/review`, `/link`, `/unlink`, `/tracking`, `/for-trade/{id}`; `tests/test_capture_links.py`, `e2e/chart-journal.spec.ts` |
| Pre-trade capture | `/charts`: **Plan trade** in the toolbar or Alt+P; the saved-plan strip above the charts; the gear in the sheet for templates and the default account | `components/charts/PlanSheet.tsx` (sheet, recorder, setup), `components/charts/PlanStrip.tsx`, `lib/captures.ts` (routes, outbox, image) | — | `/charts/captures` routes; template, Discretionary and voice plans with a frozen chart snapshot; `tests/test_captures.py`, `e2e/charts.spec.ts` |
| Practice decisions (A1) | `/`: Practice decisions section on Today | `app/engine/decisions.py`, `app/routers/decisions.py`, `components/PracticeDecisions.tsx`, `components/PracticeDecisionForm.tsx`, `lib/api.ts`; `DecisionRecord` and `DecisionContext` in `app/models.py` | `POST /decisions/context/{symbol}`, `/decisions` (create/list), `/decisions/{id}` | `tests/test_decisions.py`; immutable server-owned context, typed choices, and practice drafts/unarmed |
| Practice paper plans (A2) | Today page (`/`): a TAKE card under Practice decisions has an Arm paper plan button, the Practice paper timeline and base plus 3× costs outcome; `/?decision=<id>` opens that card | `app/engine/paper.py` (arming, watcher, phone outbox), `app/engine/paper_execution.py` (pure rules), `app/engine/level_alert_monitor.py` (runs the watcher); `DecisionEvent` in `app/models.py` | `POST /decisions/{id}/arm`, `GET /decisions/{id}/paper`; UI `frontend/components/PracticeDecisions.tsx`, `frontend/components/PracticePaperPlan.tsx`, `frontend/app/page.tsx`, `frontend/lib/api.ts` | `tests/test_paper_execution.py`, `tests/test_paper_plans.py`, `frontend/e2e/practice-decisions.spec.ts`; [live SPY phone, open-position restart and exit observation](practice-policy.md#a2-live-operational-observation-2026-10-08) recorded 2026-10-08; operational probe outside the on-time strategy cohort |
| Pre-trade check service | Jo's `/check/mcp` endpoint: `pre_trade_check`, `attach_model_verdict`, `review_checks`, `position_check`, `preopen_watchlist`, `get_notes`, `grade_checks`, `candles`, `shadow_setup`, `shadow_decide`; opt-in groups add the stock-alert, market-watch, conditional-plan and personal Jo tools below | `backend/cloud_mcp_check.py`, `backend/cloud_mcp_check_common.py`, `backend/cloud_mcp_check_ledger.py`, `backend/cloud_check_owner.py`, `app/engine/pretrade_check.py`, `backend/tradier_stock_data.py` (bounded Tradier full-market reads; no IEX fallback); installer `deploy/check_control.py` (including the separate `tradejournal-check-journal` reader socket) | OAuth MCP on the VPS; owner view on `/advisor-review` | `tests/test_pretrade_check.py`, `tests/test_cloud_mcp_check.py`, `tests/test_cloud_mcp_shadow.py`, `tests/test_cloud_check_owner.py`, `tests/test_check_deployment.py`, `tests/test_check_tool_schemas.py` (every tool's schema), `tests/test_tradier_jo_delivery.py`; [contract](advisor-pretrade-check-contract.md); activated October 12, 2026 |
| Saved advice → journal links (Dots step 5) | Trade detail page: saved checks for the trade, possible later activity, owner link/unlink | `app/engine/check_links.py`, `app/routers/check_links.py`; UI `frontend/components/TradeAdvice.tsx`, `frontend/lib/checkLinks.ts`; `alembic/versions/c7e2a9d4b1f8_add_check_links.py` | `GET /jo/check-links/for-trade/{trade_id}`, `/jo/check-links/{check_id}/activity`; `POST /jo/check-links/{check_id}/link`, `/jo/check-links/{check_id}/links/{link_id}/unlink` | `tests/test_check_links.py`, `frontend/e2e/check-links.spec.ts`; [contract](advisor-pretrade-check-contract.md#saved-advice-links-to-later-journal-activity--october-20-2026); journal reader enabled on the VPS October 20, 2026 (see the [Dots board](dots-integration.md#current-delivery-board)) |
| Jo's morning briefing and saved memories | `/morning` (compact card on the owner Dashboard), `/morning/memories` | `app/engine/jo_briefing.py`, `app/engine/jo_morning.py` (opt-in publisher/importer in the API process), `app/engine/jo_morning_market.py` (full-market evidence and market backdrop), `jo_briefing_common.py`, `jo_briefing_exchange.py`, `jo_briefing_tools.py` (Check tools `jo_morning_context`, `jo_context`, `jo_memory_propose`, `jo_briefing_submit`, `jo_receipt`), `jo_briefing_owner.py` (explicit owner commands); UI `frontend/components/dashboard/MorningBriefing.tsx`, `MemoryReview.tsx`, `frontend/lib/joMorning.ts` | `/jo/memories`, `/jo/packets`, `/jo/briefings` (and their redact routes), `GET /jo/morning`, `POST /jo/briefings/{id}/feedback` | `tests/test_jo_briefing.py`, `tests/test_jo_briefing_tools.py`, `tests/test_jo_morning.py`, `tests/test_jo_morning_market.py`, `frontend/e2e/morning-briefing.spec.ts`; [roadmap](dots-integration.md#personalized-morning-briefing-and-memory) |
| Jo's conditional price plans (price watches) | `/morning/watches` | `app/engine/conditional_plans.py` (monitor), `conditional_plan_common.py`, `conditional_plan_ledger.py`, `conditional_plan_tools.py` (Check tools `conditional_plan_create`, `_status`, `_list`, `_cancel`), `app/routers/conditional_plans.py`; UI `frontend/components/dashboard/PlanWatches.tsx`, `frontend/lib/conditionalPlans.ts`; Jo prompt `deploy/market-watch/jo-conditional-plans.md` | `GET /jo/conditional-plans` | `tests/test_conditional_plans.py`, `tests/test_conditional_plan_owner_view.py`, `frontend/e2e/price-watches.spec.ts`; [contract](setup-scanner-contract.md#conditional-price-plan-follow-through); app and Check opt-in, off by default |
| Jo's personal follow-ups (followup-v1) | none (saved in conversation with Jo; reviews run on the market-watch worker) | `followup_common.py`, `followup_ledger.py`, `followup_tools.py` (Check tools `followup_create`, `_list`, `_due`, `_review`, `_cancel`), `app/engine/followups.py` (periodic due reviews on the existing market-watch worker and outbox); Jo instructions `deploy/market-watch/jo-followups.md` | Check tools; ntfy through the market-watch outbox | `tests/test_followups.py`, `tests/test_check_tool_schemas.py`; [delivery board](dots-integration.md#personal-follow-through--october-23-2026); app `JO_FOLLOWUPS_ENABLED` and Check `followup_enabled`, both off by default |
| Isolated forecast study | Separate `/forecast/mcp`; operator CLI, no journal page | `cloud_mcp_forecast.py`, `scripts/advisor_forecast.py`, `advisor_forecast_runtime.py`, `advisor_forecast_exchange.py`; `deploy/advisor_forecast_prepare.py`, `advisor_forecast_upgrade.py` | Separate audience/scopes, frozen Tradier history/snapshot/deadline baseline/outcome; evaluation separately authorized | `tests/test_advisor_forecast.py`, `test_cloud_mcp_forecast.py`, `test_forecast_tradier.py`, `test_forecast_upgrade.py`; [contract](advisor-forecast-preparation.md) |
| Offline Jo decision audit | Operator CLI and private standalone reports | `backend/scripts/jo_decision_audit.py`, `backend/jo_decision_audit.py`, `jo_decision_audit_report.py` | Read-only named sample-run export or already-revealed comparison inputs; no provider/model calls or study activation | `tests/test_jo_decision_audit.py`; [contract](dot-historical-replay-contract.md#offline-jo-decision-auditor); underlying R is not an executable options return |
| Setup scanner S1 | `/scanner`: the day's setups, rules paper results and separate shadow TAKE/SKIP decisions/results, with previous/next day and day+cumulative scorecards | `app/engine/scanner_rules.py` (unchanged rules), `app/engine/setup_scanner.py` (scan, paper trades, exchange, day view), `app/engine/shadow_exchange.py` (isolated shadow ledger), `app/engine/level_alert_monitor.py` (runs it when `SETUP_SCANNER_ENABLED` is true), `app/engine/stock_watch.py` (selected-stock awareness, separate from option eligibility; `STOCK_WATCH_ENABLED`, off by default); `ScannerCandidate`, `ScannerEvent` in `app/models.py`; `alembic/versions/a7c3e9f1b2d4_add_setup_scanner_tables.py` | `GET /scanner/day`; UI `frontend/app/scanner/page.tsx`, `frontend/lib/api.ts` | `tests/test_setup_scanner.py`, `tests/test_stock_watch.py`; [contract](setup-scanner-contract.md); scanner and shadow exchange off by default; scanner enabled on the VPS October 12 and shadow exchange October 13, 2026 ([contract](setup-scanner-contract.md), [shadow S1](shadow-s1-contract.md#activation-evidence--october-13-2026)) |
| Jo's market watch (MW-1/MW-2) | Scheduled-read reliability screen at `/morning/market-reads` (`frontend/components/dashboard/MarketReads.tsx`, `frontend/lib/marketReads.ts`, `GET /jo/market-reads` from `app/routers/market_reads.py`); owner commands in `market_watch_owner.py` (snapshot, export, report) | `market_watch_common.py`, `market_watch_ledger.py` (check-ledger records, read notice), `app/engine/market_watch_snapshot.py`, `app/engine/market_watch_evaluation.py`, `market_watch_schedule.py` (#315 publisher), `app/engine/market_watch_wakes.py` (event detector, event wakes, ntfy messages, report; started from `app/main.py` when `MARKET_WATCH_ENABLED` is true); Jo prompts in `deploy/market-watch/` | Check tools `market_watch_snapshot`, `market_watch_submit` | `tests/test_market_watch_*.py` (including `test_market_watch_reliability.py`), `frontend/e2e/market-reads.spec.ts`; [design](market-watch-design.md#mw-2-implementation-and-activation-boundary); MW-2 event wakes/push off by default; `MARKET_WATCH_ENABLED=true` with store and outbox paths set in the VPS `backend.env` (read-only check October 20, 2026), live MW-2 wake/push behavior not verified |
| Jo's historical replay | Isolated demo only: Jo's sequential TAKE/WAIT/SKIP cards over past sessions | `app/engine/scanner_replay.py`, `scanner_replay_market.py`, `scanner_replay_report.py` (frozen scanner setups on past sessions), `app/engine/historical_replay.py`, `app/engine/opportunity_replay.py` (#329 frozen opportunity pilots); operator scripts `scripts/scanner_replay_*.py`, `scripts/opportunity_replay_export.py` | Isolated demo check tools | `tests/test_scanner_replay*.py`, `tests/test_historical_replay.py`, `tests/test_opportunity_replay.py`; [contract](dot-historical-replay-contract.md); not activated: merging does not rebind the isolated demo |
| Level alerts | `/charts`: right-click (long-press) a level, horizontal ray or automatic level; the Alerts list in the dock | `components/charts/AlertsPanel.tsx`, `components/charts/ChartMenu.tsx`, `lib/alerts.ts` (bells: `AlertLayer`) | — | `GET`/`POST /charts/alerts`, `POST /charts/alerts/{id}/rearm`, `DELETE /charts/alerts/{id}`, and `alerts` in `GET /charts/workspace`; touches, crosses, closes beyond; judged and sent to the phone by the API with no tab open; `tests/test_level_alerts.py`, `e2e/charts.spec.ts` |
| Daily Review | `/daily` (a month calendar: each trade day tinted by `closed_pnl`, the realized P&L of what closed that day, with a dot once reviewed; for the owner, the newest two months mark each weekday with Jo's status from `GET /jo/morning?month=`, `GET /jo/market-reads?month=` and `GET /jo/conditional-plans`, and no mark where there is no Jo record) → `/daily/{YYYY-MM-DD}` (pinned section menu; owner-only Jo's day timeline first: done, watching now and coming up from the existing briefing, market reads with Jo's text, price watches and scanner decisions, then every phone push recorded that day (watch alerts, Jo's read messages, watchdog notices) with its outcome; the dashboard's Today's Session card links to it) | `app/daily/page.tsx`, `app/daily/[day]/page.tsx`, `components/JoDay.tsx`, `components/dashboard/JoTodayLine.tsx`, `frontend/e2e/jo-day.spec.ts` | `GET /daily-review` (`closed_pnl` per day, `tests/test_daily_review_index.py`); per day `/daily-review/{day}`, `/trades`, `/trades/{id}/fills`, `/market-context/fills/bulk`, `/accounts`, quotes | `DailyAiPanel`: `POST /daily-review` |
| Trades | `/trades` → `/trades/{id}` | `app/trades/page.tsx`, `app/trades/[id]/page.tsx`, `components/TradesTable.tsx` | list: `GET /trades?status=&ticker=&account=&type=`, `/accounts`. Detail (client page): `/trades/{id}`, `/trades/{id}/fills`, `/market-context/fills/bulk`, `/market-context/trade/{id}` | `AuditPanel`: `GET /market-context/audit/{id}`; review button: `POST /trades/{id}/review` |
| Analytics | `/analytics` | `app/analytics/page.tsx`, `components/AnalyticsExplorer.tsx` | `GET /stats/analytics`, `/accounts`; pure metrics in `app/engine/analytics.py`; [definitions and proof](../analytics.md) | local grouping/sorting/drill-down, links to trade details |
| Fills | `/fills` → `/fills/{id}` | `app/fills/page.tsx`, `app/fills/[id]/page.tsx` | `GET /fills`, `/accounts`; edit: `/fills/{id}` | `ManualFillForm`: `POST /fills`, `PUT /fills/{id}` |
| Strategy Lab | `/strategy-lab` → `/strategies/{id}`, `/strategies/{id}/versions/new`, `/versions/{id}`, `/versions/{id}/import`, `/runs/{id}` | `app/strategy-lab/**`, `components/strategy-lab/`, `lib/strategy-lab/api.ts` | `GET /strategy-lab/strategies`, `/strategies/{id}`, `/versions/{id}`, `/runs`, `/runs/{id}`, `/runs/{id}/trades`, `/runs/{id}/metrics` | forms and wizard: `POST /strategy-lab/strategies`, `/strategies/{id}/versions`, `/versions/{id}/fork`, `/imports/preview`, `/runs/import`, `/runs/{id}/metrics/recalculate`; `PATCH /strategies/{id}`, `/versions/{id}` |
| AI Buildout | `/research/ai-buildout` | `app/research/ai-buildout/page.tsx`, `components/research/`, `lib/research/` | — | `GET`/`PUT /research/workspaces/{slug}` |
| Sync (drawer) | any page | `components/StatusPanel.tsx` | — | polls `GET /fills/enrich/status`, `/market-context/enrich/status`, `/market-context/trade-path/status`, `/market-context/coverage` |

Things worth knowing before you touch a page:

- Pages under `app/` are server components that call the API from the Next
  server through the session-aware `lib/serverApi.ts` (shared types/client helpers in `lib/api.ts`) (`NEXT_PUBLIC_API_URL`, default
  `http://localhost:8080`), except `/trades/{id}`, which is a client page.
  Client components may fetch from the browser; AnalyticsExplorer instead
  receives server-calculated metrics and trade rows as page props, so changing
  its grouping, sorting or drill-down does not fetch per-trade data.
- Row links go to `/trades/{id}` from the dashboard tables, the trades table
  and the daily review; the daily review also links each fill to
  `/fills/{id}?returnTo=`. The trade detail page links nowhere.
- The Sync Center's job types (`JOB_CONFIG` in `app/routers/sync.py`) are
  `gmail_sync`, `fill_import_check`, `trade_rebuild`, `polygon_enrich`,
  `alpaca_enrich`, `trade_path` and `gmail_push` (`daily_review` is retired:
  the opt-in nightly plan timer and the Daily Review button write reviews);
  `full_pipeline` and `resync_all` (`_EXTRA_JOB_CONFIG`) are the run types
  behind the pipeline button and the advanced resync, and
  `gmail_watch_renew` and `gmail_listener` are the run types the Gmail
  listener creates. `POST
  /sync/pipeline/run` (`_run_pipeline`) runs six
  stages: Gmail sync, fill check, trade rebuild (only when new fills arrived),
  then Polygon, Alpaca and trade-path enrichment over everything missing,
  including rows whose fields are still empty (`domain-rules.md`).
  Daily review is deliberately not one of them. Status endpoints read
  `job_run` rows, never process memory (`architecture.md`).
- `/accounts` (`app/accounts/page.tsx`) is a static placeholder: not in the
  sidebar, calls nothing, renders "No accounts yet."
- `/privacy` (`app/privacy/page.tsx`) is static and not in the sidebar. The
  Google OAuth consent screen links to it; keep it true to what the Gmail
  integration does.
- Phone layout: below `md` the sidebar in `components/Nav.tsx` is replaced by a
  tab bar fixed at the bottom (Dashboard, Charts, Daily Review, Trades, and More,
  which opens the slide-out menu with every `navItems` page and the Sync
  drawer) and a slim title bar, hidden on `/charts` so the chart starts
  higher; `AppMain` pads pages above the tab bar. On `/charts` a phone keeps
  the drawing tools and Undo/Redo behind a **Draw** button and the one/five
  charts switch in the toolbar's More menu. Below `sm` tables mark
  secondary columns `wide` so only a few show -- `TradesTable`,
  `DashboardTables`, `app/fills/page.tsx`. A row still opens the full record.
  `app/manifest.ts` plus `public/icon-*.png` (regenerate with
  `frontend/scripts/generate-icons.py`) make the home-screen shortcut open like
  an app. Proof: `e2e/phone.spec.ts`.

## Backend by feature

Each row names where the logic lives, the routes that reach it, and the test
that is the first place to look for evidence. "—" under proof means the path
is only covered where its network call is stubbed, or not at all; say so when
you change it (`verification.md`, "What is NOT covered yet").

| Working on | Start at | Routes | Proof |
|---|---|---|---|
| Charts workspace | `app/engine/chart_feed.py`, `app/engine/chart_history.py`, `app/engine/chart_calendar.py`, `app/engine/chart_splits.py`, `app/engine/chart_adjust.py`, `app/engine/chart_daily.py`, `app/engine/chart_stream.py`, `app/engine/chart_math.py`, `app/routers/charts.py`; `frontend/components/charts/`, `frontend/lib/charts.ts`, `frontend/lib/chartStore.ts`, `frontend/lib/chartSync.ts`, `frontend/lib/drawings.ts` | private `GET /charts/workspace`, `/charts/history`, `/charts/stream`, `GET`/`PUT /charts/settings`; `/charts` page | `tests/test_charts.py`, `tests/test_chart_history.py`, `tests/test_chart_calendar.py`, `tests/test_chart_splits.py`, `tests/test_chart_daily_history.py`, `tests/test_chart_stream.py`, `tests/test_chart_timing.py` (opt-in `timing=true` `Server-Timing` via `app/engine/chart_timing.py`), `frontend/e2e/charts.spec.ts`; live access probes `scripts/check_chart_feed.py`, `scripts/check_chart_splits.py` and a read-only SIP session request; [provider decision and boundaries](../charts-workspace.md) |
| Charts holding context | `frontend/components/charts/HoldingContext.tsx`, `frontend/lib/chartJournal.ts` | Existing workspace positions and selected `GET /charts/journal/trades/{id}`; owner Overview disclosure; no writes or marks | `frontend/e2e/chart-journal.spec.ts`; [holding context](../charts-workspace.md#holding-context-read-only) |
| Symbol info / You (T1.1) | `app/routers/symbol_info.py`, `app/engine/symbol_info_journal.py` (two read-only queries), `app/engine/symbol_info.py` (pure summary); `frontend/components/charts/SymbolInfo.tsx`, `frontend/components/charts/SymbolInfoYou.tsx` | private `GET /charts/symbol/{symbol}/you`; `/charts` side column | `tests/test_symbol_info.py`, `frontend/e2e/symbol-info.spec.ts`; [panel behavior](../charts-workspace.md#symbol-info-panel) |
| Chart news markers (T3.5) | `frontend/lib/newsMarkers.ts` (candle alignment: pure), `frontend/lib/newsFeed.ts` (the one news read the News tab and the layer share), `frontend/components/charts/PriceChart.tsx` (series markers, hover headlines, click, touch popover), `ChartWorkspace.tsx` (the `newsHidden` layer, click-through to the dock), `SymbolInfo.tsx` / `SymbolInfoNews.tsx` (opens on and lights the clicked articles) | the private news endpoint above, unchanged; `/charts` main chart, Layers → News markers | `frontend/e2e/news-markers.spec.ts` (alignment unit tests and stubbed browser tests); [behavior](../charts-workspace.md#symbol-info-panel) |
| Symbol info / News (T1.2) | `app/engine/symbol_info_news.py` (pure normalizers, merge, dedupe, Focused flag), `app/engine/symbol_info_news_feed.py` (Alpaca 60 s memory cache, Polygon 15 min disk cache, limiter, 429 fallback); `app/routers/symbol_info.py`; `frontend/components/charts/SymbolInfoNews.tsx` | private `GET /charts/symbol/{symbol}/news`; `/charts` side column, News tab | `tests/test_symbol_info_news.py`, `frontend/e2e/symbol-info.spec.ts`; [panel behavior](../charts-workspace.md#symbol-info-panel) |
| Symbol info / Peers strip (T3.4) | `app/engine/symbol_info_peers.py` (pure: related tickers, chips, hand-picked groups from `app/data/peer_groups.json`, peer valuation medians), `app/engine/symbol_info_peers_feed.py` (Polygon 7-day disk cache, limiter, 429 fallback; one batched Tradier quote call via the chart feed; one batched ratios read via `symbol_info_tradier.peer_ratios`); `app/routers/symbol_info.py`; `frontend/components/charts/SymbolInfoPeers.tsx` | private `GET /charts/symbol/{symbol}/peers`; `/charts` side column, last block of the Overview tab | `tests/test_symbol_info_peers.py` (recorded Polygon and Tradier fixtures), `frontend/e2e/symbol-info-peers.spec.ts`; [panel behavior](../charts-workspace.md#symbol-info-panel) |
| Symbol info / Financials (T3.2) | `app/engine/symbol_info_financials.py` (pure: quarter selection by 80-105 day span, comparatives, calculated margins, year-over-year, Q4 gaps), `app/engine/symbol_info_financials_feed.py` (SEC EDGAR reads, `SEC_USER_AGENT`, ticker map and normalized-only disk cache, pacing, failure fallback); `app/routers/symbol_info.py`; `frontend/components/charts/SymbolInfoFinancials.tsx` | private `GET /charts/symbol/{symbol}/financials`; `/charts` side column, Financials tab | `tests/test_symbol_info_financials.py` (recorded NVDA and NBIS companyfacts in `tests/fixtures/sec/`), `frontend/e2e/symbol-info.spec.ts`; [panel behavior](../charts-workspace.md#symbol-info-panel) |
| Symbol info / Short (T3.1) | `app/engine/symbol_info_short.py` (pure normalizers and view), `app/engine/symbol_info_short_feed.py` (Polygon short interest, short volume and ticker details plus Tradier easy-to-borrow list, one-day disk caches, limiter, 429 fallback); `app/routers/symbol_info.py`; `frontend/components/charts/SymbolInfoShort.tsx` | private `GET /charts/symbol/{symbol}/short`; `/charts` side column, Short tab | `tests/test_symbol_info_short.py` (recorded fixtures in `tests/fixtures/symbol_info_short/`), `frontend/e2e/symbol-info.spec.ts`; [panel behavior](../charts-workspace.md#symbol-info-panel) |
| Symbol info / Events (T1.4) and chart earnings (C2.5) | `app/engine/symbol_info_tradier.py` (Tradier fundamentals: budget, cache, background refresh), `app/engine/symbol_info_events.py` (pure normalizers); `app/routers/symbol_info.py`, `app/routers/charts.py` (`earnings` in the workspace); `frontend/components/charts/SymbolInfoEvents.tsx`, `frontend/components/charts/EarningsBadge.tsx`, `earningsMarks` in `frontend/lib/charts.ts` | private `GET /charts/symbol/{symbol}/events`, `GET /charts/workspace`; `/charts` side column and chart headers | `tests/test_symbol_info_events.py`, `frontend/e2e/symbol-info.spec.ts`, `frontend/e2e/charts.spec.ts`; [earnings](../charts-workspace.md#earnings-c25) |
| Pre-trade capture (Charts C3.4, C3.5) | `app/engine/captures.py` (rules, private file storage, idempotent saves, transcription job), `app/engine/transcribe.py` (Whisper on the server), `app/routers/captures.py`; `TradeCapture`, `TradeCaptureNote`, `CaptureTemplate`, `CaptureProfile` in `app/models.py`; `alembic/versions/c3a4d5e6f7b8_add_trade_captures.py`; the `capture` lane in `app/engine/job_runtime.py`, `deploy/launch.py`, `deploy/control.py` | private `/charts/captures` routes; files under `CAPTURE_STORAGE_DIR` | `tests/test_captures.py`, `tests/test_deployment.py`, `frontend/e2e/charts.spec.ts`; [behavior](../charts-workspace.md#pre-trade-capture-c34-c35) |
| Journal on the chart (Charts C3.1–C3.3) | `app/engine/chart_journal.py` (read-only: cards, first-in-first-out open lots, positions; units and metric states), the `journal` routes and `positions` in `app/routers/charts.py`, `option_mark` in `app/engine/quotes.py`; `frontend/lib/chartJournal.ts`, `frontend/components/charts/TradeCard.tsx` | private `GET /charts/journal/fills/{id}`, `/charts/journal/trades/{id}`, `/charts/journal/trades/{id}/mark`; `/charts?symbol=…&from=…&to=…` | `tests/test_chart_journal.py`, `frontend/e2e/chart-journal.spec.ts`; [behavior](../charts-workspace.md#journal-on-the-chart-c31c33) |
| Capture links and coverage (Charts C3.6) | `app/engine/capture_links.py` (suggestions, links anchored in source fills, timing, coverage), routes in `app/routers/captures.py`; `CaptureLink` and the tracking fields on `CaptureProfile` in `app/models.py`; `alembic/versions/b5d7e9f1a3c6_add_capture_links.py` | private `/charts/captures/review`, `/charts/captures/{id}/link`, `/unlink`, `/charts/captures/tracking`, `/charts/captures/for-trade/{id}` | `tests/test_capture_links.py`, `frontend/e2e/chart-journal.spec.ts`; [behavior](../charts-workspace.md#plans-linked-to-trades-c36) |
| Level alerts (Charts C5.1) | `app/engine/level_alerts.py` (pure: when one fires, the message), `app/engine/level_alert_monitor.py` (record once, outbox delivery, 1-minute sweep), `app/engine/chart_stream.py` (alert symbols, coverage, `on_tick`), `app/engine/ntfy.py`, `app/routers/level_alerts.py`; `LevelAlert`, `LevelAlertEvent` in `app/models.py`; `alembic/versions/8d4f6a2c9e17_add_level_alerts.py`; `deploy/systemd/tradejournal-api.service` reads `alerts.env` | private `/charts/alerts` routes, `alerts` in `GET /charts/workspace`; ntfy | `tests/test_level_alerts.py`, `tests/test_deployment.py`, `frontend/e2e/charts.spec.ts`; [behavior and delivery](../charts-workspace.md#level-alerts-c51) |
| Open-trade phone alerts | `app/engine/position_alerts.py` (give-back after +10% and +$50 falls to +3%, at the Tradier bid/ask midpoint; only the explicitly configured account's SPY/QQQ options skip the $50 floor; last-day alerts 90 and 30 minutes before the close; one re-decide alert 60 regular-session minutes after a same-day first entry, only with `POSITION_HOLD_ALERTS=true` as well; at-most-once ntfy outbox; optional frozen since-entry Radar context via `app/engine/position_alert_context.py` and shared `app/engine/radar_entry.py`, no new triggers), run by `app/engine/level_alert_monitor.py` when `POSITION_ALERTS_ENABLED=true` (off by default); `app/routers/position_alerts.py`; `PositionWatch`, `PositionAlert` in `app/models.py`; `alembic/versions/a3d8f6c2e9b1_add_position_alerts.py`; trade page section `frontend/components/TradePhoneAlerts.tsx` selects the saved event from `/trades/{id}?alert={event_id}`, above the summary, with historical quote/time, a separate current "Now" quote and open P&L for an open position (`GET /charts/journal/trades/{id}/mark`, refreshable, stale after 5 minutes) and underlying-chart link; the linked pre-trade plan follows the alert instead of the summary. Position pushes set both the ntfy tap URL and Open app action when `ALERT_APP_URL` is configured; other senders retain their existing tap behavior. Missing events are explicit; sent means ntfy acceptance, not observed phone display. | `GET /trades/{id}/phone-alerts`; Tradier quotes; ntfy | `tests/test_position_alerts.py`, `tests/test_position_alert_context.py`, `tests/test_radar_entry.py`, `tests/test_ntfy_transport.py`, `frontend/e2e/trade-phone-alerts.spec.ts`, `frontend/e2e/browser-access.auth.ts` (fresh owner session preserves event URL); activation settings and account UUID verification: [phone alerts](../../deploy/README.md#phone-alerts); why: [behavior audit](../../backend/reports/behavior_audit_2026-10-21.md) |
| Unplanned-entry plan nudge | `app/engine/plan_nudges.py`: one ntfy ping per new Robinhood position (Webull left out) whose first entry fill is `PLAN_NUDGE_GRACE_MINUTES` (default 3) old with no plan linked (`capture_links.for_trade`) or suggested by an unlinked plan from the last day (`capture_links.suggestions`); tapping opens `/copilot-lab?symbol=…&context=Plan this position: …` to plan it. Regular session only, entries since the process started only, anchored like position alerts (a rebuild never re-sends), at most `PLAN_NUDGE_DAILY_CAP` (default 5) a day (the rest are recorded `skipped`), same at-most-once outbox and 15-minute expiry. Run by `app/engine/level_alert_monitor.py` beside position alerts when `PLAN_NUDGE_ENABLED=true` (off by default, not activated on the VPS); `PlanNudge` in `app/models.py`; `alembic/versions/b2c9e4f7a1d3_add_plan_nudge.py`; listed with `kind: plan_nudge` in the trade page's phone alerts. | `GET /trades/{id}/phone-alerts`; ntfy | `tests/test_plan_nudges.py`, `frontend/e2e/trade-phone-alerts.spec.ts` |
| Exit habits (dashboard) | `app/engine/exit_habits.py` (read-only: each sent or `unknown` phone alert matched to its position by source identity, the response within 15 minutes / later / overnight / expired / still open, and the result vs. the alert's midpoint; the audit's four exit habits for the latest 30 closed long options since 2026-10-21 against every trade before it, with trades missing data left out and counted); `app/routers/exit_habits.py`; dashboard card `frontend/components/dashboard/ExitHabits.tsx` (each alert row opens its own event, `/trades/{id}?alert={event_id}`) | `GET /analytics/exit-habits` (owner only; the proxy and the access manifest deny assistants) | `tests/test_exit_habits.py`, `frontend/e2e/dashboard.spec.ts` (seeded by `/__test/exit-habits-seed`); definitions from the [behavior audit](../../backend/reports/behavior_audit_2026-10-21.md) |
| Radar recorder, rules, feed API, screen and news | `app/data/radar_universe.json` (versioned tracked list and curated groups), `app/engine/radar_store.py` (isolated append-only SQLite: passes, quotes, event/revision shape, append-only visits, feedback and `event_news` checks), `app/engine/radar_runner.py` (one Tradier pass a minute in regular hours, batches of 50, cap 6, then detection), `app/engine/radar_rules.py` (provisional `radar-rules-v0`: stock vs SPY/sector and group moves over 30 min, revisions; replay with `scripts/radar_replay.py`), `app/engine/radar_news.py` (after each pass: headlines near events under 2 h old, first check then one recheck 15 min later, at most 3 requests a pass, through `app.engine.news` with the morning brief's `eligible_headlines`/`catalyst_first`), started from `app/main.py` when `RADAR_ENABLED=true` with an absolute `RADAR_STORE` (off by default); `app/routers/radar.py` (owner-only feed, event detail, visits, feedback, read-only group comparison via `app/engine/radar_comparison.py`, and the plain "Movers now" ranking `GET /radar/movers` via `app/engine/radar_movers.py`), `app/engine/radar_premarket.py` (record-only premarket mover pilot inside the recorder, its own file, off unless `RADAR_PREMARKET_ENABLED=true`; scored by `scripts/radar_premarket_eval.py`), `frontend/app/radar/page.tsx` with `components/RadarFeedView.tsx` and `lib/radar.ts` | Tradier quotes; Alpaca/Benzinga news for event symbols only; the Radar SQLite file | `tests/test_radar_store.py`, `tests/test_radar_rules.py`, `tests/test_radar_runner.py`, `tests/test_radar_api.py`, `tests/test_radar_comparison.py`, `tests/test_radar_movers.py`, `tests/test_radar_news.py`, `tests/test_radar_premarket.py`, `frontend/e2e/radar.spec.ts`, sample event `tests/fixtures/radar/sample_event.json`; [plan](../radar.md) |
| Copilot Lab (owner-only experiment, off unless `COPILOT_ENABLED=true`; in the nav only while on) | `app/ai/copilot.py` (bounded turn loop; `fake`, `anthropic` Messages API and `plan` Agent SDK backends, the last in `app/ai/copilot_plan.py`), `app/ai/copilot_tools.py` (thirteen read-only tools (including `get_investigation_changes`, `get_owner_context` and `get_trade_review`) and `propose_plan` (watch, revisit, memory or trade plan), which writes nothing; a confirmed memory goes through `POST /jo/memories`, a confirmed trade plan through `POST /charts/captures` plus two `POST /charts/alerts`, from `components/copilot/TradePlanCard.tsx`), `app/ai/copilot_book.py` (the chart and book tools: `get_chart_context` over `chart_feed.workspace`, `get_positions` over `chart_journal.positions` and the quote engine, `get_trades`, and `get_memories` over `jo_briefing.memories`, read-only; no account identifiers; never given to research jobs), `app/ai/copilot_context.py` (the owner context pack prepended to every turn: positions with give-back watch, alerts and captured plan, symbol history, exit habits, memories, today's notes, saved investigations and armed watches, labelled owner said / measured / saved; with no symbol, the open investigations, armed alerts and waiting research jobs across every symbol, which `GET /copilot/threads` serves to the lab's Open threads home), `app/ai/copilot_review.py` (`get_trade_review`: one closed trade with its path, captured plan, phone alerts and what followed, exit-habit flags and the symbol's other closed trades; reached from the trade page's "Review with copilot"), `app/ai/copilot_fixture.py` (simulated data), `app/ai/copilot_replay.py` (local-only frozen-clock replay), `app/engine/copilot_investigations.py` with `CopilotInvestigation` in `app/models.py` (saved investigations and research results), `app/ai/research_job.py` and `scripts/run_research_job.py` (manual research job); `frontend/app/copilot-lab/page.tsx` with `components/copilot/CopilotLab.tsx` (Open threads and "What matters right now?" above an empty conversation; the page variant of `components/copilot/CopilotPanel.tsx`, which is also the Charts dock's Copilot tab and Radar's drawer), `components/copilot/PlanATrade.tsx` (the "Plan a trade" entry on Charts, Radar, the Dashboard, the phone tab bar and the plan sheet) and `lib/copilot.ts` | `GET /copilot/status`, `GET /copilot/quote`, `GET /copilot/threads`, `POST /copilot/chat`, `GET`/`POST /copilot/investigations`, `GET`/`PUT /copilot/investigations/{investigation_id}`, `POST /copilot/research-jobs/reassess` | `tests/test_copilot.py`, `tests/test_copilot_book.py`, `tests/test_copilot_context.py`, `tests/test_copilot_review.py`, `tests/test_copilot_plan.py`, `tests/test_research_job.py`, `tests/test_research_queue.py`, `frontend/e2e/copilot-entry.spec.ts`, `frontend/e2e/copilot-home.spec.ts`, `frontend/e2e/copilot-plan.spec.ts`, `frontend/e2e/copilot-trade-plan.spec.ts`, `frontend/e2e/copilot-changes.spec.ts`, `frontend/e2e/copilot-panel.spec.ts`, `frontend/e2e/copilot-review.spec.ts`, `frontend/e2e/plan-a-trade.spec.ts`; live API runs are recorded in [the lab doc](../copilot-lab.md) |
| Options snapshots (Charts C4.3) | `app/engine/options_recorder.py`; `OptionChainSnapshot` and `OptionSnapshotDay` in `app/models.py`; `alembic/versions/5e8b2d7c4a19_add_option_snapshots.py`; `deploy/systemd/tradejournal-options-snapshot.timer` and its service | Sync Center → Options positioning snapshot (`POST /sync/jobs/options_snapshot/run`); weekday timer at 16:20 and 19:20 New York | `tests/test_options_recorder.py`, `tests/test_deployment.py`; [contract](../charts-workspace.md#options-snapshots-c43) |
| Relative volume (Charts C2.4, C2.6) | `app/engine/chart_rvol.py` (pure: per-minute profiles, the 20-session baseline and its states in `day_baseline`, each candle's RVol, equal to `compute_rvol_time_adjusted`), `ChartFeed._rvol` in `app/engine/chart_feed.py`, `ChartHistory.volume_profile`, `._past_rvol` (older sessions on history pages) and `.session` in `app/engine/chart_history.py`; `app/engine/rvol_history.py` (the morning job); `deploy/systemd/tradejournal-rvol-history.timer` and its service; `volumeAlpha`/`rvolCoverage` in `frontend/lib/charts.ts`, the legend in `frontend/components/charts/PriceChart.tsx` | `/charts`: today's volume bars brighten with RVol; the main chart's study row reads the candle's RVol and the baseline's sessions; `rvol` and each candle's `rvol` in `GET /charts/workspace` (today) and `GET /charts/history` (older sessions, `rvol` by date); Sync Center → Relative volume history (`POST /sync/jobs/rvol_history/run`); weekday timer at 06:00 and 08:40 New York | `tests/test_chart_rvol.py`, `tests/test_rvol_history.py`, `tests/test_deployment.py`, `frontend/e2e/charts.spec.ts` (relative volume); [definitions](../charts-workspace.md#relative-volume-c24) |
| Automatic chart levels (Charts C2.1–C2.3) | `app/engine/chart_levels.py` (pure: prior day/week, premarket, overnight, opening ranges, swings, round numbers from supplied bars, calling the fill-context functions in `app/engine/indicators.py`; confluence zones; tested/broken/reclaimed), `ChartFeed._levels` in `app/engine/chart_feed.py`; `frontend/lib/autoLevels.ts` (the layer behind the candles), `frontend/components/charts/LevelCard.tsx` | `/charts`: the nearest three zones each side on every chart; hover or tap one for its card; Layers → Auto levels hides them; `auto_levels` and each panel's `level_events` in `GET /charts/workspace` | `tests/test_chart_levels.py`, `tests/test_charts.py`, `frontend/e2e/charts.spec.ts` (automatic levels); [definitions](../charts-workspace.md#automatic-levels-c21) |
| Option chain adapter (Charts C4.1) | `app/engine/options_chain.py` (Tradier requests, parsing, 30/minute budget), `app/engine/options_models.py` (pure normalized models) | called by the C4.3 recorder and the chart's option feed below | `tests/test_options_chain.py`; live probe `scripts/check_options_chain.py`; [contract](../charts-workspace.md#option-chains-c41) |
| Options positioning, levels and ladder (Charts C4.2, C4.4, C4.5, max pain C4.7), the range bands (Charts C2.7) and the implied move (symbol info T2.1) | `app/engine/options_positioning.py` (pure: per-strike open interest and volume, walls, ranks, Black-Scholes dollar gamma, signed gamma and the flip, max pain, chart levels, scopes), `app/engine/options_implied.py` (pure: the at-the-money straddle and the expected-move levels), `app/engine/options_feed.py` (chain cache, cadence, background refresh, the 24-a-minute share, the once-a-session expected-move capture), `app/engine/chart_math.py` (`vwap_sd`), `ChartFeed._levels` in `app/engine/chart_feed.py` (strikes join the automatic levels before confluence); `frontend/lib/autoLevels.ts` (`shownZones`, tints, the strike highlight), `frontend/lib/optionsView.ts`, `frontend/components/charts/LevelCard.tsx`, `frontend/components/charts/OptionsLadder.tsx`, `frontend/components/charts/LayersPanel.tsx` (filters), `frontend/components/charts/SymbolInfoForecast.tsx` | `options=`, `ranges=` and `auto=` on private `GET /charts/workspace`; `GET /charts/options/{symbol}/ladder`; `GET /charts/symbol/{symbol}/forecast`; `/charts`: Layers → Options levels, Expected move and VWAP bands, the Strike ladder dock tab, the Forecast tab | `tests/test_options_positioning.py`, `tests/test_options_feed.py`, `tests/test_charts.py`, `tests/test_symbol_info.py`, `frontend/e2e/charts.spec.ts` (options levels, strike ladder, range bands, max pain), `frontend/e2e/symbol-info.spec.ts` (Forecast); [definitions and assumptions](../charts-workspace.md#options-positioning-c42) |
| Background job ownership and recovery | `app/engine/job_runtime.py`, `app/jobs/worker.py`; commands in [background-jobs.md](background-jobs.md) | Sync Center, Gmail push, enrichment and Webull start routes | `tests/test_job_runtime.py` (competing processes, API restarts, worker death, queue consumption and fill dedupe/FIFO); external providers stubbed |
| PnL, FIFO, trade shape | `app/engine/reconstructor.py` | `POST /rebuild`; runs after every fill write and in `trade_rebuild` | `tests/test_reconstructor.py`; `test_seed_dev_data.py` (`EXPECTED`); `test_seed_snapshot.py` (golden snapshot over the seed) |
| Robinhood email parsing | `app/engine/email_parser.py` | — | `test_email_parser.py` |
| Gmail fetch and import | `app/engine/gmail_poller.py`, `app/routers/fills.py` | `POST /fills/import`, `POST /fills/resync-all` (destructive, needs `confirm`) | `test_gmail_poller.py`, `test_fill_import.py`, `test_environment_guard.py` |
| Gmail OAuth | `app/routers/auth.py` | `GET /auth/gmail/start`, `/auth/gmail/start/browser`, `/auth/gmail/callback` | `test_gmail_auth.py`, `test_cors.py` |
| Real-time Gmail import (Pub/Sub pull) | `app/engine/gmail_listener.py` (lane `gmail`), history cursor in `app/engine/gmail_poller.py`, `_import_gmail_changes` and `queue_gmail_push_pipeline` in `app/routers/sync.py`; setup in [deploy/README.md](../../deploy/README.md#real-time-gmail-import) | jobs `gmail_listener`, `gmail_push`, `gmail_watch_renew`; `POST /gmail/watch`, `GET /gmail/watch/status`, `POST /gmail/push` (same coalesced queue; nothing public calls it) | `test_gmail_listener.py` (fake subscriber), `test_gmail_realtime.py` (cursor, targeted fetch, coalescing) |
| Phone alerts (ntfy) | `deploy/alerts.py`, `deploy/systemd/tradejournal-alerts.*`; setup in [deploy/README.md](../../deploy/README.md#phone-alerts) | reads `GET /health`, `/gmail/health`, `/sync/runs`, opt-in `GET /jo/morning`, `systemctl show` and disk use of `/`, PostgreSQL and the backups (80% after a 30-minute grace, 90% at once) | `test_deployment.py` (grace periods, one alert per problem, recovery, merged pipeline failures, reboot, disk thresholds); the deployment workflow runs the real unit against a loopback ntfy stand-in; live ntfy delivery is not tested |
| Gmail status banner and live refresh | `app/engine/gmail_health.py`; `components/GmailStatusBanner.tsx`, `lib/useGmailHealth.ts`, status line in `components/Nav.tsx` | `GET /gmail/health` (polled every 30s while visible; `data_version` drives `router.refresh()`) | `test_gmail_realtime.py` (health states); rendering is not in the browser suite |
| Polygon enrichment, greeks, indicators | `app/engine/enricher.py`, `app/engine/indicators.py` | `POST /fills/enrich?range=`, `GET /fills/enrich/status`; job `polygon_enrich` | `test_enricher.py` (incl. the discovered rate limit), `test_indicators_rvol.py`, `test_enrichment_gap_repair.py` (which empty fields are retried) |
| Alpaca fill context | `app/engine/alpaca.py`, `app/engine/alpaca_enricher.py`, `app/engine/behavior.py` (sequence metrics) | `POST /market-context/enrich?range=&force=`, `GET /market-context/enrich/status`, `/market-context/fill/{id}`, `/market-context/fills/bulk?ids=`, `/market-context/coverage`; job `alpaca_enrich` | `test_alpaca_context_repair.py`, `test_indicators_rvol.py` (the RVOL history prefetch and the injected cache-only bar loader) |
| Trade path metrics (MFE, MAE, exit efficiency) | `app/engine/trade_path.py` | `POST /market-context/trade-path/compute`, `GET /market-context/trade-path/status`, `/market-context/trade/{id}`, `/market-context/trade-path/bulk?ids=`; job `trade_path` | `test_enrichment_gap_repair.py` (row selection, keep-existing merge); live Alpaca fetch untested, `test_seed_snapshot.py` stubs it |
| Trade audit | `app/engine/auditor.py`, `app/engine/metric_reference.py`, `app/engine/metric_validation.py` | `GET /market-context/audit/{trade_id}`; offline `scripts/validate_trade_metrics.py` emits JSON/Markdown/HTML | `test_seed_snapshot.py` (cache emptied), `tests/test_metric_reference.py`, `frontend/e2e/trade-metric-quality.spec.ts` |
| Journal data audit (D0) | `scripts/audit_journal_data.py` (read-only; writes a local report, never the database) | offline only: `--sqlite <journal.db> --output-dir backend/data/d0/...`; [contract and how to run it](../d0-data-audit.md) | `tests/test_d0_data_audit.py` |
| Durable jobs, Sync Center | `app/engine/jobs.py`, `app/jobs/run.py`, `app/routers/sync.py`; `app/engine/api_wait.py` (per-job pacing and backoff telemetry) | `GET /sync/summary`, `/sync/jobs`, `/sync/runs`; `POST /sync/pipeline/run`, `/sync/jobs/{job_type}/run?range=&force=`, `/sync/advanced/rebuild-all`, `/sync/advanced/resync-all` | `test_sync_progress.py`, `test_environment_guard.py` (the destructive guard) |
| Trades, tags | `app/routers/trades.py` | `GET /trades`, `/trades/{id}`, `/trades/{id}/fills`, `/trades/fills/bulk?ids=`; `POST /trades/{id}/tags` | browser tests; `test_seed_dev_data.py` |
| Fills CRUD | `app/routers/fills.py` | `GET`/`POST /fills`, `GET`/`PUT /fills/{id}` | browser tests |
| Stats, accounts | `app/routers/stats.py`, `app/routers/accounts.py` | `GET /stats`, `GET /accounts` | the browser fixture test asserts `/stats` totals |
| Live quotes | `app/engine/quotes.py` (provider seam), `app/engine/tradier.py`, `app/engine/occ.py`, `app/routers/quotes.py` | `GET /quotes?tickers=`, `POST /quotes/positions` | `test_quotes_provider.py` (dispatch, batching, fallback), `test_tradier.py`, `test_occ.py` — the live call itself is uncovered; `scripts/compare_quote_providers.py` is how it gets checked |
| Market packets, reports, ticker analysis | `app/engine/packets.py`, `app/engine/analyzer.py`, `app/engine/news.py`, `prompts/market_report.md` | `GET /packets/report`, `/packets/analyze`, `/packets/news` | — (live Alpaca and yfinance) |
| Scalp analysis | `app/engine/scalper.py` (`score_scalp()` is pure) | `GET /packets/scalp` | `test_scalper.py` |
| AI review | `app/ai/reviewer.py` (one trade, on the plan, with the day context), `app/ai/monthly_reviewer.py` (one month from statistics: overall, breakdowns by ticker, side, entry time, hold time, weekday, size, days to expiry, captured plan, SPY's day and entry flags; the month's daily reviews and rules; last month and its commitment; table `monthly_review`), `app/routers/monthly_review.py`, `/daily/month/{YYYY-MM}` (`components/MonthlyAiPanel.tsx`), `app/ai/daily_reviewer.py` (prompt v4: process grade, the last review's rules checked, the trader's 20-day baseline, data gaps, plan vs execution, the market read), `app/ai/review_context.py` (the day around the trades: captured plans, tags, SPY/QQQ/IWM/SMH, SPY's and QQQ's intraday shape, VIX and the 10-year yield from yfinance, sector-relative moves, earnings, headlines, open-interest walls, the trader's levels and fired alerts, `app/data/macro_calendar.json`), `app/ai/daily_review_service.py`, `app/ai/plan_runner.py` (`claude -p` on the Claude plan), `app/jobs/plan_reviews.py` (nightly run, opt-in `tradejournal-plan-reviews.timer`), `app/routers/daily_review.py` | `POST /trades/{id}/review` (on the plan); `GET /daily-review`, `/daily-review/{day}`, `/daily-review/runner`, `POST /daily-review` (on the plan); `GET /monthly-review`, `/monthly-review/{month}`, `POST /monthly-review` (on the plan); the Sync Center `daily_review` job is retired (the nightly timer replaced it) | `tests/test_monthly_review.py` (stats, context, first-of-month trigger, routes), `tests/test_review_context.py` (offline: each part and its gaps), `tests/test_plan_reviews.py` (fake Claude Code: sign-in check, history, day choice, status, one trade's review), `frontend/e2e/daily-plan-review.spec.ts`; the live plan call is uncovered |
| Webull | `app/engine/webull*.py`, `app/routers/webull.py` | `GET /webull/health`, `/webull/accounts`, `/webull/orders/recent`, `/webull/orders/{order_id}`, `/webull/events/status`; `POST /webull/events/test-ingest`, `/webull/events/start`, `/webull/events/stop`; job `webull_listener` | `test_webull_ingest.py`, `test_webull_events.py`, `test_webull_signer.py` |
| Strategy Lab (kept readable, not extended since 2026-10-02: [what comes next](../strategy-factory.md#what-comes-next)) | `app/engine/strategy_lab.py`, `strategy_csv.py`, `strategy_metrics.py`, `app/routers/strategy_lab.py` | listed under the screen above | `test_strategy_lab_routes.py`, `test_strategy_import_routes.py`, `test_strategy_run_reads.py`, `test_strategy_csv.py`, `test_strategy_metrics.py` |
| Isaac Market Map backtester | `app/engine/market_map.py` (pure historical strategy research rules), `app/engine/market_map_report.py` (cohorts, TradingView-shaped CSV, export parity), `scripts/backtest_market_map.py` (Alpaca bars, CLI) | — (`python scripts/backtest_market_map.py MU META --days 365`) | `test_market_map.py` (synthetic bars), `test_market_map_exports.py` (execution model vs the committed TradingView exports), `test_market_map_report.py`; entry parity on real bars is the script's `--parity` run, see `docs/pine/README.md` |
| Strategy factory | `app/engine/factory_data.py` (bars, splits, features), `factory_rules.py` (entry families, the shared execution model, specs), `factory_model.py` (learned filter), `factory_gates.py` (gates, ledger records), `factory_brief.py` (the weekly brief, proposal review, weekly report) — all pure; `scripts/strategy_factory.py` (bar cache, ledger file, CLI, the opt-in `--use-api` Claude call, ntfy); `../scripts/factory_week.sh` (the weekly run, from launchd with `claude -p` on the Claude plan as the idea model, or by hand with a Claude Code session: `.claude/skills/factory-week/SKILL.md`); specs in `research/specs/`, results in `research/ledger.jsonl`; the live ledger and the weekly reports are on branch `factory/ledger`, never merged | — (`python scripts/strategy_factory.py run ../research/specs/<spec>.json`, then `ledger`; weekly: phone summary) | `test_factory.py` (synthetic bars: execution model, families, gates, forward evidence, the data lock end to end), `test_factory_brief.py` (catalog, digest, evidence, review, report), `test_strategy_factory.py` (the script with a stub minute source and a stub idea model); see `docs/strategy-factory.md` |
| Research workspace | `app/engine/research.py`, `app/routers/research.py` | `GET`/`PUT /research/workspaces/{slug}` | — |
| TradingView Signals page | `frontend/app/signals/page.tsx`, `frontend/app/signals/[alertId]/page.tsx`, `frontend/components/SignalsRefresh.tsx`, `frontend/lib/tradingview.ts` | `/signals` in the nav, then any row's **Detail**; both refresh every 30s while visible and on tab return | `frontend/e2e/signals.spec.ts`: new alerts, verdicts/details, hidden-tab pause, navigation cleanup, slow refresh and skip/error reasons against disposable SQLite |
| Automatic deployment | `deploy/autodeploy.py`, `.github/workflows/release.yml`, `deploy/control.py` (`prune`, lock exit 75), `deploy/systemd/tradejournal-autodeploy.*`, `deploy/autodeploy.env.example` | merge to `main`; on the VPS `sudo … autodeploy.py status` ([automatic deployment](../../deploy/README.md#automatic-deployment)) | `test_autodeploy.py`, `test_deployment.py`; the Ubuntu smoke upgrades through the real unit against a local stand-in for GitHub. The live Release workflow runs only on `main` |
| Retired TradingView alert records | `app/models.py`, `app/engine/tradingview_alerts.py`, `app/routers/tradingview_alerts.py`; migration and legacy parsers retained for historical data | private read-only `GET /tradingview/alerts`, `/tradingview/alerts/{alert_id}`; Signals list/detail pages | `test_tradingview_routes.py` (GET-only API and DTO reads), `test_tradingview_alert_migration.py`; C5.2 deployment smoke proves no ingress service or 8090 listener |
| Schema | `app/models.py`, `alembic/versions/`, `app/schema.py` | — | `test_schema_migrations.py`, `test_schema_authority.py`, `test_postgres_parity.py`, `test_postgres_migration_paths.py` |
| Which database am I on | `app/environment.py`, `app/database.py`, `app/routers/health.py` | `GET /health` | `test_environment_guard.py`, `test_check_database.py` |
| Database roles | `scripts/setup_roles.py` | — | `test_setup_roles.py` (Postgres job only) |
| App startup and wiring | `app/main.py` | — | every `TestClient(app)` test boots the real lifespan |
| Import boundaries | `tests/test_import_boundaries.py` (the policy lists are at the top) | — | itself; see `architecture.md` |
| MCP tools for Claude Desktop | `mcp_server.py` | — | — |

## Getting evidence for a change

The isolated **Level 2 lab** (`/level2-lab`, owner navigation) keeps its synthetic replay in
`frontend/components/level2/Level2Lab.tsx` and `frontend/lib/level2Replay.ts`,
covered by `frontend/e2e/level2-lab.spec.ts`. A separate manual provider section
(`frontend/components/level2/LiveDepthSession.tsx`) uses the disabled-by-default
`frontend/app/api/level2-lab/session/route.ts` and an explicitly started
`backend/scripts/moomoo_lab_server.py` loopback bridge. Its tests are
`frontend/e2e/level2-live.spec.ts`, `frontend/e2e/level2-route.spec.ts` and
`backend/tests/test_moomoo_lab.py`. On Charts the session is owned by the page
(`frontend/components/level2/useDepthSession.ts`) and feeds a memory-only
heatmap behind the main chart's candles for one US ticker at a time (`frontend/lib/depthHeatmap.ts`, drawn from
`frontend/components/charts/PriceChart.tsx`); its browser checks are in
`frontend/e2e/charts.spec.ts`. The opt-in depth recorder and its R2 upload are
`backend/scripts/moomoo_depth_recorder.py` and `backend/scripts/depth_upload.py`,
tested in `backend/tests/test_moomoo_depth_recorder.py`. Charts reads it as liquidity levels, a depth
profile and an opt-in heatmap through `backend/scripts/depth_history.py`,
`frontend/app/api/level2-lab/depth/route.ts` and
`frontend/components/level2/useRecordedDepth.ts` (`backend/tests/test_depth_history.py`). It changes no chart feed or saved metrics;
see the [prototype notes](../level2-synthetic-prototype.md) and
[manual connection contract](../level2-manual-connection.md).

- **Engine or router change:** the test module in the table, or drive the
  route through `TestClient(app)` the way `test_fill_import.py` does.
- **Anything a page shows:** `bash scripts/verify.sh --e2e`. The smoke tests
  (`frontend/e2e/smoke.spec.ts`) open `/`, `/trades`, `/trades/{id}`,
  `/fills`, `/analytics`, `/daily`, `/strategy-lab` against a seeded backend
  and assert the values from `EXPECTED` in `scripts/seed_dev_data.py`. Then
  open the route on the dev server (`bash startdev.sh`, port 3000) and say
  what you saw. For a chart picture a person will judge, use the
  market-shaped candles in `frontend/e2e/fixtures/realisticBars.ts`; to try
  the UI on real candles without touching real records or synced chart
  settings, `bash scripts/ux_sandbox.sh` (port 3098, its own seeded SQLite).
  `--jo-day` instead runs a scripted Jo day on a fake clock
  (`backend/scripts/ux_jo_day.py`): briefing, scheduled and extra reads, an MU
  price watch that triggers, a refused TSLA watch, a market-read phone message,
  a missing read with the watchdog's notice, and a late read,
  written through the Check ledgers and outboxes and judged by the app's own
  importers, plan monitor and API; step it with `POST :8098/__sim/next`.
  The `trade-chart-ux` skill (`.claude/skills/trade-chart-ux/SKILL.md`)
  covers UI review and the picture checks before review.
- **A route with no test:** call it and paste the response.
  `curl -s localhost:8080/health` tells you which database you are on first.

## Analysis and repair scripts

`backend/scripts/` — stable utilities:

- `generate_reconciliation_report.py` — markdown reports into `backend/reports/`
- `analyze_tiebreak_impact.py` — read-only same-timestamp FIFO impact analysis
- `csv_reconstruct.py` — DB-derived FIFO vs Robinhood CSV ground truth
- `find_phantoms.py` — duplicate cumulative partial-fill investigation
- `rebuild_trades.py`, `backfill_greeks.py`, `inspect_enrichment.py`
- `seed_dev_data.py` — the fixed fills behind the browser tests and the snapshot
- `migrate_sqlite_to_postgres.py` — SQLite → PostgreSQL copy
- `check_database.py` — read-only preflight: which database, schema ready?
- `repair_gmail_fill_times.py` — plans, checks and applies the guarded repair of
  Gmail fill times stored as UTC clocks, verified against the source emails
  (`domain-rules.md`, fills and trades)
- `repair_expired_trade_times.py` — the guarded repair of expiration closes
  saved as UTC clocks instead of 16:00 New York wall time
- `setup_roles.py` — provision and verify database roles, including the
  retained legacy ingress role by connecting as each one (`environments.md`)
- `backtest_market_map.py` — Isaac Market Map over many tickers from Alpaca
  bars: cohort report in R, Strategy Lab CSVs, `--parity` against exports
- `imm_export_cohorts.py`, `playbook_cohorts.py` — the cohort evidence
  `docs/pine/README.md` cites
- `research_studio.py` — explicit-root cache-only discovery population preview;
  no UI, provider, database, outcomes or Factory execution. Shared stop-free
  features and strict masks live in `app/engine/research_studio.py`;
  [R1 contract](research-studio-r1.md) owns source/identity and acceptance.
- `research_studio_run.py` — explicit local R2 enqueue/work-once/status/result/
  cancel/retry; parent-owned research SQLite/artifacts and a pure calculation
  child, no app route/service/provider or journal/Factory writes. The
  [R2 contract](research-studio-r2.md) owns semantics, exposure and acceptance.
  R3 connects **Research Studio** (`/research-studio`) through
  `frontend/components/research-studio/ResearchStudio.tsx`, its static chart,
  `backend/app/routers/research_studio.py`, and the manually started
  `backend/scripts/research_studio_server.py` sidecar. The
  [R4](research-studio-r4.md) adds frozen-parent comparisons and append-only conclusions through the same owner workspace, with plain labels and separate finite comparison computation.
  The [comparison extension](research-studio-comparison.md) adds every-event
  endpoints, concentration checks and compatible saved-period summaries.
  The [prospective MU study](research-studio-prospective-mu.md) is a separately
  registered, scheduled cache/receipt workflow with a fixed formal review;
  `backend/scripts/research_studio_prospective.py` and its explicit installer
  `deploy/research_studio_prospective.py` own it. Future results stay separate
  from the historical Studio UI and never enter Factory gates.
- `overnight_trial.py` — finite invented-data rehearsal around the existing R2
  store, durable run receipt and consolidated Markdown report; explicit bounded
  retry, no agents/providers/schedules. [Ownership, host plan and activation
  boundary](../overnight-engineering.md); `tests/test_overnight_trial.py`.
  [R3 contract](research-studio-r3.md) owns setup and inspection/exposure
  boundaries; `backend/tests/test_research_studio_session.py` and
  `frontend/e2e/research-studio.spec.ts` prove the fixture workflows.
- `strategy_factory.py` — judges a strategy spec through the factory's gates
  and appends the result to `research/ledger.jsonl`; `prepare` fetches the SIP
  minute bars it needs (the only step that calls Alpaca); `week` is the weekly
  loop (it calls Claude) and `notify` sends its summary to the phone. The
  repository-level `scripts/factory_week.sh` runs them every Sunday from
  launchd in the factory checkout (`docs/strategy-factory.md`)

`backend/compare_fills*.py` are ad hoc scratch scripts, not stable app code.

Scripts in `backend/scripts/` may do real work (open databases, call APIs) at
**import** time. Pytest collection is scoped to `backend/tests` for this
reason, and ruff lints them without importing them.

## Documentation upkeep

- `docs/agent/last-reconciled.json` — the commit documentation was last
  reconciled to. `tests/test_docs_freshness.py` counts code commits past it
  and warns past 30 (it never fails CI); `tests/test_docs_links.py` checks
  names and anchors. The judgement half is `.claude/skills/docs-drift/SKILL.md`.
  It runs unattended every day as a Claude Code routine in Anthropic's cloud
  ("Daily docs drift pass" at claude.ai/code/routines), on the Claude plan rather than API
  credits, so it needs no token, no Mac and no launchd job. From 20 code
  commits on, and only when no earlier `claude/docs-drift-*` pull request is
  still open, it runs the pass on a fresh clone of `main`, edits only
  documentation, moves the marker, runs the docs tests and opens a pull
  request on `claude/docs-drift-<date>`. It never merges. Its instructions
  live in the routine, not the repository; each run's log is on its routine
  page. (Until 2026-10-10 a launchd script on the development Mac ran it
  with `claude -p`; before that, a desktop scheduled task stalled on a
  permission prompt on its first run, 2026-09-26.)

## Reference documents

- `docs/tradingview-webhook-contract-v1.md` — frozen wire contract
- `docs/strategy-lab-metrics.md` — metric definitions
- `docs/strategy-lab-pine-metadata.md` — the `sl1|key=value|...` convention
- `docs/pine/README.md` — archived Isaac Market Map research and historical
  TradingView export comparisons
- `docs/strategy-factory.md` — how the strategy factory judges an idea (the
  periods, random-entry baseline, rising bar and holdout lock), how to write a
  spec, and its results so far

## Where things are NOT

- No auth, no multi-user model, no roles in the application (database roles
  exist; see `environments.md`).
- No live trading. Webull has read/listen/import only; the scalper is
  decision support and never places orders.
- No component-level frontend tests; the Playwright smoke tests are the only
  frontend coverage, and they are smoke depth.
- The Pine alert source was retired with C5.2; the Python research implementation remains tested on synthetic bars and historical exports.
- `/accounts` is a placeholder page (above).

## Subsystem notes worth knowing before you dig

- **Market packets** (`app/engine/packets.py`) build deterministic
  premarket/postmarket reports: index detail with VWAP/ORB/premarket/AH, sector
  rotation, macro gauges (`^VIX`/`^TNX` via yfinance), a bucketed high-beta
  universe with `rs_vs_spy`, leaders/laggards, and raw Alpaca news. The symbol
  universe is hand-edited in `backend/data/universe.json` — it is an execution
  watchlist, not the market. No relevance filtering happens in Python; Claude
  triages headlines. Judgment lives in `backend/prompts/market_report.md`, not
  in backend code.
- **Scalper** (`app/engine/scalper.py`) is read-only decision support and never
  places trades. `score_scalp()` is a pure function over a packet and is tested
  without network in `tests/test_scalper.py`; `build_scalp_analysis()` is the
  gathering layer. Hard rules: closed market or stale data ⇒ wait/no_trade;
  option spread >10% of mid ⇒ reject; inside the VWAP/OR band on weak RVOL ⇒
  chop; extra strict in the first 5–15 minutes.
- **MCP server** (`backend/mcp_server.py`) is a stdio FastMCP adapter for Claude
  Desktop. It is a thin httpx client over the private API, holds no API keys,
  and logs calls to `backend/data/mcp_log/*.jsonl`. It defaults to
  `http://localhost:8000`; set `TRADE_JOURNAL_API` when the backend is on 8080.
  Read-only tools: `get_market_report`, `get_news`, `analyze_ticker`,
  `analyze_scalp`, `get_trades`, `get_stats`, `get_trade_detail`,
  `get_coverage`, `get_trade_audit`, `get_trade_path_metrics`,
  `get_fill_contexts`.
- **Caches** live at `backend/data/polygon_cache/` and
  `backend/data/alpaca_cache/`. Deleting a file forces a re-fetch. The audit
  reads existing files without fetching and separates missing/stale evidence from matches.
  The golden snapshot reads the Alpaca cache; `test_seed_snapshot.py` points
  it at an empty directory so a developer's cache cannot leak into the result.

## Owner Dashboard foundation

The owner root view mounts `frontend/components/dashboard/OwnerDashboard.tsx`:
ET closed-P&L summary, factual session counts, compact active options, collapsed
stock holdings, exposure disclosure, compact performance and five recent trades
ordered by close time. Account/type filters and decision/run references stay in
the URL. The owner Practice workspace and saved decisions live at `/practice`,
linked from the sidebar and phone More menu. Legacy `/?decision=` and
`/?practice_run=` links forward there. Journal-reader and decision-writer assistant branches retain their
existing surfaces. See the [inventory and staged plan](../dashboard-redesign.md).
`frontend/e2e/dashboard.spec.ts` exercises states, scopes, navigation and desktop
and phone pictures; the browser harness has offline position quotes.

## Dashboard Attention

`frontend/components/dashboard/AttentionPanel.tsx` streams in beside Today's
Session after the rest of the owner Dashboard; `frontend/lib/dashboardAttention.ts`
holds the rules. It reads the positions the page already loaded plus
`GET /charts/alerts`, `/sync/jobs`, `/gmail/health` and, per open-option
underlying, `/charts/symbol/{symbol}/events` and, per open option trade,
`/trades/{id}/phone-alerts`. Order: record integrity (expired but
open, no price, no basis), import and sync data (Gmail down/degraded, failed job),
expirations within three calendar days and earnings on or before expiry, price
alerts fired in the last 24 hours and today's (ET) latest give-back phone alert per open
position, which opens that alert (`/trades/{id}?alert={event_id}`), then the owner's own open WAIT choices. A failed
source is listed as "Could not check", never read as quiet. Job and Gmail items
open the Sync Center through `/?sync=open`. Pure rule tests and the panel picture
are in `frontend/e2e/dashboard-attention.spec.ts`.

## Open-position basis

Dashboard and Daily Review share `frontend/lib/dashboard.ts` for remaining
FIFO basis and unrealized P&L. Fill ordering matches reconstruction: ET wall
time, opens before closes, then fill ID. The all-entry trade average remains
historical; it is not the basis of lots left after a partial close. Missing or
invalid lot evidence leaves basis/P&L unavailable. Option fill prices are per
contract, so only quote marks are multiplied by 100. Pure browser-runner
regressions in `frontend/e2e/dashboard-basis.spec.ts` cover partial FIFO closes,
same-minute ordering, fractional shares and long/short option units. Backend
`app/engine/chart_journal.py` remains the independent FIFO projection.

## A3 daily Practice routine

The owner `/practice` page and Daily Review mount
`frontend/components/PracticeRoutine.tsx`; assistant Today surfaces are retained: manual
preparation, frozen contexts, validated immutable choices, explicit reveal,
A2 arming, outcome/coverage review, feedback and actual attention timers.
The page leads with the day's task (setups to answer before the cutoff and
progress); a TAKE is entered by picking saved price facts, which the page turns
into the same A1 plan the server validates. The morning brief, per-setup
outcome/feedback and run provenance (policy, hashes, IDs, agent cost) sit in
collapsed sections.
`backend/app/routers/practice.py` owns the private owner API;
`backend/app/engine/practice.py` owns run/revision identity and deterministic
review/benchmark. `backend/app/engine/practice_agent.py` is the bounded tool-free
adapter, disabled by default. `backend/app/jobs/practice_schedule.py` and the
optional `deploy/systemd/tradejournal-practice.timer` provide disabled 08:50 ET
scheduling in a separate lane. Tests live in
`backend/tests/test_practice_routine.py` and
`frontend/e2e/practice-routine.spec.ts`. See the
[A3 acceptance contract](a3-implementation-contract.md); live acceptance is
unobserved until three real sessions and their actual routine timings exist.


## Optional assistant browser access

Private owners in authenticated mode also have `/access` for credential
administration; a restricted assistant sees only granted pages and no Sync
controls. `/login` is the dedicated assistant sign-in page. Authentication is
disabled by default, and the optional assistant listener has no bundled
internet ingress. See the [access contract](cloud-browser-auth-contract.md)
for scope and rollout gates.

Code: backend `app/engine/access.py`, `app/access_manifest.py`,
`app/access_middleware.py`, `app/routers/access.py`; frontend
`proxy.ts`, `lib/accessServer.ts`, `lib/backendProxy.ts`, `lib/serverApi.ts`,
`components/AccessProvider.tsx`, `components/AssistantAccess.tsx`.
Proof: backend `tests/test_browser_access.py`, `tests/test_access_deployment.py`,
Postgres parity; frontend `e2e/browser-access.auth.ts` through
`playwright.auth.config.ts`. Fixtures are not a live Dot or TLS observation.

## Optional sample cloud connector

D0 exposes the synthetic profile. The selected D1 increment adds two read tools
for one linked assistant's assigned simulated MU/NBIS Practice run. Structured
tools retrieve frozen records; the separately signed-in assistant UI handles
charts and visual flow. No connector writes or paid model/provider calls.
See the [D1 contract](cloud-mcp-d1-contract.md) for manual activation and pending
actual Dot acceptance.

Code: `backend/cloud_mcp_d1.py`, `backend/cloud_mcp_d1_common.py`, backend
`app/engine/cloud_practice_access.py`, `app/routers/cloud_practice.py` and the
existing restricted sample projection. Proof: `backend/tests/test_cloud_mcp_d1.py`
and `deploy/cloud-mcp-d1/smoke.py` on disposable Ubuntu; live OAuth/tool/UI evidence
is a separate gate. Normal releases keep the templates disabled.

## Manual advisor/shadow fixture

The owner-only panel on Today is shown only for an operator-created invented
assignment. `backend/app/engine/advisor_shadow.py` owns the allowlisted packet,
immutable manual assignment/receipt and assistance boundary;
`backend/advisor_shadow_demo.py` is its separate loopback-only three-operation
shadow gateway. `backend/scripts/advisor_shadow_demo.py` creates a fresh migrated
SQLite fixture or revokes it. Owner advisor export/answer routes live in
`backend/app/routers/advisor_shadow.py`; `frontend/components/AdvisorShadowPanel.tsx`
displays the exact packet, explicit question/plan, manually supplied answer and
resolved fact citations. Existing Practice controls retain paired choice/reveal
and paper review. Checks are `backend/tests/test_advisor_shadow.py`,
`backend/tests/test_advisor_shadow_cli.py`, the owner-route refusals in
`backend/tests/test_browser_access.py` and `frontend/e2e/advisor-shadow.spec.ts`.
See the [contract and activation boundaries](advisor-shadow-contract.md).

The normal private journal's `/advisor-review` shows saved pre-trade checks
through its separately enabled journal reader. It omits the isolated demo's
connection and receipt panels, which require the authenticated owner entrance.
The optional direct owner view on `/advisor-review` uses
`frontend/components/AdvisorOwnerReview.tsx` and the shared pure
`frontend/components/AdvisorReceiptView.tsx`. Its Node-only `GET /api/advisor-owner` BFF requires an
explicit authenticated owner profile/session before and after a fixed Unix read.
`backend/cloud_advisor_owner.py` independently checks the exact kernel frontend
UID and reads only one pinned existing invented request/receipt from read-only
SQLite. Default legacy/assistant access cannot retrieve it. No journal database
repoint, file import, write or advisor catalog/grant expansion is involved.
Optional owner units remain excluded from the four-unit installer; checks are
`backend/tests/test_cloud_advisor_owner.py`, `frontend/scripts/advisor-owner.test.js`,
`frontend/e2e/advisor-owner.auth.ts` and the disposable advisor native smoke.
See the [direct owner boundary](cloud-mcp-advisor-contract.md#direct-owner-review-in-tradejournal-dormant).


### Repeatable invented advisor questions

`/advisor-review/questions` is an explicitly enabled authenticated owner flow,
linked from `/advisor-review`. `frontend/components/AdvisorAssignments.tsx` and the
`/api/advisor-assignments` BFF use the isolated advisor bridge and
`backend/app/engine/advisor_assignments.py`; they never use the journal database.
The [bounded contract](advisor-assignment-contract.md) owns its assignment,
revocation and dormant activation boundary. Proof lives in
`backend/tests/test_advisor_assignments.py`, the existing owner transport test
`frontend/scripts/advisor-owner.test.js`, and
`frontend/e2e/advisor-assignments.auth.ts`. Actual Jo acceptance is separate.

Macro Charts reuse `backend/app/engine/chart_indices.py` and the existing Charts workspace; `backend/tests/test_chart_indices.py` covers units/hours/cache, and `frontend/e2e/charts.spec.ts` covers Macro/Tech switching. See [the contract](../charts-workspace.md#macro-layout-vix-and-10-year-yield).

Weekly exit review: `backend/app/engine/weekly_review.py`, `backend/app/routers/weekly_review.py` (`GET/PUT /weekly-review/{monday}`), `frontend/app/daily/week/page.tsx`, `frontend/app/daily/week/[week]/page.tsx` and `frontend/components/WeeklyReviewPanel.tsx`; backend proof `backend/tests/test_weekly_review.py`. No committed weekly-review browser spec was found in this reconciliation. See [the plan and acceptance boundary](weekly-review-plan.md).

### Navigation continuity and Dashboard streaming

`frontend/lib/chartSession.tsx` owns the bounded, owner-only browser snapshot
cache used by `ChartWorkspace.tsx`; `frontend/e2e/chart-session.spec.ts` covers expiry/bounds,
and `charts.spec.ts` covers failure disclosure, exact candle and viewport reuse.
The owner Dashboard shell mounts morning/Radar context independently of the
shared journal/quote promise in `frontend/app/page.tsx`. Attention renders once
trades and quotes arrive, without waiting for journal statistics; both keep the
existing calculations and error disclosures. Ordinary internal Dashboard links
use client navigation, and sidebar/tab links in `frontend/components/Nav.tsx`
mark themselves pending while the next page's server data loads. `dashboard.spec.ts` checks partial loading,
filters, failures and desktop/phone layout. The opt-in
`frontend/e2e/navigation-performance.spec.ts` measures these paths on invented candles and
controlled response delays; it makes no provider calls. Chart and Tradier quote transport
is in `backend/app/engine/market_http.py`, with credential/timeout/no-cookie-reuse
coverage in `backend/tests/test_market_http.py`. `scripts/benchmark_chart_json.py`
measures how long chart responses stall the API's event loop.
