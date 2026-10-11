# Seeing the UI: pictures, the sandbox, safety

Three ways to look, cheapest first. If `frontend/node_modules` or
`backend/.venv` is missing (fresh clone, worktree, cloud session), run
`bash scripts/setup.sh` first, or every check fails on missing tools.

| Need | Use |
|---|---|
| Layout, overlap, clipping, states, phone vs desktop, before/after | 1. browser-test pictures |
| How a real session reads: clutter, label collisions, studies over candles | 1. the realistic-candle test, then 3. the sandbox |
| Hover, drag, menus, settings changes, whole-task walks | 3. the sandbox |

## 1. Pictures the browser tests take

```bash
cd frontend && npx playwright test e2e/charts.spec.ts -g "realistic candles"
find test-results -name '*.png'
```

- Each run builds the app and starts its own seeded backend (8099) and
  frontend (3099): about 20–30 s for a few tests. Candles are stubbed and
  chart settings use an in-memory fake (`e2e/fixtures/chartSettings.ts`), so
  it is deterministic, needs no keys and cannot touch real data.
- Most chart tests use a smooth sine-wave fixture: right for asserting
  prices, useless for judging how price action reads. The test named
  "realistic candles" uses `e2e/fixtures/realisticBars.ts` (a seeded,
  market-shaped session with real EMA/VWAP/RSI and fills) and saves
  `charts-realistic-desktop.png` (1440×900) and `charts-realistic-phone.png`.
  Use `realisticPanels()` in any new test whose picture a person will judge.
- Which test saves which picture: `grep -n "outputPath(" e2e/*.spec.ts`.
  A failing test also leaves `test-failed-1.png` and a trace in its folder.
- `test-results/` is wiped on every run: copy baseline pictures to your
  scratch directory before running again.
- Ports busy: `E2E_BACKEND_PORT=8199 E2E_FRONTEND_PORT=3199 npx playwright
  test ...`. Never run two suites on the same ports, and never stop another
  checkout's servers.
- On a pull request that changes `frontend/`, CI's Screenshots comment
  shows every saved picture, grouped by spec file and screen size.

## 2. A picture no test takes yet

Add it to the nearest existing test of that area, not a new harness:
`await page.setViewportSize({ width: 390, height: 844 })`, then
`page.screenshot({ path: test.info().outputPath("dock-sheet-phone.png"),
animations: "disabled" })`, or `locator.screenshot(...)` for a crop. Chart
tests need the candle `stub()` or the route in the realistic test, both in
`e2e/charts.spec.ts`; add chart pictures in that file. Keep the screenshot if
it shows a state the change introduced (it will appear on the PR); remove a
throwaway one before committing. Pair each picture with at least one
assertion on the fact it is meant to show.

## 3. The UX sandbox: real candles, nothing real to break

```bash
bash scripts/ux_sandbox.sh        # run in the background; ready in ~10 s
```

- Real candles, quotes, news and automatic levels from the market-data keys
  in the main checkout's `backend/.env` (or `--keys-from FILE`; `--no-keys`
  for records only). Nothing else from that file is loaded.
- Its own seeded SQLite file (`backend/data/ux_sandbox/`) and its own ports:
  app at `http://127.0.0.1:3098`. Toggling studies, saving layouts, adding
  levels, drawings or plans changes only that file — never the user's
  devices. Gmail, Webull, phone alerts and practice jobs are off.
- It refuses to start in a checkout with its own `backend/.env` or `.env`
  (use a worktree), or on busy ports, and stops itself unless the app's
  `/api/backend/health` reports `ux_sandbox.db`.
- The first `/charts` load takes ~15 s (dev compile plus provider fetch).
  The app runs as `next dev`; for performance numbers compare like with
  like, and confirm anything that matters on the production build.
- Drive it with the Claude desktop app's built-in browser pane, or any
  Playwright-capable browser tool or short script. Claude in Chrome on this
  setup drives a different computer and cannot reach this Mac's localhost.
- Ctrl+C (or stopping the background task) stops both servers. Delete
  `backend/data/ux_sandbox/` to start over.

## Safety outside the sandbox

The user's own app (`bash startdev.sh`, ports 8080/3000) is connected to real
records. If you must look there, first `curl -s localhost:8080/health` and
then only look:

- No Sync, rebuild/resync, saved plans, alerts, fill edits or trade links.
- No chart setting changes — studies, levels, drawings, watchlist, layouts
  and panel proportions save through `PUT /charts/settings` and reach every
  device the user owns. Use the sandbox for that.
- Pictures of real records show account values and P&L: keep them in the
  session; do not attach them to issues or PRs. Sandbox and test pictures
  show only seeded records and are fine to share.

## Reading pictures well

- Every image read costs tokens. Read only the target surface: one whole
  screen plus at most one crop per state, desktop and phone. Prefer a
  `locator.screenshot` to a full page when the question is local.
- Candles, lines and price-axis labels are drawn on a canvas: only a picture
  shows them. Toolbar, dock and table chrome is DOM: check it in the test
  instead of by eye — overlap with `boundingBox()`, clipping with
  `scrollWidth > clientWidth`, errors with `page.on("pageerror")`.
- Base and branch pictures are never pixel-identical (the status bar shows a
  live clock and quote age; `docs/agent/verification.md`, Browser tests).
  Compare the same test at the same viewport by eye and by DOM facts.
- Name pictures `<surface>-<state>-<desktop|phone>.png` so the PR comment
  reads as a before/after story.
