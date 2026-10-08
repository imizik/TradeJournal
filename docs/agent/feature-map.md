# Feature map

How to get from a feature to its screen, its endpoints, its code and its
proof. The code is the source of truth; this shortens the search and says
where the evidence for a change comes from.

Backend paths are relative to `backend/`, frontend paths to `frontend/`.

For Charts changes, use the [roadmap's execution order](../charts-roadmap.md#status-board)
and [C0.0 implementation contract](../charts-deep-history.md). The tables below
describe shipped code, including deep-history pagination, the split-adjusted price basis and daily/weekly depth.

## The screens

The sidebar (`components/Nav.tsx`) has nine entries plus a **Sync** button
at its foot that opens a drawer on any page. Everything else is reached from
one of these by a row link or a button.

| Sidebar | Route | Page | Loads | Then, from the browser |
|---|---|---|---|---|
| Dashboard | `/` | `app/page.tsx` | `GET /stats`, `/trades`, `/accounts`, `/trades/fills/bulk`, `/quotes?tickers=`, `POST /quotes/positions` | `DashboardActions`: `GET /sync/summary`, `/sync/jobs`, `/sync/runs`, `/health`, `/auth/gmail/start`; `POST /sync/pipeline/run`, `/sync/jobs/{job_type}/run`, `/sync/advanced/rebuild-all`, `/sync/advanced/resync-all` |
| Charts | `/charts` | `app/charts/page.tsx`, `components/charts/`, `components/AppMain.tsx` | — | the page fills the window beside a navigation rail (C7.3): one toolbar row, a drawing-tool rail, a side dock (watchlist or layers; a bottom sheet on a phone) and a status strip, charts sized by the browser; dividers between the main chart and the smaller row, between the smaller charts and at the dock's edge, and Maximize on each chart (C7.4, `components/charts/Splitter.tsx`; proportions shared, dock width and maximize per device); `GET /charts/workspace` every 15s while visible for Tradier today/quotes; `GET /charts/history` on scroll: intraday pages from completed Alpaca SIP sessions, 1D/1W pages from Tradier's whole daily history (read once per day); prices are split-adjusted with a basis chip and a warning when splits are unknown, and saved levels move with later splits; private stream, linked timeframes, fill markers, countdown, full screen, symbol search; `GET`/`PUT /charts/settings` shares levels, watchlist and layout across devices with a revision check (browser copy offline); smaller charts can hold their own symbol (three symbols at most, one request and one stream); named layouts (intervals, held symbols, chart sizes, linked ranges) are saved with those settings and switched from the Layouts menu (`components/charts/LayoutMenu.tsx`); hotkeys (`lib/hotkeys.ts`: typed minutes on Enter, H/4/D/W, Space watchlist steps, Alt+R reset, End to realtime, Delete and ⌘/Ctrl+Z undo for levels and drawings) listed by the `?` sheet (`components/charts/HotkeySheet.tsx`); the drawing layer (`lib/drawings.ts`): levels and drawings (horizontal ray, trend line, rectangle zone, text note from the tool buttons beside Undo/Redo, magnet to OHLC) select by click or tap, drag, restyle from the selection bar (`components/charts/SelectionBar.tsx`), delete and undo/redo; right-click or a long press opens the chart menu (`components/charts/ChartMenu.tsx`): add a level or copy the price there, reset that chart's scale, Layers (hide levels, drawings, fills and studies on every chart; show hidden items), and on a level or drawing its label and color inline, lock, hide, duplicate and delete; the Layers button opens the layers panel (`components/charts/LayersPanel.tsx`, a bottom sheet on a phone): hide My levels, Drawings, Journal or Indicators on every chart, lock or delete all levels or drawings (one undo step), hide/lock/delete one item, or click it to bring the chart to it; Layers → Options levels shows option walls, ranked strikes and max pain with their filters, Layers → Range bands the expected move and VWAP ±1σ/±2σ, and the dock's Strike ladder tab (`components/charts/OptionsLadder.tsx`) lists strikes around the price and marks one on the charts |
| Symbol info / You, News, Events, Forecast, Short | `/charts`, below the watchlist | `components/charts/SymbolInfo.tsx`, `components/charts/SymbolInfoYou.tsx`, `components/charts/SymbolInfoNews.tsx`, `components/charts/SymbolInfoEvents.tsx`, `components/charts/SymbolInfoForecast.tsx`, `lib/symbolInfo.ts`; `app/engine/symbol_info_reactions.py` | — | `GET /charts/symbol/{symbol}/you`: all-account completed-trade stats, open records and recent links; `GET /charts/symbol/{symbol}/events`: next earnings with confirmed/estimated status, the last eight reports, dividends and splits; `GET /charts/symbol/{symbol}/forecast?spot=`: T2.1 implied moves; `GET /charts/symbol/{symbol}/reactions`: T2.2 inferred earnings reactions from the latest eight confirmed reports, using completed split-adjusted Tradier daily bars; `GET /charts/symbol/{symbol}/news`: merged Alpaca (Benzinga) and Polygon headlines with per-source status and Polygon-supplied sentiment; `GET /charts/symbol/{symbol}/short`: T3.1 FINRA short interest, short volume and the hard-to-borrow flag; T1.3 Overview with the T3.3 Ownership section (13F from the overview payload; `GET /charts/symbol/{symbol}/insiders`: 90-day open-market insider buys and sells from Yahoo, unofficial, cached a day); device-local tab choice and collapsed phone panel; `tests/test_symbol_info.py`, `tests/test_symbol_info_reactions.py`, `tests/test_symbol_info_events.py`, `tests/test_symbol_info_news.py`, `tests/test_symbol_info_insiders.py`, `tests/test_options_feed.py`, `e2e/symbol-info.spec.ts` |
| Journal on the chart (trade card, position lines, historical mode) | `/charts`: hover or click a fill arrow; lines for open positions; **Open on chart** on a trade or fill page | `components/charts/TradeCard.tsx`, `lib/chartJournal.ts`, the arrows' hover and click in `components/charts/PriceChart.tsx`, the past-trade banner in `components/charts/ChartWorkspace.tsx`, `app/trades/[id]/page.tsx`, `app/fills/[id]/page.tsx` | — | `GET /charts/journal/fills/{id}`, `GET /charts/journal/trades/{id}` (`/mark` for an open option), `positions` in `GET /charts/workspace`; `tests/test_chart_journal.py`, `e2e/chart-journal.spec.ts` |
| Plans linked to trades | `/charts`: **Needs linking** on the saved-plan strip; the trade card and trade page show a linked plan | `components/charts/LinkReview.tsx`, `components/charts/PlanSummary.tsx`, `components/charts/PlanStrip.tsx`, `lib/captures.ts` | — | `/charts/captures/review`, `/link`, `/unlink`, `/tracking`, `/for-trade/{id}`; `tests/test_capture_links.py`, `e2e/chart-journal.spec.ts` |
| Pre-trade capture | `/charts`: **Plan trade** in the toolbar or Alt+P; the saved-plan strip above the charts; the gear in the sheet for templates and the default account | `components/charts/PlanSheet.tsx` (sheet, recorder, setup), `components/charts/PlanStrip.tsx`, `lib/captures.ts` (routes, outbox, image) | — | `/charts/captures` routes; template, Discretionary and voice plans with a frozen chart snapshot; `tests/test_captures.py`, `e2e/charts.spec.ts` |
| Practice decisions (A1) | `/`: Practice decisions section on Today | `app/engine/decisions.py`, `app/routers/decisions.py`, `components/PracticeDecisions.tsx`, `components/PracticeDecisionForm.tsx`, `lib/api.ts`; `DecisionRecord` and `DecisionContext` in `app/models.py` | `POST /decisions/context/{symbol}`, `/decisions` (create/list), `/decisions/{id}` | `tests/test_decisions.py`; immutable server-owned context, typed choices, and practice drafts/unarmed |
| Practice paper plans (A2) | Today page (`/`): a TAKE card under Practice decisions has an Arm paper plan button, the Practice paper timeline and base plus 3× costs outcome; `/?decision=<id>` opens that card | `app/engine/paper.py` (arming, watcher, phone outbox), `app/engine/paper_execution.py` (pure rules), `app/engine/level_alert_monitor.py` (runs the watcher); `DecisionEvent` in `app/models.py` | `POST /decisions/{id}/arm`, `GET /decisions/{id}/paper`; UI `frontend/components/PracticeDecisions.tsx`, `frontend/components/PracticePaperPlan.tsx`, `frontend/app/page.tsx`, `frontend/lib/api.ts` | `tests/test_paper_execution.py`, `tests/test_paper_plans.py`, `frontend/e2e/practice-decisions.spec.ts`; [live SPY phone, open-position restart and exit observation](practice-policy.md#a2-live-operational-observation-2026-10-08) recorded 2026-10-08; operational probe outside the on-time strategy cohort |
| Level alerts | `/charts`: right-click (long-press) a level, horizontal ray or automatic level; the Alerts list in the dock | `components/charts/AlertsPanel.tsx`, `components/charts/ChartMenu.tsx`, `lib/alerts.ts` (bells: `AlertLayer`) | — | `GET`/`POST /charts/alerts`, `POST /charts/alerts/{id}/rearm`, `DELETE /charts/alerts/{id}`, and `alerts` in `GET /charts/workspace`; touches, crosses, closes beyond; judged and sent to the phone by the API with no tab open; `tests/test_level_alerts.py`, `e2e/charts.spec.ts` |
| Daily Review | `/daily` → `/daily/{YYYY-MM-DD}` | `app/daily/page.tsx`, `app/daily/[day]/page.tsx` | `GET /daily-review`; per day `/daily-review/{day}`, `/trades`, `/trades/{id}/fills`, `/market-context/fills/bulk`, `/accounts`, quotes | `DailyAiPanel`: `POST /daily-review` |
| Trades | `/trades` → `/trades/{id}` | `app/trades/page.tsx`, `app/trades/[id]/page.tsx`, `components/TradesTable.tsx` | list: `GET /trades?status=&ticker=&account=&type=`, `/accounts`. Detail (client page): `/trades/{id}`, `/trades/{id}/fills`, `/market-context/fills/bulk`, `/market-context/trade/{id}` | `AuditPanel`: `GET /market-context/audit/{id}`; review button: `POST /trades/{id}/review` |
| Analytics | `/analytics` | `app/analytics/page.tsx`, `components/AnalyticsExplorer.tsx` | `GET /stats/analytics`, `/accounts`; pure metrics in `app/engine/analytics.py`; [definitions and proof](../analytics.md) | local grouping/sorting/drill-down, links to trade details |
| Fills | `/fills` → `/fills/{id}` | `app/fills/page.tsx`, `app/fills/[id]/page.tsx` | `GET /fills`, `/accounts`; edit: `/fills/{id}` | `ManualFillForm`: `POST /fills`, `PUT /fills/{id}` |
| Strategy Lab | `/strategy-lab` → `/strategies/{id}`, `/strategies/{id}/versions/new`, `/versions/{id}`, `/versions/{id}/import`, `/runs/{id}` | `app/strategy-lab/**`, `components/strategy-lab/`, `lib/strategy-lab/api.ts` | `GET /strategy-lab/strategies`, `/strategies/{id}`, `/versions/{id}`, `/runs`, `/runs/{id}`, `/runs/{id}/trades`, `/runs/{id}/metrics` | forms and wizard: `POST /strategy-lab/strategies`, `/strategies/{id}/versions`, `/versions/{id}/fork`, `/imports/preview`, `/runs/import`, `/runs/{id}/metrics/recalculate`; `PATCH /strategies/{id}`, `/versions/{id}` |
| Research | `/research/ai-buildout` | `app/research/ai-buildout/page.tsx`, `components/research/`, `lib/research/` | — | `GET`/`PUT /research/workspaces/{slug}` |
| Sync (drawer) | any page | `components/StatusPanel.tsx` | — | polls `GET /fills/enrich/status`, `/market-context/enrich/status`, `/market-context/trade-path/status`, `/market-context/coverage` |

Things worth knowing before you touch a page:

- Pages under `app/` are server components that call the API from the Next
  server through `lib/api.ts` (`NEXT_PUBLIC_API_URL`, default
  `http://localhost:8080`), except `/trades/{id}`, which is a client page.
  Client components may fetch from the browser; AnalyticsExplorer instead
  receives server-calculated metrics and trade rows as page props, so changing
  its grouping, sorting or drill-down does not fetch per-trade data.
- Row links go to `/trades/{id}` from the dashboard tables, the trades table
  and the daily review; the daily review also links each fill to
  `/fills/{id}?returnTo=`. The trade detail page links nowhere.
- The Sync Center's job types (`JOB_CONFIG` in `app/routers/sync.py`) are
  `gmail_sync`, `fill_import_check`, `trade_rebuild`, `polygon_enrich`,
  `alpaca_enrich`, `trade_path`, `daily_review` and `gmail_push`;
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
  bar plus a slide-out menu (same `navItems`), and below `sm` tables mark
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
| Charts workspace | `app/engine/chart_feed.py`, `app/engine/chart_history.py`, `app/engine/chart_calendar.py`, `app/engine/chart_splits.py`, `app/engine/chart_adjust.py`, `app/engine/chart_daily.py`, `app/engine/chart_stream.py`, `app/engine/chart_math.py`, `app/routers/charts.py`; `frontend/components/charts/`, `frontend/lib/charts.ts`, `frontend/lib/chartStore.ts`, `frontend/lib/chartSync.ts`, `frontend/lib/drawings.ts` | private `GET /charts/workspace`, `/charts/history`, `/charts/stream`, `GET`/`PUT /charts/settings`; `/charts` page | `tests/test_charts.py`, `tests/test_chart_history.py`, `tests/test_chart_calendar.py`, `tests/test_chart_splits.py`, `tests/test_chart_daily_history.py`, `tests/test_chart_stream.py`, `frontend/e2e/charts.spec.ts`; live access probes `scripts/check_chart_feed.py`, `scripts/check_chart_splits.py` and a read-only SIP session request; [provider decision and boundaries](../charts-workspace.md) |
| Symbol info / You (T1.1) | `app/routers/symbol_info.py`, `app/engine/symbol_info_journal.py` (two read-only queries), `app/engine/symbol_info.py` (pure summary); `frontend/components/charts/SymbolInfo.tsx`, `frontend/components/charts/SymbolInfoYou.tsx` | private `GET /charts/symbol/{symbol}/you`; `/charts` side column | `tests/test_symbol_info.py`, `frontend/e2e/symbol-info.spec.ts`; [panel behavior](../charts-workspace.md#symbol-info-panel) |
| Symbol info / News (T1.2) | `app/engine/symbol_info_news.py` (pure normalizers, merge, dedupe, Focused flag), `app/engine/symbol_info_news_feed.py` (Alpaca 60 s memory cache, Polygon 15 min disk cache, limiter, 429 fallback); `app/routers/symbol_info.py`; `frontend/components/charts/SymbolInfoNews.tsx` | private `GET /charts/symbol/{symbol}/news`; `/charts` side column, News tab | `tests/test_symbol_info_news.py`, `frontend/e2e/symbol-info.spec.ts`; [panel behavior](../charts-workspace.md#symbol-info-panel) |
| Symbol info / Peers strip (T3.4) | `app/engine/symbol_info_peers.py` (pure: related tickers, chips), `app/engine/symbol_info_peers_feed.py` (Polygon 7-day disk cache, limiter, 429 fallback; one batched Tradier quote call via the chart feed); `app/routers/symbol_info.py`; `frontend/components/charts/SymbolInfoPeers.tsx` | private `GET /charts/symbol/{symbol}/peers`; `/charts` side column, above the tabs | `tests/test_symbol_info_peers.py` (recorded Polygon and Tradier fixtures), `frontend/e2e/symbol-info-peers.spec.ts`; [panel behavior](../charts-workspace.md#symbol-info-panel) |
| Symbol info / Financials (T3.2) | `app/engine/symbol_info_financials.py` (pure: quarter selection by 80-105 day span, comparatives, calculated margins, year-over-year, Q4 gaps), `app/engine/symbol_info_financials_feed.py` (SEC EDGAR reads, `SEC_USER_AGENT`, ticker map and normalized-only disk cache, pacing, failure fallback); `app/routers/symbol_info.py`; `frontend/components/charts/SymbolInfoFinancials.tsx` | private `GET /charts/symbol/{symbol}/financials`; `/charts` side column, Financials tab | `tests/test_symbol_info_financials.py` (recorded NVDA and NBIS companyfacts in `tests/fixtures/sec/`), `frontend/e2e/symbol-info.spec.ts`; [panel behavior](../charts-workspace.md#symbol-info-panel) |
| Symbol info / Short (T3.1) | `app/engine/symbol_info_short.py` (pure normalizers and view), `app/engine/symbol_info_short_feed.py` (Polygon short interest, short volume and ticker details plus Tradier easy-to-borrow list, one-day disk caches, limiter, 429 fallback); `app/routers/symbol_info.py`; `frontend/components/charts/SymbolInfoShort.tsx` | private `GET /charts/symbol/{symbol}/short`; `/charts` side column, Short tab | `tests/test_symbol_info_short.py` (recorded fixtures in `tests/fixtures/symbol_info_short/`), `frontend/e2e/symbol-info.spec.ts`; [panel behavior](../charts-workspace.md#symbol-info-panel) |
| Symbol info / Events (T1.4) and chart earnings (C2.5) | `app/engine/symbol_info_tradier.py` (Tradier fundamentals: budget, cache, background refresh), `app/engine/symbol_info_events.py` (pure normalizers); `app/routers/symbol_info.py`, `app/routers/charts.py` (`earnings` in the workspace); `frontend/components/charts/SymbolInfoEvents.tsx`, `frontend/components/charts/EarningsBadge.tsx`, `earningsMarks` in `frontend/lib/charts.ts` | private `GET /charts/symbol/{symbol}/events`, `GET /charts/workspace`; `/charts` side column and chart headers | `tests/test_symbol_info_events.py`, `frontend/e2e/symbol-info.spec.ts`, `frontend/e2e/charts.spec.ts`; [earnings](../charts-workspace.md#earnings-c25) |
| Pre-trade capture (Charts C3.4, C3.5) | `app/engine/captures.py` (rules, private file storage, idempotent saves, transcription job), `app/engine/transcribe.py` (Whisper on the server), `app/routers/captures.py`; `TradeCapture`, `TradeCaptureNote`, `CaptureTemplate`, `CaptureProfile` in `app/models.py`; `alembic/versions/c3a4d5e6f7b8_add_trade_captures.py`; the `capture` lane in `app/engine/job_runtime.py`, `deploy/launch.py`, `deploy/control.py` | private `/charts/captures` routes; files under `CAPTURE_STORAGE_DIR` | `tests/test_captures.py`, `tests/test_deployment.py`, `frontend/e2e/charts.spec.ts`; [behavior](../charts-workspace.md#pre-trade-capture-c34-c35) |
| Journal on the chart (Charts C3.1–C3.3) | `app/engine/chart_journal.py` (read-only: cards, first-in-first-out open lots, positions; units and metric states), the `journal` routes and `positions` in `app/routers/charts.py`, `option_mark` in `app/engine/quotes.py`; `frontend/lib/chartJournal.ts`, `frontend/components/charts/TradeCard.tsx` | private `GET /charts/journal/fills/{id}`, `/charts/journal/trades/{id}`, `/charts/journal/trades/{id}/mark`; `/charts?symbol=…&from=…&to=…` | `tests/test_chart_journal.py`, `frontend/e2e/chart-journal.spec.ts`; [behavior](../charts-workspace.md#journal-on-the-chart-c31c33) |
| Capture links and coverage (Charts C3.6) | `app/engine/capture_links.py` (suggestions, links anchored in source fills, timing, coverage), routes in `app/routers/captures.py`; `CaptureLink` and the tracking fields on `CaptureProfile` in `app/models.py`; `alembic/versions/b5d7e9f1a3c6_add_capture_links.py` | private `/charts/captures/review`, `/charts/captures/{id}/link`, `/unlink`, `/charts/captures/tracking`, `/charts/captures/for-trade/{id}` | `tests/test_capture_links.py`, `frontend/e2e/chart-journal.spec.ts`; [behavior](../charts-workspace.md#plans-linked-to-trades-c36) |
| Level alerts (Charts C5.1) | `app/engine/level_alerts.py` (pure: when one fires, the message), `app/engine/level_alert_monitor.py` (record once, outbox delivery, 1-minute sweep), `app/engine/chart_stream.py` (alert symbols, coverage, `on_tick`), `app/engine/ntfy.py`, `app/routers/level_alerts.py`; `LevelAlert`, `LevelAlertEvent` in `app/models.py`; `alembic/versions/8d4f6a2c9e17_add_level_alerts.py`; `deploy/systemd/tradejournal-api.service` reads `alerts.env` | private `/charts/alerts` routes, `alerts` in `GET /charts/workspace`; ntfy | `tests/test_level_alerts.py`, `tests/test_deployment.py`, `frontend/e2e/charts.spec.ts`; [behavior and delivery](../charts-workspace.md#level-alerts-c51) |
| Options snapshots (Charts C4.3) | `app/engine/options_recorder.py`; `OptionChainSnapshot` and `OptionSnapshotDay` in `app/models.py`; `alembic/versions/5e8b2d7c4a19_add_option_snapshots.py`; `deploy/systemd/tradejournal-options-snapshot.timer` and its service | Sync Center → Options positioning snapshot (`POST /sync/jobs/options_snapshot/run`); weekday timer at 16:20 and 19:20 New York | `tests/test_options_recorder.py`, `tests/test_deployment.py`; [contract](../charts-workspace.md#options-snapshots-c43) |
| Relative volume (Charts C2.4) | `app/engine/chart_rvol.py` (pure: per-minute profiles, the 20-session baseline, each candle's RVol, equal to `compute_rvol_time_adjusted`), `ChartFeed._rvol` in `app/engine/chart_feed.py`, `ChartHistory.volume_profile` and `.session` in `app/engine/chart_history.py`; `app/engine/rvol_history.py` (the morning job); `deploy/systemd/tradejournal-rvol-history.timer` and its service; `volumeAlpha`/`rvolCoverage` in `frontend/lib/charts.ts`, the legend in `frontend/components/charts/PriceChart.tsx` | `/charts`: today's volume bars brighten with RVol; the main chart's study row reads the candle's RVol and the baseline's sessions; `rvol` and each candle's `rvol` in `GET /charts/workspace`; Sync Center → Relative volume history (`POST /sync/jobs/rvol_history/run`); weekday timer at 06:00 and 08:40 New York | `tests/test_chart_rvol.py`, `tests/test_rvol_history.py`, `tests/test_deployment.py`, `frontend/e2e/charts.spec.ts` (relative volume); [definitions](../charts-workspace.md#relative-volume-c24) |
| Automatic chart levels (Charts C2.1–C2.3) | `app/engine/chart_levels.py` (pure: prior day/week, premarket, overnight, opening ranges, swings, round numbers from supplied bars, calling the fill-context functions in `app/engine/indicators.py`; confluence zones; tested/broken/reclaimed), `ChartFeed._levels` in `app/engine/chart_feed.py`; `frontend/lib/autoLevels.ts` (the layer behind the candles), `frontend/components/charts/LevelCard.tsx` | `/charts`: the nearest three zones each side on every chart; hover or tap one for its card; Layers → Auto levels hides them; `auto_levels` and each panel's `level_events` in `GET /charts/workspace` | `tests/test_chart_levels.py`, `tests/test_charts.py`, `frontend/e2e/charts.spec.ts` (automatic levels); [definitions](../charts-workspace.md#automatic-levels-c21) |
| Option chain adapter (Charts C4.1) | `app/engine/options_chain.py` (Tradier requests, parsing, 30/minute budget), `app/engine/options_models.py` (pure normalized models) | called by the C4.3 recorder and the chart's option feed below | `tests/test_options_chain.py`; live probe `scripts/check_options_chain.py`; [contract](../charts-workspace.md#option-chains-c41) |
| Options positioning, levels and ladder (Charts C4.2, C4.4, C4.5, max pain C4.7), the range bands (Charts C2.7) and the implied move (symbol info T2.1) | `app/engine/options_positioning.py` (pure: per-strike open interest and volume, walls, ranks, Black-Scholes dollar gamma, signed gamma and the flip, max pain, chart levels, scopes), `app/engine/options_implied.py` (pure: the at-the-money straddle and the expected-move levels), `app/engine/options_feed.py` (chain cache, cadence, background refresh, the 24-a-minute share, the once-a-session expected-move capture), `app/engine/chart_math.py` (`vwap_sd`), `ChartFeed._levels` in `app/engine/chart_feed.py` (strikes join the automatic levels before confluence); `frontend/lib/autoLevels.ts` (`shownZones`, tints, the strike highlight), `frontend/lib/optionsView.ts`, `frontend/components/charts/LevelCard.tsx`, `frontend/components/charts/OptionsLadder.tsx`, `frontend/components/charts/LayersPanel.tsx` (filters), `frontend/components/charts/SymbolInfoForecast.tsx` | `options=`, `ranges=` and `auto=` on private `GET /charts/workspace`; `GET /charts/options/{symbol}/ladder`; `GET /charts/symbol/{symbol}/forecast`; `/charts`: Layers → Options levels and Range bands, the Strike ladder dock tab, the Forecast tab | `tests/test_options_positioning.py`, `tests/test_options_feed.py`, `tests/test_charts.py`, `tests/test_symbol_info.py`, `frontend/e2e/charts.spec.ts` (options levels, strike ladder, range bands, max pain), `frontend/e2e/symbol-info.spec.ts` (Forecast); [definitions and assumptions](../charts-workspace.md#options-positioning-c42) |
| Background job ownership and recovery | `app/engine/job_runtime.py`, `app/jobs/worker.py`; commands in [background-jobs.md](background-jobs.md) | Sync Center, Gmail push, enrichment and Webull start routes | `tests/test_job_runtime.py` (competing processes, API restarts, worker death, queue consumption and fill dedupe/FIFO); external providers stubbed |
| PnL, FIFO, trade shape | `app/engine/reconstructor.py` | `POST /rebuild`; runs after every fill write and in `trade_rebuild` | `tests/test_reconstructor.py`; `test_seed_dev_data.py` (`EXPECTED`); `test_seed_snapshot.py` (golden snapshot over the seed) |
| Robinhood email parsing | `app/engine/email_parser.py` | — | `test_email_parser.py` |
| Gmail fetch and import | `app/engine/gmail_poller.py`, `app/routers/fills.py` | `POST /fills/import`, `POST /fills/resync-all` (destructive, needs `confirm`) | `test_gmail_poller.py`, `test_fill_import.py`, `test_environment_guard.py` |
| Gmail OAuth | `app/routers/auth.py` | `GET /auth/gmail/start`, `/auth/gmail/start/browser`, `/auth/gmail/callback` | `test_gmail_auth.py`, `test_cors.py` |
| Real-time Gmail import (Pub/Sub pull) | `app/engine/gmail_listener.py` (lane `gmail`), history cursor in `app/engine/gmail_poller.py`, `_import_gmail_changes` and `queue_gmail_push_pipeline` in `app/routers/sync.py`; setup in [deploy/README.md](../../deploy/README.md#real-time-gmail-import) | jobs `gmail_listener`, `gmail_push`, `gmail_watch_renew`; `POST /gmail/watch`, `GET /gmail/watch/status`, `POST /gmail/push` (same coalesced queue; nothing public calls it) | `test_gmail_listener.py` (fake subscriber), `test_gmail_realtime.py` (cursor, targeted fetch, coalescing) |
| Phone alerts (ntfy) | `deploy/alerts.py`, `deploy/systemd/tradejournal-alerts.*`; setup in [deploy/README.md](../../deploy/README.md#phone-alerts) | reads `GET /health`, `/gmail/health`, `/sync/runs` and `systemctl show` | `test_deployment.py` (grace periods, one alert per problem, recovery, merged pipeline failures, reboot); the deployment workflow runs the real unit against a loopback ntfy stand-in; live ntfy delivery is not tested |
| Gmail status banner and live refresh | `app/engine/gmail_health.py`; `components/GmailStatusBanner.tsx`, `lib/useGmailHealth.ts`, status line in `components/Nav.tsx` | `GET /gmail/health` (polled every 30s while visible; `data_version` drives `router.refresh()`) | `test_gmail_realtime.py` (health states); rendering is not in the browser suite |
| Polygon enrichment, greeks, indicators | `app/engine/enricher.py`, `app/engine/indicators.py` | `POST /fills/enrich?range=`, `GET /fills/enrich/status`; job `polygon_enrich` | `test_enricher.py` (incl. the discovered rate limit), `test_indicators_rvol.py`, `test_enrichment_gap_repair.py` (which empty fields are retried) |
| Alpaca fill context | `app/engine/alpaca.py`, `app/engine/alpaca_enricher.py`, `app/engine/behavior.py` (sequence metrics) | `POST /market-context/enrich?range=&force=`, `GET /market-context/enrich/status`, `/market-context/fill/{id}`, `/market-context/fills/bulk?ids=`, `/market-context/coverage`; job `alpaca_enrich` | `test_alpaca_context_repair.py`, `test_indicators_rvol.py` (the injected cache-only bar loader) |
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
| AI review | `app/ai/reviewer.py`, `app/ai/daily_reviewer.py`, `app/routers/daily_review.py` | `POST /trades/{id}/review`; `GET /daily-review`, `/daily-review/{day}`, `POST /daily-review`; job `daily_review` | — (Anthropic) |
| Webull | `app/engine/webull*.py`, `app/routers/webull.py` | `GET /webull/health`, `/webull/accounts`, `/webull/orders/recent`, `/webull/orders/{order_id}`, `/webull/events/status`; `POST /webull/events/test-ingest`, `/webull/events/start`, `/webull/events/stop`; job `webull_listener` | `test_webull_ingest.py`, `test_webull_events.py`, `test_webull_signer.py` |
| Strategy Lab (kept readable, not extended since 2026-10-02: [what comes next](../strategy-factory.md#what-comes-next)) | `app/engine/strategy_lab.py`, `strategy_csv.py`, `strategy_metrics.py`, `app/routers/strategy_lab.py` | listed under the screen above | `test_strategy_lab_routes.py`, `test_strategy_import_routes.py`, `test_strategy_run_reads.py`, `test_strategy_csv.py`, `test_strategy_metrics.py` |
| Isaac Market Map backtester | `app/engine/market_map.py` (pure historical strategy research rules), `app/engine/market_map_report.py` (cohorts, TradingView-shaped CSV, export parity), `scripts/backtest_market_map.py` (Alpaca bars, CLI) | — (`python scripts/backtest_market_map.py MU META --days 365`) | `test_market_map.py` (synthetic bars), `test_market_map_exports.py` (execution model vs the committed TradingView exports), `test_market_map_report.py`; entry parity on real bars is the script's `--parity` run, see `docs/pine/README.md` |
| Strategy factory | `app/engine/factory_data.py` (bars, splits, features), `factory_rules.py` (entry families, the shared execution model, specs), `factory_model.py` (learned filter), `factory_gates.py` (gates, ledger records), `factory_brief.py` (the weekly brief, proposal review, weekly report) — all pure; `scripts/strategy_factory.py` (bar cache, ledger file, CLI, the Claude call, ntfy); `../scripts/factory_week.sh` (the weekly run, from launchd, or by hand with a Claude Code session as the idea model: `.claude/skills/factory-week/SKILL.md`); specs in `research/specs/`, results in `research/ledger.jsonl`; the live ledger and the weekly reports are on branch `factory/ledger`, never merged | — (`python scripts/strategy_factory.py run ../research/specs/<spec>.json`, then `ledger`; weekly: phone summary) | `test_factory.py` (synthetic bars: execution model, families, gates, forward evidence, the data lock end to end), `test_factory_brief.py` (catalog, digest, evidence, review, report), `test_strategy_factory.py` (the script with a stub minute source and a stub idea model); see `docs/strategy-factory.md` |
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

- **Engine or router change:** the test module in the table, or drive the
  route through `TestClient(app)` the way `test_fill_import.py` does.
- **Anything a page shows:** `bash scripts/verify.sh --e2e`. The smoke tests
  (`frontend/e2e/smoke.spec.ts`) open `/`, `/trades`, `/trades/{id}`,
  `/fills`, `/analytics`, `/daily`, `/strategy-lab` against a seeded backend
  and assert the values from `EXPECTED` in `scripts/seed_dev_data.py`. Then
  open the route on the dev server (`bash startdev.sh`, port 3000) and say
  what you saw.
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
  and fails at 30; `tests/test_docs_links.py` checks names and anchors. The
  judgement half is `.claude/skills/docs-drift/SKILL.md`. It runs unattended
  every Saturday: launchd on the development Mac starts
  `scripts/docs_drift_week.sh` in `/Users/user/TradeJournal-docs`, a checkout
  kept at `main`. From 20 code commits on, the script has Claude run the pass
  headless, with the key in the main checkout's `backend/.env` and a $20 cap.
  Claude may edit only documentation, and anything needing permission is
  refused rather than waiting for a person. The script then checks the
  changes and the marker, runs the docs tests, pushes `docs/drift-<date>` and
  opens a pull request. The phone hears about the pull request, one still
  waiting for review, or a failure. Proof: `tests/test_docs_drift_script.py`.
  The desktop scheduled task that ran it before stalled on a permission prompt
  on its first run (2026-09-26) and is disabled.

## Reference documents

- `docs/tradingview-webhook-contract-v1.md` — frozen wire contract
- `docs/tradingview-signal-loop-plan.md` — staged plan for the signal loop
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

## A3 daily Practice routine

Today and Daily Review mount `frontend/components/PracticeRoutine.tsx`: manual
preparation, frozen contexts, validated immutable choices, explicit reveal,
A2 arming, outcome/coverage review, feedback and actual attention timers.
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
