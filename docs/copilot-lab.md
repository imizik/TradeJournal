# Copilot Lab

An owner-only experiment: does a Claude conversation embedded in TradeJournal
help the owner's research workflow more than hosted Trader Jo? It is a
read-only sparring partner. It never trades, and it saves a plan, alert,
revisit or memory only when the owner confirms a proposal card (below). Its
background research queue and its phone pings are off by default.
Trader Jo, follow-ups, price watches, Shadow and MCP work are separate and
untouched, except that a confirmed memory is saved as one of Jo's memories
(`POST /jo/memories`).

## What runs

- `GET /copilot/status`, `POST /copilot/chat` (Server-Sent Events) and `POST /copilot/transcribe` in
  `backend/app/routers/copilot.py`. The frontend page is `/copilot-lab`
  (`frontend/components/copilot/CopilotLab.tsx`), laid out as the desk (below). It is in the nav ("Copilot") only for the owner while the lab is on.
- One conversation component, `frontend/components/copilot/CopilotPanel.tsx`.
  It is the full page (`variant="page"`, `CopilotLab.tsx`: the desk's
  conversation, history, deep links) and the panel beside other pages (`variant="panel"`).
  Both share investigations, proposals, Research deeper, What changed? and
  linked activity. A panel renders nothing for the assistant profile or while
  the lab is off.
  - The nav, every panel and every Ask copilot button share one
    `/copilot/status` read per page load (`lib/copilot.ts` `copilotStatus`,
    `useCopilotOn`).
- **Hold to talk** (`frontend/components/copilot/VoiceInput.tsx`, every
  variant): a 44 px mic beside Send, shown only while the lab is on and
  something can listen.
  - Press and hold to talk, release to transcribe. A short tap switches to
    tap-to-stop. Sliding off the button, Cancel, a hidden page or closing the
    panel drops the clip unsent. A clip stops at 30 seconds and is
    transcribed. A live timer shows while it listens. A refused microphone
    says how to allow it.
  - "Auto-send what I say" (default on, remembered in this
    browser) sends the words as soon as they are transcribed, after anything
    already in the box. Off, or while a turn is running, the words wait in
    the box with "Review the message, then Send."
  - `POST /copilot/transcribe` (owner-only like every `/copilot` route)
    takes either `audio` (with `audio_ms`), capped like voice plans at
    3 MB and 30 seconds, or `text`. Audio goes to the voice-plan Whisper
    transcriber (`app/engine/transcribe.py` `transcribe_bytes`). Whisper is
    primed with the owner's most-traded tickers, then Radar's. The clip
    sits in a temporary file only while it is read. Neither audio nor words
    are logged or stored. `text` is what the browser's own recognition
    heard: when `GET /copilot/status`
    `capabilities.transcriber.configured` is false the page uses
    `webkitSpeechRecognition`/`SpeechRecognition` instead (iOS Safari has
    it). With neither, there is no mic. An unconfigured server answers 503
    with the reason.
  - Spoken tickers (`app/engine/spoken_tickers.py`): "N-B-I-S", "en bee eye
    ess", "en bis", "N-BIS" and company names ("Nebius", "applied digital")
    become the symbol when it is in Radar's universe or the owner's traded
    tickers. Names come from the AI buildout seed. A phrase changes only
    when exactly one known symbol fits, so "I see you are why" and
    "coherent" stay as heard.
- **Read it back** (`frontend/components/copilot/SpeakAnswer.tsx`, every
  variant): a 44 px speaker beside the mic reads each finished answer aloud
  with the browser's own `speechSynthesis`. No server call is made. It is
  off by default and remembered in this browser (`copilot.speak`), with a
  Voice speed of 0.9×, 1.0× or 1.2× (`copilot.speak-rate`) beside the
  auto-send setting. The device's default English voice reads.
  - Speech starts when the turn's `done` event arrives, never on partial
    text. `lib/copilot.ts` `speechText` prepares it: markdown and the
    simulated-model head are dropped, and list items become sentences.
    Tickers are spelled ("N B I S"), prices become dollars and `95C` becomes
    "95 call". Tool rows and the metrics line are not part of the answer's
    text. A card adds one closing sentence ("There is a plan card to
    confirm."). Nothing is ever confirmed by voice.
  - A new turn, pressing the mic (before it listens), a hidden page or
    closing the panel stops speech at once. A tap on the speaker while it
    reads stops that answer and leaves it on. With auto-send and the
    speaker both on, the loop is hold to talk, hear the answer, hold again.
    A browser without speech synthesis shows no speaker.
- Entry points (nothing is ever sent until the owner presses Send):
  - **Plan a trade** (`frontend/components/copilot/PlanATrade.tsx`): the
    primary-styled way in, so an impulse gets pressure-tested before the
    entry. It deep-links (below) with `Plan a trade: <what the page knows>`
    as the context, owner-only and only while the lab is on:
    - Charts: in the toolbar beside the symbol and price, desktop and phone,
      with `<symbol> from the <interval> chart at <price>`.
    - Radar: first in an event's detail, ahead of "Ask copilot", with the
      event's time and summary.
    - Dashboard: at the top, beside Sync. Phone: a lit "Plan" tab beside
      Charts in the bottom tab bar. With no symbol, the context is just
      `Plan a trade:` and the owner names the ticker.
    - Charts' Plan trade sheet: "Pressure-test with copilot" beside Save
      plan carries what is chosen and typed so far (side, contract, note,
      template wording), cut to 300 characters. It leaves the sheet unsaved.
  - **Nav:** "Copilot" opens `/copilot-lab`. It is owner-only, shown only
    while the lab is on.
  - **Charts:** a "Copilot" tab in the side dock, beside the watchlist, layers
    and ladder. It uses the dock's width and divider, and on a phone it is
    the dock's bottom sheet.
    - It opens on the chart's symbol, resuming that symbol's latest open
      investigation, or starting one with `Context: Charts · <symbol>
      <interval> chart` in the message box.
    - When the chart's symbol changes, an empty panel follows. A
      conversation is never retargeted: the panel offers "Switch to <symbol>"
      or "Keep <symbol>" (Switch waits for a turn in progress).
    - A follow still loading when the owner sends is dropped, and a draft
      the owner typed is never replaced.
    - Closing a panel mid-turn (the dock tab, the sheet, Radar's drawer, or
      leaving the page) stops the turn and saves what had arrived.
    - Above the conversation, for the chart's symbol only
      (`frontend/components/charts/CopilotLoop.tsx`, owner-only
      `GET /copilot/symbol/{symbol}`): its open position with the plan it was
      entered under (contract, P&L now, invalidation distance, time stop,
      give-back state), its armed plans not yet in a position (distance to
      entry and invalidation), and one line of what is new on it (a Radar
      event since the last Radar visit, or a thesis trigger fired today). The
      same read's `last_exit` (the symbol's newest answered exit review) feeds
      the plan card's lesson line; the dock does not show it. Each
      is a dock section with its count, folded per device; an empty one is
      left out. A position opens its review (`Review this position: <trade
      id>`), a plan its investigation, and the new line a conversation about
      it with its origin, all in the panel and unsent. The route composes the
      Plans board, the Plans card and the Today screen's readers in-process,
      each section on its own (`unavailable` when its source fails), with one
      quote read for that symbol; the tab reads it on opening and every
      minute while open and visible.
    - **Plan a trade** there starts a new conversation with `Context: Plan a
      trade: <symbol> from the <interval> chart at <last price> · nearest
      automatic levels: above …, below …` (the chart's own automatic zones, so
      the copilot drafts levels without a chart read) and origin `chart`. The
      toolbar's Plan a trade still opens the lab.
    - **Plan this** (draw the plan; `frontend/components/charts/PlanFromDrawing.tsx`,
      pairing in `frontend/lib/drawPlan.ts`): two price levels drawn or
      selected on the main chart open this tab in place with `Context: Plan a
      trade: <symbol> from the <interval> chart, last <price>. Entry trigger
      <price> (my drawn level "<name>"). Invalidation <price> (my drawn
      level). Draft the plan around these levels; argue if they are wrong.`
      (one level: the invalidation, and the copilot drafts the trigger), with
      origin `chart`. The drawn prices also ride along structurally, so the
      plan card marks each price "From your drawing", or "Changed from your
      drawing: <price>" when the draft differs, and says so when the draft's
      side is not the one drawn. On Confirm the card tells Charts
      (`tradejournal:plan-confirmed`), which labels the drawn levels "Entry
      trigger" and "Invalidation" and draws the plan's alert bells; see
      [the Charts doc](charts-workspace.md#implemented-behavior).
    - **Explain this candle** (the chart menu on the main chart: right-click,
      or a long press on a phone) opens this tab in place with `Context:
      Explain this candle: NBIS 5m at 10:41 ET (O 94.10 H 94.60 L 93.95 C
      94.35, vol 41k, RVol 1.3). What moved it, and what did I do here?`
      (`on <date>` after the time for an earlier session's candle) and
      nothing sent; that conversation's first Send also attaches the chart
      as Look at my chart does (Explain this candle, below).
    - Charts' Symbol info Overview tab also keeps its "Ask copilot" link into
      the lab.
  - **Radar:** "Ask copilot" in an event's detail opens the same panel in
    place, as a right-hand drawer (full screen on a phone), on the event
    symbol, with its one-line summary as the context. Escape or the backdrop
    closes it, and focus returns to the button.
  - **Deep link:** `/copilot-lab?symbol=X&context=<short text>` opens a new
    investigation with the symbol set and `Context: <text>` (at most 300
    characters) in the message box. `&plan=trigger:95.90,invalidation:92.30,side:long`
    (no `trigger` part for an invalidation alone) carries drawn levels to the
    plan card as Plan this does; a malformed one, or a long whose trigger is
    not above its invalidation, is dropped.
  - **Trade page:** a closed trade offers "Review with copilot" next to
    "Open on chart", which deep-links with `Review this trade: <trade id>` as
    the context; an open one offers "Ask copilot about this position" with
    `Review this position: <trade id>` (Review a trade or position, below).
  - **Position alerts:** a position alert push's answer actions (Prompted
    review, Already aware) open the trade page, whose primary action is "Ask
    copilot about this position", prefilled with the alert's numbers (Review a
    trade or position, below).
  - **Phone:** the unplanned-entry nudge (`PLAN_NUDGE_ENABLED`) deep-links here with
    `Plan this position: …` when a new position has no plan. When a saved plan
    is suggested for the fill it sends a link ping instead, whose confirm page
    (`/plans/link`) offers the same **Plan it now** link after "Not this plan"
    (see the [feature map](agent/feature-map.md), "Plan pings for new positions").
  - Browser proof: `frontend/e2e/copilot-entry.spec.ts` (including a 375 px
    phone check), `frontend/e2e/copilot-panel.spec.ts` and
    `frontend/e2e/copilot-review.spec.ts`.
- **Thread list**, the desk's left pane (page only, lab on;
  `components/copilot/ThreadRail.tsx`). One grouped list, in `DESK_GROUPS`
  order, with one line for the day above it: the market phase, how many rows
  need a decision, and the plan streak. Each group's heading carries a
  coloured dot (rose Act now, sky Near a trigger and New, amber Waiting for
  you) and its row count. Groups:
  - **Pinned**: the Briefing only (today's pre-market prep when there is
    one). Pressing it sends one turn, the fixed **What matters right
    now?** prompt (`lib/copilot.ts` `WHAT_MATTERS_PROMPT`, "What matters
    right now across my open positions, armed watches and open
    investigations? Lead with anything that needs a decision today; say
    plainly if nothing does."). Review my week is in ⌘K and on the
    Briefing (beside Watch today); the server's pinned week row is not
    listed. Opening the list never sends.
  - **Act now**: open positions the Today screen flags (within 1% of an
    armed invalidation or past a hit one, expiring today, give-back fired,
    time stop within 30 minutes). Empty, it says "Clear. Nothing needs a
    decision right now.", or that positions are unavailable. A `decision`
    day-journal entry for the symbol logged today moves the row to Watching,
    unless the invalidation was hit after it.
  - **Near a trigger**: armed plans not yet in a position within 1% of their
    entry or invalidation.
  - **Waiting for you**: the owner's open conversations with plan or alert
    cards (`trade_plan`, `watch`; a plan card carries its time stop) still
    waiting on Confirm or Dismiss, read from each saved transcript (a card
    with no `outcome`), newest first. The value is "N to confirm" (amber),
    the status the first waiting card ("Alert · APLD crosses 31.20", "Plan ·
    APLD long calls · entry crosses 31.20"). A row opens the conversation in
    place, on its cards: only a card's own Confirm makes anything. A
    conversation already shown as an armed plan or a position stays there,
    a waiting one leaves Watching, and a research job's cards are not read.
    Hidden when nothing waits.
  - **New since you looked**: Radar events since the last Radar visit and
    the newest thesis-watch trigger today per investigation, one row per
    symbol (a Radar hit ahead of thesis news, newest first), five shown and
    the rest behind "+N more". What the owner has opened or marked seen is
    remembered in this browser only (`localStorage`); seen rows stay,
    dimmed, and opening a symbol's row sees its folded rows too.
  - **Watching**: every other open position (its plan's nearest line, "Fill
    to link" in amber when a saved plan is suggested for its fill, or "No
    plan yet"), armed plan and open investigation (a research job's
    conclusion is never shown: a model that read web pages wrote it); three
    shown and the rest behind "+N more", so a busy day reads as about ten
    rows.

  **All | Plans** under the day line switches the list to the **Plans**
  view and back; the choice is remembered in this browser (`localStorage`),
  and on a phone it sits inside the Now tab. The Plans view lists every plan
  from the same read (`plans` in `GET /copilot/desk/threads`), grouped
  **Armed**, **In position** (a fill waiting to be linked counts), **Exited
  this week** (its exit review waiting) and **Done this week** (the
  `plan_done` text: Exit reviewed, Exit review skipped or Marked done), the
  last two over the last seven days. One row each: symbol, instrument
  (contract, direction or stock), horizon, and on the right the distance to
  the entry (armed) or where the underlying sits in units of the plan's risk,
  `R`, 0 at the entry and −1 at the invalidation (in position); under it
  the entry, invalidation and time stop, or the distance to the invalidation.
  The tab's count is the armed and in-position plans. A row opens its thread
  in place; a done plan whose alerts and time stop were all deleted has no
  saved thread to find and opens by its symbol.

  Under the groups, a collapsed **Closed this week** footer with its count:
  saved conversations closed and last touched since Monday (New York), from
  the latest 50 in `GET /copilot/investigations`, each opening in place; then
  the key hint.

  Each row: symbol, instrument (contract, direction or "research"), one value
  and one status line coloured by what it needs (amber: needs you). A
  position's value is its own unrealized P&L, an option's from its own mark;
  its plan levels are on the underlying, named in the status line. Only Act
  now and Near a trigger rows carry a plan meter: the underlying on the track
  from the invalidation (left) to the entry (the tick), with room past it.
  Empty groups other than Act now are left out. A row with an investigation
  opens it in place; any other follows its link (a stock Radar hit opens the
  desk on its decision, `/copilot-lab?symbol=<symbol>&radar=<id>`; a group
  event its `/radar?event=<id>`; a position with a fill to link the desk on
  its symbol, `/copilot-lab?symbol=<symbol>`; planning an unplanned position;
  a trade). **Plan a
  trade** sits under the groups. It refreshes every minute while visible and
  reads one owner-only `GET /copilot/desk/threads`
  (`app/routers/copilot_desk.py`), composed in-process from the Plans board
  (`copilot_plans.board`), `plan_positions.positions` with the Today
  screen's Act now rule (`today._act_now`), the open investigations, today's
  day journal, the Today screen's Radar, thesis-watch, prep and week readers,
  and the market calendar for the phase, sharing one batched quote read.
  Each source stands alone: one that fails reads `unavailable` and the list
  names it. Read-only: no Radar visit, no pings. The only ids out are the
  investigation, trade and Radar event ids its rows link to. Browser proof:
  `frontend/e2e/copilot-thread-list.spec.ts` (with a 375 px phone check) and
  `frontend/e2e/copilot-home.spec.ts`; route tests:
  `tests/test_copilot_desk.py`.
- **Plans board read** (`GET /copilot/plans`, `app/engine/copilot_plans.py`):
  one row per confirmed copilot plan that is still armed: its entry or
  invalidation alert is armed, its time stop is pending, or the fill linked
  to its pre-trade plan is an open position. Each row has the symbol and
  direction, the thesis, the last price, the distance to the entry and to the
  invalidation in % and $ (or when it was hit), the time stop, and the fill:
  in position, fill to link (a matching open trade not yet linked to the
  plan), or waiting, and `confirmed_at` (epoch seconds of its newest part,
  which the desk compares with a `plan_done` entry). Rows sort nearest to an
  armed trigger first. It reads
  the `plan_role` alerts and time stops by investigation, the plan capture
  (the time stop's `client_id`, else the newest "Copilot plan" capture for
  the symbol made with them), its capture link, and one batched quote read
  (`chart_feed.quote_rows`, as `GET /copilot/quote`). An investigation with
  several plans shows its latest: the parts made within ten minutes of the
  newest. The only id out is the investigation's. A plan whose alerts have
  all fired or been deleted and with no open position drops off, and still
  shows in its investigation (Linked to this investigation). The desk's
  thread header reads the route; the thread list, the Charts dock and the
  Today screen read the board in process; route tests:
  `tests/test_copilot_plans.py`.
- **Plans card on the Dashboard** (`components/dashboard/PlansCard.tsx`),
  near the top of the owner Dashboard above Exit habits, owner-only and shown
  only while the lab is on. One row per open position (Webull left out): the
  contract, open P&L in $ and %, then the plan it was entered under:
  "Invalidation 92.30 · 2.1% away" (or "hit"), "Time stop 15:30 · 41 min",
  "planned late" when the plan was saved after the fill, and the give-back
  watch (armed or fired) with the latest open-trade alert. A position with no
  plan says "No plan" with **Link plan** (the one-tap `/plans/link` page) when
  a saved plan is suggested for it, else **Plan it** (the same deep link as the
  unplanned-entry nudge). A tap on the row opens its position review
  (`Review this position: <trade id>`). With nothing open it says so beside the
  **Plan a trade** button. It refreshes every minute while visible and reads
  `GET /copilot/plans/positions` (`app/engine/plan_positions.py`): positions
  marked as `copilot_book.position_rows` marks them, the oldest linked plan
  capture, its plan card's invalidation alert and time stop (by the capture's
  investigation, made within ten minutes of it), one batched underlying quote
  read for the distance, and `position_alerts.for_trade`. The only id out is
  each row's trade id. Browser proof: `frontend/e2e/dashboard-plans-card.spec.ts`
  (with a 375 px phone check); route tests: `tests/test_plan_positions.py`.
- **Today** (`/today`, `components/today/TodayView.tsx`): the owner's phone
  landing page, the first phone tab and ahead of Dashboard in the sidebar
  (Dashboard stays in the phone's More menu). One column, top to bottom, each
  section collapsed to its count when empty:
  - **Act now**: open positions within 1% of an armed invalidation (or past a
    hit one), expiring today, with the give-back alert fired, or with a time
    stop due within 30 minutes.
  - **Plans near a trigger**: armed plans not yet in a position within 1% of
    their entry or invalidation.
  - **New since you looked**: Radar events since the last Radar visit,
    thesis-watch triggers fired today and today's pre-market prep.
  - **Held back**: pings the notification policy held today (merged, quiet
    window or over the cap), with their text.
  - **Your week so far**: this week's planned/total entries and the streak.
  - Then **Plan a trade** and **Review my week**.

  A position row opens its review (`Review this position: <trade id>`), a plan
  or trigger or prep its investigation, a Radar event `/radar?event=<id>`. It
  shows its as-of time and refreshes every minute while visible. While the lab
  is off the page still reads; a position opens its trade page instead and the
  other copilot links and both buttons are left out. It reads one owner-only
  `GET /today` (`app/routers/today.py`) that composes the readers above in
  process (`copilot_plans.board`, then `plan_positions.positions`, sharing one
  batched quote read), the Radar feed reader, `ThesisWatchTrigger`,
  `PremarketPrep`, `PhonePing` and `plan_streak.streak`. Each section stands
  alone: one that fails reads `unavailable` and the rest stand. Read-only: it
  records no Radar visit and sends nothing. The only ids out are the trade,
  Radar event and investigation ids its rows link to. Browser proof:
  `frontend/e2e/today.spec.ts` (375 and 1440 px); route tests:
  `tests/test_today.py`.
- **Open threads read** (`GET /copilot/threads`): `{positions,
  investigations, watches, as_of}` from the no-symbol owner context pack
  (Owner context, below), each open investigation with its last three
  thesis-watch triggers. The desk showed it before the thread list replaced
  it; no page reads it now. A position is cut to symbol, instrument,
  unrealized %, give-back state and its clocks: no account, entry, mark or
  captured plan. Memories and habits are never returned, and the only ids are
  investigations'. It is a page read, not a turn, so the pack's size cap does
  not apply (`owner_context(None, bounded=False)`); each section keeps its row
  caps. Fixture mode serves the simulated pack. Replay says it is unavailable.
- `GET`/`POST /copilot/investigations` and `GET`/`PUT /copilot/investigations/{id}`
  hold saved investigations (below).
- All these routes are owner-only: they are in no assistant grant
  (`backend/app/access_manifest.py`), and `frontend/lib/backendProxy.ts`
  refuses `copilot` for the assistant profile.
- One turn (`backend/app/ai/copilot.py`) streams the answer and lets the model
  call seventeen read-only tools (`backend/app/ai/copilot_tools.py`): Radar group
  comparison, peer moves, symbol news, earnings dates, quotes, saved research,
  investigation changes (below), the chart and book tools below (including the
  trade review and the week review), option candidates (below), one moment on
  the chart (Explain this candle, below), and the owner
  context pack for another symbol (Owner context, below). It can
  also call `propose_plan`, which writes nothing (see Confirm a plan). Each tool
  reads an existing service in-process and returns a compact result with its
  source and as-of time. No market math is reimplemented.
- **Chart and book tools** (`backend/app/ai/copilot_book.py`):
  - `get_chart_context(symbol, timeframe 1m/5m/15m/1h/1D)` reads the same
    `chart_feed.workspace` as the Charts page. It returns:
    - the last 40 bars (New York times; OHLC, volume, relative volume,
      extended-hours flag);
    - the nearest three automatic level zones each side, with their
      tested, broken or reclaimed state;
    - the latest bar's VWAP and its 1σ band;
    - the relative-volume baseline;
    - the quote row: session open, high and low, and the previous close.
  - `get_positions()` lists open journal positions through
    `chart_journal.positions`, marked by the dashboard's quote engine: option
    mid, or the stock price. Each has stock or option (side, strike, expiry),
    quantity, average entry and mark (options per contract, i.e. premium ×
    100), unrealized $ and %, and days held. At most 15 are shown.
  - `get_trades(symbol, limit ≤ 10)` lists recent closed trades in one symbol,
    newest first: entry and exit time and price, P&L in $ and percent of the
    premium paid, hold time and up to 4 tags of at most 24 characters.
  - `get_trade_review(trade_id)` reviews one closed trade or open position
    (`backend/app/ai/copilot_review.py`; Review a trade or position, below).
  - `get_week_review(week_start?)` reviews one trading week (Review my week,
    below).
  - `get_level_history(symbol, level, side, entry?, lookback_days?)` or
    `(symbol, minutes, lookback_days?)` replays the owner's own closed trades
    in the symbol at a level like the one being drafted (Your history at this
    level, below).
  - Journal times (`opened_at`, entry and exit) are New York wall-clock times,
    emitted with their offset (for example `-04:00` in summer, `-05:00` in
    winter), never as UTC. Days held count from that moment. Option marks
    are read in one batched quote call before the per-contract cache reads.
  - `get_memories(limit ≤ 10, symbol?)` lists the owner's approved (active,
    not redacted) Jo memories, read through `jo_briefing.memories`; with a
    symbol, that symbol's first and then the general ones. It never writes
    Codex's store.
  - No account number, account id, broker id, trade id or fill id is ever
    returned. An account appears only by its name, with digit runs removed.
    Webull is left out (dormant).
  - The fixture serves simulated versions. In replay, the chart is
    unavailable (the snapshot has no bars) and so is the book.
  - Research jobs never get `get_positions`, `get_trades`, `get_memories`,
    `get_trade_review`, `get_week_review` or `get_level_history`: a job reads
    untrusted pages and can fetch URLs, which could carry the book out. Those
    aren't even registered for a job; `get_chart_context` is allowed.
    `get_option_candidates` and `get_moment` are kept out too: the job
    allowlist (`research_job.JOB_TOOLS`) grows only by decision.
- Limits per turn: 4 model rounds, 8 tool calls, a 10 s timeout per tool,
  120 s per turn, and 6,000 characters per tool result. Tool inputs are
  validated (ticker pattern, at most 8 symbols, no extra keys).
- The browser sends text-only history: at most 24 messages, 4,000 characters
  each, 40,000 in total. Tool results are never accepted from the browser.
  Evidence is re-read when the model needs it.
- The answer streams as `text` events. While nothing else is visible, a quiet
  status line shows the model's progress notes (`progress` events, from
  `thinking: {type: "adaptive", display: "updates"}` with the
  `thinking-display-updates-2026-08-18` beta) or what the turn is doing
  ("Reading evidence…", "Weighing the evidence…"). It disappears when the
  answer starts.
- Prompts and answers are never logged; they are stored only as a saved
  investigation. One metrics line per turn is
  logged: model, first feedback (first progress note, tool call or answer
  text), first text, longest wait between visible events, total latency, tool
  names, tokens and estimated cost. The UI shows the same metrics inside each
  answer's folded Sources line.

## The desk

The full page is a desk of three panes beside each other
(`frontend/components/copilot/CopilotLab.tsx`, layout and look in
`CopilotLab.module.css`):

- **Threads**: the thread list (above). It stays in view while a
  conversation runs; a row or a pinned question opens or asks in the
  conversation beside it, through the panel's `desk` hand-off.
- **Conversation**: the page variant of `CopilotPanel.tsx` in `desk` mode. Its
  message box stays in reach while the conversation scrolls. One quiet line
  says what answers and on what data (the simulated model, simulated or replay
  data, the API budget, a missing key), with **New** and a **…** menu (the
  thread's one-line conclusion or lesson, Save, Close thread / Reopen, and
  Mark plan done on a plan's thread; see Plans end below) at its end. There is no Recent row (the thread list does that) and no Symbol box:
  the message box carries a scope chip, "About NBIS ×", where × asks across
  everything and "add a symbol" scopes it again. Above the box, two to four
  suggestion chips from the thread's state: **What changed?** (a saved
  conversation; one turn), **Look at my chart** (sends the Context pane's
  picture of today with the plan's lines; one turn), **Size it** (a plan card
  in the thread; fills the box unsent, the owner adds the dollars at risk),
  **Close with a lesson** (opens the menu on the conclusion), and for a fresh
  conversation "Is NBIS's group confirming?" and **Plan a trade**. Below
  768 px the box takes the full width; attach and read-aloud wait behind
  **+** (the speaker stays out while it reads, so its Stop is in reach),
  and the mic is the main round button (48 px) beside Send, above the tab
  bar. Each answer leads with its verdict and headline (see How the
  copilot reasons) and folds what it read into one **Sources · N** line that
  still names anything unavailable, stale, partial, simulated or a replay
  ("Sources · 4 · 1 unavailable · simulated"); opening it lists each source
  and the turn's model, timings and cost. The panel beside Charts and Radar
  keeps its own header and composer, with the same answers and Sources line.
  Above the conversation, the
  open thread's header (`ThreadHead.tsx`): a status chip (In position,
  Armed, Draft · not armed, Not planned), the Horizon menu for a position or
  a plan (see Horizon below), one meta line (an option's strike,
  expiry and days left, or a stock's days held), the symbol, the thesis on
  one truncated line (full text on hover) and the price. An option shows its
  own mark (a share's premium; the journal keeps a contract's) and P&L %,
  with "NBIS 87.74 · underlying" beneath, so the underlying's price is never
  read as the option's; a stock shows its last price, P&L % and average cost.
  Under it, the plan ladder (`PlanLadder.tsx`): one scale from the
  invalidation through the entry to 1R and 2R past it (R is the
  entry-to-invalidation distance; plans have no target, so these only
  measure), the live price, "3.1% above invalidation", the current R multiple,
  one quiet line with the time stop or expiry, and the rest (alert conditions,
  1R in dollars, entry premium, size, open P&L) behind Details. For an option
  the levels are the underlying's, said in its title. `compact` draws it as
  one line (invalidation · bar · 2R), `dimmed` for a plan not armed yet.
  Both read `GET /copilot/plans` (the plan is the row for the open
  investigation) and `GET /copilot/plans/positions` (the open position in its
  symbol, matched by the plan's invalidation; none for an armed plan not yet
  entered), once a minute; a thread with no plan shows only the header.
- **Context**: the open thread's symbol, "today" and Open in Charts →, with
  three small tabs (`components/copilot/Inspector.tsx`, reads in
  `backend/app/engine/desk_context.py`). A thread that names a symbol with no
  saved conversation (a position or plan from the thread list, a `?symbol=`
  link, a Radar hit) reads them by the symbol at once, as `symbol:<SYMBOL>` on
  the same routes: its plan's lines when it has one (in a position first, else
  armed), else the fills of its open trade; once a conversation is saved the
  pane reads by it.
  Each tab reads only when opened and again when something is confirmed in the
  conversation; nothing here arms or sends.
  - **Chart** (first): the server's ping picture of the symbol
    (`GET /copilot/desk/{id}/picture?timeframe=`, `chart_render`) with
    timeframe buttons **2m** (the default: today's minute bars from the same
    cached chart-feed read as a ping, the regular session once it has bars),
    **15m** (regular-session 15-minute bars of today and the two completed
    sessions before it, those from the chart history: disk, or fetched once
    and stored) and **1D** (the last 120 days of the chart feed's daily bars).
    The intraday views carry the plan's entry (TRIG) and invalidation (INV)
    lines, the owner's fills in the symbol today (amber, IN and OUT; an option
    fill at the underlying's recorded price, else a line at its time; a
    pre-market fill is left off once the regular session shows), the phone
    pings sent today on the symbol (violet, first labelled PING; the session
    strip's ping reader) and today's Radar hits on it (blue, first labelled
    RADAR; the Radar store read-only, none when it is off or missing), each
    on the bar of its time, so an alert can be judged against what price did
    next. 1D has no marks. A legend under the picture names fills, pings and
    Radar. No bars, a failed read, a read past 6 seconds, or both workers
    still busy with earlier reads says why instead of a blank picture.
  - **Timeline** (`/timeline`): one list, newest first, New York time on the
    right and a dot by kind: the investigation's alerts (armed, hit; a sent
    ping for one rides on its row, a held one shows with why), time stop (set,
    pinged, skipped with the reason; whether time-stop pings are off), revisit
    jobs, the fills of the trade
    linked to its plan, and for the symbol over 7 days its thesis-watch
    triggers, phone pings (sent or held back) and today's `decision` journal
    entries. A source that cannot be read is named under the list.
  - **Your history** (`/history`): `copilot_review.level_history` (the engine
    behind `get_level_history`) at the plan's invalidation, the side from the
    plan (below for a long), measured from its planned entry: a tile per past
    trade that crossed that distance while held, won (realized P&L above zero)
    or not, and one sentence from the counts. No plan invalidation, or no
    planned entry, says what is missing; the pane never measures from a live
    quote.

  While the Briefing (or a thread about no symbol, or no thread) is open the
  pane shows the day instead, with its own three tabs: **Chart**, QQQ today
  with the day's fills (any symbol, amber, first labelled FILL) and phone pings
  sent (violet, PING) as dots on the bar of their minute, from the picture
  route's reserved id (`GET /copilot/desk/market/picture`,
  `desk_context.market_picture`, fed by the session timeline's own fill and
  ping readers) and read again each minute; **Timeline**, the day across
  everything newest first from `GET /copilot/desk/session` (time stops still
  ahead, fills, pings sent, Radar events, decisions, the prep); and **This
  week**, which opens on the two proofs as /proof reads them, read-only and
  never recomputed: "Alerts: <habit label> · based on 9 of 14 alerts
  answered" (`GET /analytics/exit-habits`, its feedback counts, or its trade
  sample when there are none) and "Radar: <label> · 6 hits rated"
  (`GET /radar/proof`, or its reason when there is no verdict), each saying
  "could not load" when its read fails, and Open Proof →; then the plan
  streak's record (`GET /charts/captures/streak`): a tile per
  entry this week in time order (+ planned before entry, − no plan or a plan
  saved late, · a suggested plan waiting to be linked), each titled like
  "NBIS 100C · Tue 10:31 · planned" and opening that trade's page, where its
  linked plan shows; then the counts, the streak and best, and what one more
  planned entry makes.

**Link a fill where you are** (`components/copilot/FillLinkBar.tsx`). A row
whose open trade has a fill waiting for its plan carries `fill_to_link` (that
trade's id): the unplanned position the link ping would offer plans for, and
the armed plan its fill is suggested for (matched by symbol), so both open on
the same bar. At the top of that symbol's thread (the plan's conversation, or
the symbol alone) one compact bar reads "Bought NBIS 10/23/26 100C 10:05 ·
Link to plan "…" / No plan", with the plans the linker suggests: the link
ping's confirm page data (`GET /trades/{id}/plan-link`), each plan named by
its desk thread when a plan card saved it. **Link** calls the capture link
route (`POST /charts/captures/{id}/link`) at once, so every linking rule
holds, and offers **Undo** (the unlink route) for 8 seconds; then the list
reads again and the plan's thread top reads its position (header, ladder).
**No plan** writes nothing, as the confirm page's "Not this plan" does: the
fill stays unplanned in the plan streak and This week, and this browser
remembers the answer (`localStorage` `desk.no-plan.v1`) so the desk stops
asking. The thread list (under the day line) and the Briefing count the fills
still waiting, one per trade ("2 fills to link"); pressing it opens the first,
and each Link or No plan opens the next. Proof: `tests/test_copilot_desk.py`,
`frontend/e2e/copilot-desk-fill-link.spec.ts`.

**Pings open on the decision.** A position alert's phone ping opens the
desk thread for that position (see Review a trade or position), so a tap
lands on the decision bar: on the plan's conversation when there is one, else
on the symbol alone, where the bar shows without a saved conversation.

**Alert scorecard** (`components/copilot/AlertScorecard.tsx`, under the
Briefing's session timeline; `GET /copilot/desk/scorecard`,
`app/engine/alert_scorecard.py`). For each position alert sent to the
phone in the last 30 days: what was decided after it (the first `decision`
journal entry for the symbol that New York day, before the position's next
alert; the journal keeps the symbol, not the position) and what its
contracts then fetched, against selling them at the alert's bid (its mark
when no bid was quoted). The closing sells from the alert's minute on are
taken in FIFO order up to the contracts the alert saw open; contracts that expired fetched
nothing; a position still open is "still open"; a short position, an alert
with no price, or a trade that cannot be found is "not measured". One line
sums it ("You held 5: 3 better than selling at the alert, 1 worse, 1 still
open (net +$412)"), and each alert is behind "Each alert". Alerts are prompts
to decide, not exit rules (the 2026-10-24 exit study), so their value shows
here, in what was decided after them. Read-only; it changes no alert or
threshold. Proof: `tests/test_alert_scorecard.py`,
`frontend/e2e/copilot-scorecard.spec.ts`.

**Radar hits open on a decision** (`components/copilot/RadarDecision.tsx`).
A stock Radar hit in New since you looked opens the desk on that hit: what
Radar saw (its kind, direction, first-seen time and summary, with Open in
Radar) and one choice. **Watching** or **Pass** logs a `decision` day-journal
entry for the symbol ("Watching. Radar vs SPY: …", "Passing. …") after the
decision bar's Undo window; **Plan it** logs "Planning. …" and opens a plan
conversation whose origin is the hit (`radar_event`), so a confirmed plan
carries it to Radar's Planned and Traded marks. Ask about it puts a question in
the message box, unsent. A hit from an earlier day offers only Plan it: a
decision counts on the hit's own New York day. Once logged it is one line, with
Plan it still offered after Watching. Advice only. Proof:
`frontend/e2e/copilot-radar-decision.spec.ts`.

**Radar scorecard** (under the alert scorecard, from the same
`GET /copilot/desk/scorecard` read, its `radar` part;
`app/engine/radar_scorecard.py`). For each stock Radar hit of the last 30
days: what was decided (the first Watching, Passing or Planning `decision`
entry for the symbol on the hit's New York day, before the stock's next hit;
the journal keeps the symbol, not the hit), whether a plan names it and was
traded, and how far the stock then went against SPY in the direction Radar
flagged, an hour on and at the session's last pass (the outcome scorer's
`60m` and `close`, `scripts/radar_outcomes.py`). A hit whose pass or prices
are missing, or whose session is still open, says why it is not measured.
One line sums it ("You watched 4 (2 kept going, avg +0.8%)"), and each hit is
behind "Each hit". Group events name no one stock to decide on and stay on the
Radar page. While Radar is off the section is left out; an unreadable Radar
file reads unavailable and the alert scorecard stands. Read-only. Proof:
`tests/test_radar_scorecard.py`, `frontend/e2e/copilot-scorecard.spec.ts`.

**Answers for /proof** (`components/copilot/ProofAnswers.tsx`). The two answers
the [/proof page](product-roadmap.md#end-goal--october-22-2026) measures are
asked where the pings and hits are seen. A position's thread (a ping opens the
desk on its decision bar) lists the alerts sent today for its symbol under the
decision bar, each with Prompted a review, Already aware, Too late and Not useful
and an optional reason saved with the tap. A Radar hit's thread puts Useful,
Already knew, Too late and Irrelevant in its own box under the hit's decision,
not inside it. The Briefing's top says "N alerts to answer" and "N Radar hits
to rate", in /proof's scope: every sent or delivery-unconfirmed position alert
with no feedback, and every unrated event of Radar's newest rule version. Each
opens its waiting rows (today's, then the newest from before, up to 20) to
answer in place, and its count drops at once. An answer is a line with
Change. Saves go through the routes the trade page and the Radar feed use
(`PUT /trades/{trade_id}/phone-alerts/{id}/feedback`,
`POST /radar/events/{id}/feedback`), so /proof counts each one at once. The rows
come from the session read's `to_answer` (below); an alert whose position is
no longer in the journal is counted but not listed. Proof:
`tests/test_copilot_desk_session.py`, `frontend/e2e/copilot-proof-answers.spec.ts`.

**One main element per thread.** The thread's top reads header, then its
main element, then the conversation: while the decision bar (below) is
asking, it sits between the header and the plan ladder, and the ladder
shrinks to one line (invalidation · scale · 2R); once a decision is logged, or
when nothing needs one, the full ladder leads. The bar reports whether it is
asking through `onActive`; `DeskThreadTop` places it (`hero`, `compact`).
Browser proof: `frontend/e2e/copilot-decision-bar.spec.ts`.

**Decision bar** (`components/copilot/DecisionBar.tsx`, between the thread
header and the plan ladder). While the market is open and the open thread's symbol has an
Act-now row on `GET /today` (give-back fired, invalidation near or hit,
expires today, time stop due), one bar says what fired and when ("Give-back
fired at 10:31."), what the plan says ("Your plan says hold while NBIS is
above 85.00. It is 3.1% above.", from the row's `invalidation`, `time_stop`
and `latest_alert`), and offers **Holding**, **Exiting** and **Ask why**. Ask
why puts a question in the message box unsent (the `fill` desk command).
Holding and Exiting save one day-journal entry of kind `decision` with the
symbol and a sentence such as "Holding. Give-back fired at 10:31; plan says
hold above 85.00 (3.1% above)." Entries are immutable, so the save waits 5
seconds behind "Logged holding · Undo" (leaving the thread inside the window
still saves); a double tap or retry reuses one `operation_id`. Afterwards the
bar is one quiet line ("You logged holding at 10:44. Next check: a close below
85.00."); a decision logged before a later phone alert, an invalidation hit
or a time stop coming due does not hide the bar. The hold side is read from
where the level sits (a long put's invalidation is above the price), not from
the lot's direction.
Advice only: Exiting places, sizes and sends nothing; its line says to close
the position in Robinhood, where the fill links to the plan on its own.
Logging what was decided after each alert is the data that shows whether
position alerts help.

**Horizon.** Every plan and open position has a horizon that sets how often
the desk checks in after the close: **Day trade** (every trading day),
**Swing** (only on a day something happened to it: a phone ping judged, sent
or held, a level alert fired, a fill, or the decision bar asked or was
answered) or **Long hold** (never day to day; `get_week_review` lists it under
`long_holds`, and Review my week gives each a line). It is kept per symbol as
a `horizon` day-journal entry (text `Day trade`, `Swing` or `Long hold`; the
newest wins, `day_journal.check_ins`), so no new store or route: the plan card
saves one at Confirm (its default from the time stop: due today is a day
trade, otherwise a swing; the owner can pick another on the card), and the
thread header's Horizon menu saves a new one. A symbol with none is a swing.
An invalidation hit still raises the decision bar during the session, whatever
the horizon.

**Close of day.** After 16:00 New York on a weekday (by `/today`'s `as_of`;
holidays and early closes are not known here) the thread list's rows its
horizon asks about today carry `close` (`GET /copilot/desk/threads`): a
position asks "Review: did you follow the plan?" and an armed plan not yet in
a position asks "Added or not, and why?". A position with no plan instead asks
"Want a plan for this?" once (not for a long hold): **Plan it** opens planning
it and **Not now** keeps it quiet, both saved as a `plan_ask` day-journal
entry, so the answer holds across devices; an answer from before the position
opened does not count. The open thread's decision bar shows its row's
question instead of the bar. Answer opens a one-line input that saves a
`reflection` entry for the symbol; Skip hides it for the day in this browser.
The row's status line says the same in a muted amber, beside the first words
of the symbol's first `reflection` (or `plan_ask` answer) today: "Reviewed ·
<first words>" once one is saved, or "Skipped today".
**Close the day** (the phase button, "Close the day · N to review", or the ⌘K
command) is a pass through them: it opens the first unreviewed thread in list
order on its question (a position with no conversation opens by its symbol,
`/copilot-lab?symbol=…`, and the pass carries on in this tab), and each answer
or Skip opens the next. Then, in the conversation pane (`ClosePass.tsx`), it
asks the rest one at a time with the same answers the Briefing and thread top
use: today's position alerts with no feedback, today's Radar hits not rated,
then the fills waiting to link (the link bar). An answer or Skip moves on, the
✕ ends the pass, and the last one ends it. Older alerts and hits stay in the
Briefing's "to answer" lists. With nothing left it puts the day's question in
the message box, unsent. Nothing is sent to the model, and the answers go
through the same routes as everywhere else. The button counts all of it
("Close the day · 6 to review", less what was skipped), and the Briefing's
line says "N of M done": the close questions (one per symbol), today's alerts
and hits, and the fills to link, a skip not counting as done.
`/copilot-lab?close=1` (the [evening review ping](#phone-ping-policy)'s link)
starts the same pass once the list and the session have read, after 16:00
only: the first unreviewed thread by its link, else today's alerts, hits and
fills; with nothing left, or read before 16:00, it opens the desk as usual.
Browser proof:
`frontend/e2e/copilot-decision-bar.spec.ts` and
`frontend/e2e/copilot-desk-keys.spec.ts`.

**Plans end.** A plan goes Draft → Armed → In position → Exited → Done.
It is **Exited** once its position is over: the trade linked to its capture
is closed, or, with no link, every trade in the symbol opened in the two
weeks after the plan is closed (`copilot_plans.exits`; Webull stays out). For a week after the exit
its thread list row leads Watching with "Did you follow the plan? One lesson?"
(`close.kind` `exit`, at any hour, so Close the day walks it too) and its
header chip says Exited. The decision bar asks it once: Answer saves the line
as a `reflection` entry, and the answer or Skip saves a `plan_done`
day-journal entry, so the plan is **Done** on every device and never asks
again. A week on, an unanswered review stops asking (a plan with an alert
still armed goes back to a quiet plan row). **Mark plan done** in the thread's
… menu (a plan's thread, not a held position's) ends a plan that was never
entered or was given up on the same way. If its entry or invalidation alert is
still armed it says so and asks first; Remove alerts and mark done removes
just those alerts through the alerts route (`DELETE /charts/alerts/{id}`, the
only way the route disarms one), Cancel changes nothing. The plan's capture,
its conversation and the journal stay. A Done plan (a `plan_done` entry for
its symbol at or after its newest part) leaves every group of the thread
list, and so does an owner conversation about the symbol not touched since;
closing the conversation puts it in the Context pane's This week record. A
plan confirmed after that is a new plan.

**The last lesson comes back to the next plan.** A new plan on a symbol shows
that symbol's newest answered exit review as one quiet line, "Last NBIS exit
(Oct 21): didn't follow · “No, sold the give-back too early.”"
(`LastExitLine.tsx`): the date of that plan's last exit, what the answer opens
with (followed, partly followed or didn't follow; left out when it says
neither) and the owner's own words, cut at 200 characters. It sits under a
draft plan card (not a confirmed or dismissed one), read from
`GET /copilot/symbol/{symbol}`'s `last_exit`, and on each Arm today's plans
row, from the Plans read's `last_exit` on an armed plan.
`copilot_plans.last_exit_lessons` reads it as Review my week does
(`copilot_review.exit_reviews`'s pairing and helpers): of the symbol's exited
plans, newest exit first, the first whose `plan_done` says Exit reviewed, with
the `reflection` saved just before it. A skipped or unanswered review falls
back to the one before; a symbol with none shows nothing. Read-only, no model
call; a failed read leaves the line out (`last_exit` unavailable).

**Today's session (the Briefing's top).** While the Briefing (or no thread) is
open, the top of the conversation shows the day
at a glance instead of a header and plan ladder (`SessionTape.tsx`): "Today",
the market phase and SPY, QQQ and VIX's change on one line; one strip of the regular
session in New York time (9:30 to 16:00, or the calendar's early close) with a
"now" marker, today's fills, phone pings sent, Radar events and logged
decisions as small ticks coloured by kind (hover for the time and what it was;
one before the open or after the close sits faded at the edge), and the plan
time stops still ahead as hollow amber ticks, amber being for what still needs
you; then a numbers row: open positions and how many need a decision (from
the thread list's rows), the nearest armed trigger (the first Near a trigger
row, "CRWV · 0.6% to entry 99.00"), and pings sent today against the daily cap
(with how many were held); then one quiet line: **Next:** the nearest time
stop, else the open (before it) or the close (during the session), and the
practice goal's line. Before the open the strip waits (no marker) and
the line leads with whether the pre-market prep is written; after the close it
shows the whole day; a closed day says so. The desk bar shows the same read
beside its title: **Live** (green dot) in the regular session, **Pre-market**,
or **Closed 16:00** (the calendar's close) after it, and on a wide screen SPY,
QQQ and VIX's change. At the top of the thread list sits a phase button:
**Arm today's plans** before 9:30 on a weekday, and **Close the day** after
16:00, which walks each thread's close question (see Close of day).

**Arm today's plans** opens a checklist in the conversation pane
(`ArmChecklist.tsx`; on a phone it moves to the Thread tab): each armed plan
from the thread list's Plans read, with its contract, entry, invalidation and
time stop, flagged (⚑) with any thesis-watch trigger fired today on the
symbol, earnings first, the symbol's last exit lesson (see Plans end), and
three answers. **Still good** logs a `decision`
day-journal entry, "Armed for today. Entry … · invalidation … · time stop …."
(the decision bar's Holding/Exiting parser does not read it). **Change** opens
the plan's thread with "Change my <symbol> plan before the open: … What should
change, and why?" in the box, unsent. **Drop** is Mark plan done: while the
plan's alerts are armed it asks first, then removes them. "N of M checked"
counts the plans answered (Still good is read back from today's journal; a
drop counts on that visit, and the plan leaves the list on the next read).
**Ask the copilot instead**, at the foot, puts the old question in the box,
unsent (check each plan against the pre-market and propose what is missing).
Opening a thread or Close leaves the checklist. Nothing in it arms, sizes or
sends an order. On a
phone Jump to… and New plan show as icons so the bar stays on one line. One
read, `GET /copilot/desk/session` (owner only, refused while the lab is off),
once a minute while the page is visible, read once by the desk
(`useDeskSession`) for its bar and the Briefing, composed in `copilot_desk.py` from readers
that already exist: `day_replay.traded` (Webull left out), the notification
policy's `PhonePing` rows and `daily_cap`, the Radar store's events for today,
`decision` day-journal entries, scheduled `PlanTimeStop` rows, `today._prep`
and one `chart_feed.quote_rows` read of SPY, QQQ and VIX (the feed's index
mapping). Under `to_answer` it adds the position alerts and Radar hits still
waiting on an answer (see Answers for /proof), with the alert, trade and Radar
event ids those answers save against; no other ids go out. Each source fails on
its own. No futures quote is read yet.

**Keys and the palette.** ⌘K (Ctrl+K off a Mac; either works), or the desk bar's
"Jump to…" button, opens a palette over the desk (`CommandPalette.tsx`, a
modal dialog): a search box, then Threads (the thread list's rows in list
order, each with its status line and value) and Commands (Plan a trade, Review
my week, What matters right now?, and the day's phase command: Prep the day
before 9:30 on a weekday, Close the day after 16:00). Type to filter, arrows
and Enter to choose, Escape or a click outside to close. A thread opens through
the list's own path (in place, or its deep link); Plan a trade opens the same
unsent "Plan a trade: " link as the list's button; Review my week and What
matters right now? send their one turn exactly as their pinned rows do; Prep
the day and Close the day only put a question in the message box, unsent.
While not typing in a field: J / K open the next or previous thread in list
order (rows that open in place; a Radar or trade-link row is skipped, since it
leaves the page), N opens Plan a trade (not while the message box holds unsent words), and `]` hides or shows the Context pane
where the panes sit side by side (remembered in this browser; the desk bar's
pane button does the same, and a phone keeps its tabs). No desk key fires in an
input, text area or editable field, ⌘K included, and no other browser shortcut
is taken. A one-line key hint sits at the foot of the thread list on a wide
screen. Browser proof: `frontend/e2e/copilot-desk-keys.spec.ts` (palette,
J/K order, `]` remembered, keys ignored while typing, the timeline at 1440 and
375 px).

The panes follow the desk's own width: three from 1100 px, two below that
(Context under Threads), and below 760 px one at a time behind Now / Thread /
Context tabs. A phone lands on Now unless a deep link brings a conversation.
While the lab is off only the conversation shows, saying so. On a wide screen
(1024 px and up) the desk takes the whole screen, as Charts does
(`AppMain.fullScreenRoute`), and each pane scrolls on its own. From 768 px the
app's navigation folds into one **Menu** button at the left of the desk bar
(`useFoldedNav` / `openNavMenu` in `Nav.tsx`), so the desk gets the full
width; it opens the labelled menu (every page, sync, the plan streak), whose
**Keep the sidebar open** shows the full sidebar instead, remembered in this
browser with the same key as Charts' expanded rail (its Collapse folds it
back). A phone keeps its tab bar. Every icon in the Charts rail names itself
on hover or focus (`NavHint`), the sync dot included.
The desk bar holds Menu, Jump to… (⌘K), New plan and the Context toggle; the
read-only note sits under the message box.

**The desk is home.** While the lab is on, the desk takes the Today screen's
place: it is first in the menu and the phone's first tab ("Desk",
`withDesk` in `frontend/components/Nav.tsx`), `/today` forwards to it, and
the Labs entry for the same page goes. What Today showed that the desk did
not now sits in the Briefing (`BriefingExtras.tsx`): the pings held back today
behind a disclosure, and Watch today. With the lab off, Today is unchanged.

The message box (desk and side panel alike) is one box: on the desk the
"About <symbol>" chip, then a full-width text area that starts three lines
tall and grows with what is typed (up to 40% of the page, or about 14 lines in
a panel), then a toolbar inside it (attach and read aloud; mic and Send). A
streaming answer is followed only while the reader is at the bottom of the
conversation: scrolling up to read stops following, and the end follows again
on their next send.

The whole app now uses the desk's graphite surfaces, text and borders
(`frontend/app/globals.css`). The desk keeps its own accent (amber as the
one accent, where the rest of the app's primary stays blue-grey) and type
(Instrument Sans, IBM Plex Mono for tabular numbers), scoped to this page: it
overrides the shadcn tokens inside the desk only. `frontend/lib/desk.ts` holds the shapes the desk's pieces share (tabs,
the conversation hand-off, thread-list rows and groups, logged decisions,
the decision bar's wording).
Browser proof: `frontend/e2e/copilot-home.spec.ts` (including a 375 px phone),
`frontend/e2e/copilot-thread-list.spec.ts`,
`frontend/e2e/copilot-thread-head.spec.ts` (option and stock, 375 px),
`frontend/e2e/copilot-answer-format.spec.ts` (the answer format, Sources,
the cleaned conversation and the 375 px composer) and
`frontend/e2e/copilot-desk-context.spec.ts` (each Context tab, the chart's
timeframe buttons and legend, unavailable states, the 375 px Context tab, the
Briefing's day).

## How the copilot reasons (system prompt)

`copilot.SYSTEM_PROMPT` (`backend/app/ai/copilot.py`) frames every turn:

- **Who it works with**, as working hypotheses to test against what the owner
  does, never a diagnosis: debate-driven; semiconductors, AI infrastructure,
  recoveries, relative strength and catalysts; a longer thesis often expressed
  through a short-dated option. The [behavior audit](../backend/reports/behavior_audit_2026-10-21.md)'s
  findings (exits, not entries; 15-60 minute holds best; hour-to-close worst;
  the 53 green-then-red losers; trading on while green) are stated with their
  sample and labelled associations, not rules, with the exit counterfactual's
  rejection of the three mechanical exits. The prompt says to raise one when
  the position in front of it resembles it, never to recite them.
- **Four separate questions** for any trade idea: thesis, setup now,
  instrument fit (expiry, strike and premium against the horizon, from real
  contracts through `get_option_candidates`; no implied volatility or Greeks,
  so it says so rather than estimates), and
  the decision now (what changed for the thesis versus only for the
  position). "Nothing here changes the plan" and "not worth a trade" are
  complete answers.
- The evidence, time-labelling, pushback and untrusted-text rules; the owner
  context block (below); memory proposals (Confirm a plan); trade and
  position reviews (Review a trade or position); weekly reviews (Review my
  week); explaining a moment on the chart (Explain this candle); plans, and
  pressure-testing a trade the
  owner wants to take before one plan card (Confirm a plan); SIMULATED;
  no orders.
- **Short answers.** After the Verdict line, at most about 120 words: the
  two or three deciding facts with their numbers and as-of, including the
  strongest point against; no preamble, tool tour or closing summary, and a
  plan's fields stay on its card rather than in the text. A trade review, a
  week review or an explicit "more", "why" or "go deeper" gets the room it
  needs. Length is the wait: after a tool result, Sonnet 5.5 sends the whole
  answer at once at about 100 tokens a second (§ Live measurements).
- **The answer format.** The first line of every answer is
  `Verdict: <word> — <headline>`, for example
  `Verdict: Hold — The thesis has not broken.`, with the word from a fixed
  set: Hold, Wait, Pass, Focus, Draft, Pattern, Broken (the plan's
  invalidation or the thesis broke: what the plan says, never an order) and
  Unclear. Then the body in short paragraphs or bullets, and, when one thing
  would change the answer, a last line `Changes if: …`. The frontend parses
  the structure rather than guessing it from prose (`lib/copilot.ts`
  `answerParts`, `VERDICTS`): the verdict as a small tag, the headline in
  bold, the body, then a plain "Changes if …" line. An answer without it (one
  saved before the format, a backend that ignores it, an unknown word, an
  error) renders as plain text. The scripted `fake` backend writes every
  answer this way (`copilot.scripted`), with its simulated-model note (and
  any image note) under the Verdict line. Read aloud, the line becomes
  "Hold. The thesis has not broken."
- **The case against.** On an answer about a trade idea, a thesis or a
  position decision, the line after the Verdict is
  `Read: Thesis holds · Timing early · Contract n/a` (one or two words per
  question), and the body ends with `Against: <the strongest case against
  the verdict, with its number or source>` before any Changes if line;
  "nothing in the evidence" only when that is true. A claim no tool or owner
  context shows gets a body line `Unsupported: <claim> — <what would support
  it>` instead of being reasoned from. `answerParts` returns `read` (only when
  all three parts parse) and `against`; the desk shows the read as one small
  line under the headline and Against set off in amber above Changes if, and
  read aloud they become "Thesis holds, Timing early, …" and "Against that,
  …". The scripted group reads carry both. The scheduled turns' phone pings and
  saved conclusions drop the "Verdict: " label (`premarket_prep.unlabelled`,
  `week_review_auto._plain`); their saved answers keep it.

Tests pin the sentences other guards depend on (`tests/test_copilot_answer_format.py`
on the answer format and the scripted answers, `tests/test_copilot_book.py`
on account identifiers, `tests/test_copilot_adversarial.py` on "you cannot
create alerts or research jobs yourself", `tests/test_copilot.py` on the
four-question frame and the memory rule).

## Owner context

Every turn starts with what TradeJournal already knows about the owner, so
the model spends no tool rounds rediscovering them and leads with it: an open
position in the symbol they ask about, the plan they captured for it, a thesis
they saved, a habit the moment resembles. `backend/app/ai/copilot_context.py`
assembles one bounded pack (at most 5,500 characters, about 1,400 tokens) for
the turn's symbol, from services that already exist, and `run_turn` puts it
after the context line and before the owner's message. The browser never sends
it; it is rebuilt on the server each turn, so marks and hold times are current.

- **Sections**, each with a provenance label the system prompt explains
  (`owner said` = their own words; `measured` = journal facts; `saved` = earlier
  conclusions and watches, possibly stale):
  - `positions` (measured): `get_positions`' rows, the turn's symbol first (put
    ahead before any cut, so a large book never drops it) and at most 8, each with its minutes held when opened today, days to expiry and
    expires-today flag, the give-back watch (`not armed`, `armed` or `fired`,
    with the peak gain) and the last three phone alerts `position_alerts` keeps
    for it, and the plan captured before it (`capture_links`: setup, wording,
    note, time; owner said).
  - `history` (measured): closed trades in the symbol (count, wins, realized $)
    and the latest four, as `get_trades` shows them.
  - `habits` (measured): the behavior audit's four exit habits through
    `exit_habits.build`, the latest 30 closed long options against the baseline,
    cached for ten minutes in the process.
  - `memories` (owner said): approved memories for the symbol, then general
    ones, at most 8.
  - `today` (owner said): today's day-journal entries (New York), at most 6.
  - `investigations` (saved): saved investigations and research results for the
    symbol, open first, at most 4, with their ids so the model can call
    `get_investigation_changes`. A copilot conversation's conclusion is shown;
    a research job's is not (title and status only): a job's text was written
    by a model that read untrusted web pages, and this block sits in the
    owner's turn, where `propose_plan` and the book are in reach. Its findings
    stay a tool result (`get_saved_research`).
  - `watches` (saved): armed level alerts for the symbol, and queued or running
    research jobs that name it (question jobs) or are linked to one of its
    investigations (reassessments); Radar event jobs name an event, not a
    symbol, so they are not matched. At most 6.
- **No symbol** (a turn with an empty symbol box, and the Open threads read): there is
  no `history`, and memories are the general ones. `investigations` are the
  open ones across every symbol, newest first, at most 4, each with its symbol.
  The same conclusion rule holds: a copilot conversation's is shown, a
  research job's is not. `watches` are the armed level alerts across every
  symbol, newest first, at most 6, each with its symbol, then at most 3 queued
  or running research jobs of any kind, with the symbols they name. The shed
  order below is unchanged, and watches are never shed.
- A section that cannot be read says `unavailable`; the others stand. If the
  whole read fails or exceeds the tool timeout, the block says the context was
  unavailable and the turn goes on (the read itself finishes in its worker
  thread; the turn does not wait for it). The read runs before the first model
  round, so a slow quote provider adds up to the tool timeout to a turn. Over the size cap, the pack sheds the
  least decision-relevant parts first (recent trades, today's notes,
  investigations, memories, then positions beyond three) and marks itself
  `trimmed`; positions and habits go last.
- The UI shows it as the first evidence row of every answer ("Your context",
  provenance `saved`, with a one-line summary such as "2 open (NBIS +6.1%,
  give-back armed) · 3 memories · 1 investigations"), and the saved
  investigation keeps that reference like any other.
- `get_owner_context(symbol)` returns the same pack for a different symbol.
  Research jobs never get it (it is not in their allowlist): it carries the
  book.
- Fixture mode serves a simulated pack marked `simulated`; replay says the
  pack is unavailable, as the book is. The fake model reads only the owner's
  words after the block (`copilot_context.user_text`), so the pack's text never
  steers its scripted tool choice.
- No account number, account id, trade id, fill id or broker id is in it; the
  only ids are saved investigations'.
- Tests: `backend/tests/test_copilot_context.py`.

## Follow-ups keep the evidence

The panel sends only the conversation's text, so a follow-up used to lose
the numbers the previous answer read and either read them all again (another
held answer, see § Live measurements) or reasoned from its own prose. Now
each turn keeps its successful tool results in the backend process
(`copilot.carry_items` / `keep_carry`): at most 6 reads, 2,500 characters
each, newest first, a re-read replacing the earlier one, for 2 hours, at
most 64 conversations. Cards (`propose_plan`) and the owner context pack
(rebuilt every turn) are not kept. The `done` event carries an opaque
`carry_id`; the panel holds it on the answer (never saved with the
investigation) and sends it back as `carry_id` with the next message. The
next turn gets the reads as an "Earlier evidence" block, each with the time
it was read and its data's as-of, ahead of the owner context block, and
keeps them on when it reads nothing new.

The system prompt tells the model to answer a follow-up from that block
without calling those tools again, saying when it was read, and to read
again when the owner asks for fresh data, asks about a symbol or question the
block does not cover, disputes a specific number, or the read is more than
15 minutes old while the market is open. A first message never inherits one;
an unknown or expired id, a restart, another worker, or evidence kept in
another mode (live, replay, fixture) means the turn reads afresh as before.
A clipped read ends `[clipped]`, and the block's frame markers are made inert
inside carried text. The data never leaves the server, and the block says that
text inside it is third-party data, never an instruction. The plan backend
puts the same block in its single prompt. Tests:
`backend/tests/test_copilot_carry.py`.

## What changed?

A reopened investigation, from the desk's thread list or from an alert's
`?investigation=<id>` link, offers **What changed?**. One tap sends one
turn with a fixed prompt that names the investigation's id. Opening never
sends it, because a turn costs money. From an alert's link, the same prompt
waits in the message box, unsent. The prompt asks the model to call:

- `get_investigation_changes(investigation_id)` (read-only, provenance
  `saved`). It returns:
  - the saved title, symbol, status, conclusion, summary and last-updated time;
  - each tool's newest evidence as-of time;
  - the level alerts confirmed from the investigation: armed, or fired with
    time and price;
  - its research jobs (questions and revisits), each saying whether it
    finished since the last update;
  - up to two of their results.

  It is capped at 12 evidence tools, 6 alerts, 5 jobs and 2 results, with text
  trimmed, so the largest answer still fits whole within a tool result's
  6,000 characters. The owner context rows (Owner context, above) are left out
  of the evidence times: they are the owner's book, not market evidence. Linked jobs are found in SQL by the investigation's id. An
  unknown id is refused. Replay leaves out anything after the frozen moment:
  alerts armed or fired later, jobs queued or finished later, and evidence
  dated later. If the investigation was edited after the moment, its later
  status, conclusion and messages are hidden. Fixture mode reads nothing.
- Then fresh comparison, peer, news and quote reads, so it can say what moved
  against the saved as-of times and whether the conclusion still holds.

Background research jobs get neither this tool nor `propose_plan`. They read
untrusted pages and can fetch URLs, so injected text must not make them read
another investigation by id.

## Review a trade or position

On a closed (or expired) trade's page, while the lab is on, **Review with
copilot** opens `/copilot-lab?symbol=<ticker>&context=Review this trade: <trade
id>`. On an open trade's page **Ask copilot about this position** opens it with
`Review this position: <trade id>`: the primary action inside the selected
alert a position alert's link opens (`TradePhoneAlerts.tsx`), a header link
otherwise. While the lab is on (`COPILOT_ENABLED=true`), a position alert's
tap opens the desk on that position's decision (`position_alerts.desk_path`:
the plan's conversation when a plan card saved the position's plan, else
`/copilot-lab?symbol=…`, which opens on the decision bar); with the lab off the
tap opens the trade page as before. Either way the push carries two answer
actions next to Open app (ntfy shows three; all need `ALERT_APP_URL`):
**Prompted review** and **Already aware** (`position_alerts.ANSWER_ACTIONS`)
open the trade page on the alert with `&answer=prompted_review` or
`&answer=already_aware`. The page drops `answer` from the address, then saves
that rating once through the existing
`PUT /trades/{trade_id}/phone-alerts/{alert_id}/feedback` with `base_version`
0, so it is the same feedback row the desk, Close the day and Proof read and the
alert leaves Close the day's questions. It shows "Saved: …" with Edit feedback
to change it (or add a reason). An alert already answered keeps its answer: the
tap is shown as not saved over it, and a stale save gets the usual reload
prompt. No new route, token or public ingress. The push no longer carries its
own Ask copilot or Open trade action: the page's Ask copilot inside the selected
alert takes the ping's old context instead, what the alert saw, e.g.
`Review this position: <id>. Give-back alert at 11:02 AM: was +$124, now +$20.`
(at most 300 characters, `position_alerts.ask_context`, served on each position
alert in `GET /trades/{trade_id}/phone-alerts`); the header's Ask copilot, with
no alert, stays `Review this position: <trade id>`. The message box holds the
context, unsent; the owner sends it, adding a question if they like.
The system prompt asks the model to call:

- `get_trade_review(trade_id)` (read-only, provenance `saved`). The id is
  checked as a UUID; an unknown id is refused, and a Webull trade reads
  `unavailable`. For a closed trade it returns, each section labelled like the
  owner context pack:
  - `trade` (measured): contract, account label, quantity, entry and exit
    (New York wall clock with its offset), prices, premium paid, P&L in $ and
    %, hold minutes, status, expired worthless, and how many entry and exit
    fills made it;
  - `path` (measured): `TradePathMetrics`' option peak % and peak unrealized $,
    the give-back from the peak, the worst unrealized $, the underlying's best
    and worst move, and the best move in the 30 minutes after the exit;
  - `plan` (owner said): the plan captured for it (`capture_links.for_trade`:
    setup, side, mode, wording, note, planned size, time), `image: available`
    when a chart image was saved with it (the image follows the text; see
    [The copilot can see](#the-copilot-can-see)), and its timing
    against the entry (`pre_entry`, `unverified` or `retrospective`);
  - `alerts` (measured): the phone alerts sent for the position
    (`position_alerts.for_trade`, at most 6) and what followed each
    (`exit_habits.follow_up`: closed within 15 minutes, trimmed, closed later,
    held overnight or expired, and the $ against closing at the alert's mark);
  - `habits` (measured): this trade against the behavior audit's four exit
    habits (`exit_habits.habit_flags`): yes, no or unknown; closed long options
    only;
  - `comparison` (measured): the symbol's latest four other closed trades, as
    `get_trades` shows them, without the account.
- For an open position it returns `trade` (no exit or P&L yet), `plan`,
  `alerts` (what followed so far: `still_open` until the contracts close) and
  `comparison`, plus `now`: the mark and open P&L in $ and % through
  `copilot_book.position_rows` (the dashboard's quote engine; a missing quote
  says so), minutes and days held (calendar time, weekends included), days
  to expiry and expires-today, the give-back
  watch's peak gain, the $ given back from it and its state, and the latest
  alert (kind, time, gain at the alert). No `path` or `habits` until it
  closes. The prompt asks the model to lead with the decision now (the fourth
  question: thesis vs position), compare with the plan's invalidation and
  time stop if one was captured, and never tell the owner to sell or hold as
  an order.
- Then, for a closed trade, the model compares what the plan assumed with what happened, keeps
  thesis apart from execution, says when one trade cannot support a lesson,
  and proposes a memory only if the owner states one.
- The review is held under 5,800 characters (inside a tool result's 6,000):
  over that, it drops the provenance labels, then comparison trades, then all
  but the last three alerts, and marks itself `trimmed`. One failing section
  reads `unavailable`; the others stand.
- No trade, fill, account or broker id is returned; the id arrives only in the
  owner's own message. Research jobs never get the tool, and "What changed?"
  leaves it out of an investigation's evidence times, as it does the owner
  context.
- Fixture mode serves a simulated review marked `simulated` (the open NBIS
  call for `copilot_fixture.OPEN_REVIEW_ID`, a closed one for any other id);
  replay says it is unavailable (the journal now would show what happened
  after the frozen moment). The fake model answers "review this trade" or
  "review this position" with a UUID by calling the tool and writing a short
  scripted comparison or decision-now summary.
- Tests: `backend/tests/test_copilot_review.py`,
  `backend/tests/test_position_alerts.py` (the push action),
  `frontend/e2e/copilot-review.spec.ts`, `frontend/e2e/position-copilot.spec.ts`.

## Review my week

While the lab is on, **Review my week** sits on the Dashboard header and on a
Friday's Daily Review (`components/copilot/ReviewMyWeek.tsx`), opening
`/copilot-lab?context=Review my week` (a Friday's adds `of <its Monday>`) with
the text in the message box, unsent. On the lab home it sits beside "What
matters right now?" (the desk's Briefing and ⌘K) and sends the turn at once. The system prompt asks the
model to call:

- `get_week_review(week_start?)` (read-only, provenance `saved`;
  `copilot_review.week_review`). `week_start` is any `YYYY-MM-DD` in the week
  (2020 to next week); without one it reads the latest week with a closed
  trade. A week is Monday 00:00 to Saturday 00:00 New York, by close time;
  Webull trades are left out. With no closed trades it reads `none` (and names
  the latest week that has some). Otherwise it returns:
  - `week` and `sample` (fewer than 10 trades is `small`, with a note that it
    cannot show a habit changed);
  - `totals`: trades, P&L $, P&L on premium paid %, win rate, expired
    worthless, account labels;
  - `planned`: `pre_entry` (a plan captured and linked before the entry),
    `late_or_unverified` (captured inside the entry's minute or after it) and
    `none`, each with count, P&L $, on premium and win rate
    (`capture_links.for_trade` and `timing`);
  - `follow_through`: for planned trades, whether the plan's invalidation
    alert (`level_alert` with `plan_role` invalidation, found through the time
    stop saved under the plan's client id, else the copilot invalidation armed
    within 10 minutes of the plan) fired between the entry and the last exit,
    and whether the trade was fully closed within 15 minutes of it
    (`out_15m`, `held_past_15m`, `expired`), with up to 6 rows; and the time
    stops due that week (`plan_time_stop`): due, sent, skipped and what
    followed each sent ping (`exit_habits.follow_up`), up to 6 rows;
  - `alerts`: phone alerts sent for the week's trades, by kind, what followed
    them and the $ against closing at each alert's mark;
  - `pings`: every phone ping the [notification policy](#phone-ping-policy)
    judged that week (`notification_policy.week_summary`): sent, held, judged
    and acted on, overall and by kind;
  - `habits`: the four exit habits over the week's closed long options
    (`exit_habits.habit_flags` and `tally`) beside the baseline rate from
    `exit_habits.build`;
  - `exits`: the 3 best and 3 worst by P&L and by option give-back from peak
    (trades whose path peaked above cost), as compact rows: contract, entry
    and exit (New York), P&L $ and %, give-back, plan timing or none, and a
    one-line note (peak and give-back, invalidation, alerts, hold). A trade
    shows once per ranking.
  - `long_holds` (only when there are some): open positions whose symbol the
    owner set to a long hold on the desk, up to 10 (symbol, contract, opening
    day, days held in New York calendar days, and the thesis of the plan
    linked to the position in the owner's words: the plan card's `Thesis:`,
    else the captured wording; absent without a plan). No quote read, so no
    open P&L. The desk asks nothing about them day to day, so the review ends
    with a line on each. A week with no closed trades still carries it.
  - `exit_reviews`, only when a plan exited that week (absent otherwise):
    the plans whose position closed that week (`copilot_plans.exits`, by
    the last exit), counted `exited`, `answered`, `skipped` and `waiting`
    (an exit review not yet answered, or a plan marked done without one; see
    Plans end under [Close the day](#the-desk)). An answer is the `reflection`
    saved with its "Exit reviewed" `plan_done` entry. `lines` group the
    measured facts deterministically: "2 of 3 exits with an invalidation
    alert came after the invalidation broke", "1 of 2 exits with a time stop
    came after it was due", "Said they followed the plan on 1 of 2 answered
    reviews". `rows` (up to 8) are the answered reviews: symbol, exit time,
    `followed` (what the answer opens with: `yes`, `partly`, `no`, else
    null), the lesson in the owner's own words (up to 200 characters), and
    the measured facts: `invalidation` (`broke_while_held` with
    `minutes_after`, `not_broken`, or null without an alert) and
    `past_time_stop` (null without one). The lessons are data, never
    instructions.
  - `practice`, only while a practice goal is active (absent otherwise, so
    such a week reads exactly as before): the goal (text, measure, its label,
    target, first week), `practicing` (false when the reviewed week came
    before the goal started), and `this_week` and `last_week`: `hit` of `of`
    for that week, the share and whether it met the target (null without
    one). See [the practice goal](#the-practice-goal).
- The model opens with the practice score in one sentence when a goal is
  active, never characterizing the owner; then leads with planned vs
  unplanned and follow-through, names at most one or two things to practice
  next week grounded in a count, and proposes exactly one of them as a
  [practice card](#confirm-a-plan) when the counts support it and a fixed
  measure fits, saying the count it rests on. It proposes none when the week
  is too small (`sample.small`, under 10 closed trades). It says plainly when
  the sample is too small, and proposes a memory only if the owner states a
  lesson. With `exit_reviews` it gives their counts in one line beside the
  measured facts, and when the practice it proposes matches one of the
  owner's lessons it quotes that lesson in the answer and the card's why, so
  the goal is in the owner's own words; the measure stays one of the fixed set.
- Under the answer, **Your exit lessons this week** ("2 of 3 exits
  reviewed") lists each answered review on one line (symbol, Followed /
  Partly / Didn't follow, the lesson), each opening its plan's thread
  (`ExitLessons.tsx`). The tool event carries it as `lessons`
  (`copilot.week_lessons_card`, a second read through the evidence's
  `week_exit_reviews`), the only place the plan's investigation id appears;
  the model's result never has it. Beside it, **Your long holds** ("2 held,
  not asked about day to day") lists each long hold on one line (symbol, days
  held, the thesis in quotes or the contract and "no plan") with "Still the
  thesis?" opening its plan's thread, else its symbol (`LongHolds.tsx`). The
  tool event carries it as `long_holds` (`copilot.long_holds_card`, a second
  read through the evidence's `week_long_holds`). A reopened saved
  conversation shows the answer without either block (saved evidence keeps no
  tool data).
- The review is held under 5,800 characters: over that, it drops the
  provenance labels, the time-stop rows, the follow-through rows, then trims
  the give-back and P&L rankings to two each, drops the notes, and finally
  the give-back ranking, cuts the exit lessons to 80 characters and then to
  three rows, then the practice note, then cuts the long holds' theses to 60
  characters, marking itself `trimmed`.
  Totals, planned vs unplanned, the follow-through counts and the practice
  score always stay. One failing section reads `unavailable`.
- No trade, fill, account, plan or investigation id is returned. Research
  jobs never get the tool (`research_job.JOB_TOOLS` is an allowlist), and
  "What changed?" leaves it out of an investigation's evidence times.
- Fixture mode serves a simulated week marked `simulated`; replay says it is
  unavailable. The fake model answers "review my week" (and "review my week
  of YYYY-MM-DD") by calling the tool and writing a short scripted review
  with an exit reviews line quoting a lesson; for a week of 10 or more
  trades it first proposes one practice (exit at the invalidation when a hit
  was held past 15 minutes, quoting a lesson from an exit after the
  invalidation broke, else a plan before every entry when trades had none).
  The fixture's week has 8, so it proposes none; its three exited plans have
  two answered lessons (no thread: each line opens its symbol), and it sheds
  its provenance labels to fit, as a real week does.
- Tests: `backend/tests/test_copilot_week_review.py`,
  `frontend/e2e/review-my-week.spec.ts`.

**Automatic.** With `WEEK_REVIEW_AUTO_ENABLED=true` (off by default; nothing
runs while `COPILOT_ENABLED` is off) the review runs by itself once a week
(`backend/app/engine/week_review_auto.py`, additive table `week_review_auto`,
migration `d2a7e5c9f3b1`), so the owner never has to press the button:

- **When:** at `WEEK_REVIEW_AUTO_AT` (`HH:MM` New York, default `16:45`) on
  the week's last trading day per the market calendar: Friday, or Thursday
  when Friday is a holiday. The week (its Monday) is claimed once, so a
  restart or a second process never runs it twice; a review not started by
  midnight New York waits for the next week. A week with no closed trade
  (the tool reads `none`) is recorded `skipped`: no turn, no ping.
- **Turn:** one `run_turn` on the configured backend and evidence, its turn
  budget cap included, whose owner message is the Review my week context naming
  the week, as a Friday's Daily Review link sends it:
  `Context: Review my week of <Monday>`. So the model calls `get_week_review`,
  opens with the practice score while a goal is active, and proposes one
  practice when the counts support it, exactly as above. The answer is saved as
  an open copilot investigation titled `Week review Oct 19–Oct 23` (Monday to
  Friday), so it shows in the desk's thread list. A proposed practice is kept on the
  `week_review_auto` row, and `GET /copilot/practice?investigation=<id>`
  returns it as `proposed`, so opening that investigation shows the practice
  card under the answer until it is confirmed (a goal saved from that
  investigation) or a later week's review replaces it. Nothing is saved as a
  goal until the owner confirms the card.
- **Ping:** title `Your week: +$412 · 3 of 5 planned` (the review's P&L and
  trades with a plan captured before the entry, of the week's closed trades);
  body the answer's first two lines (markdown removed), then
  `Practice (<goal>): 2 of 3 this week, 1 of 4 last week` while a goal is
  active, then "Open to confirm next week's practice" when the turn proposed
  one. A tap opens `/copilot-lab?investigation=<id>`. If the turn fails (an
  error event, the budget stop included, or no text), the ping and the saved
  record carry the week's facts instead (trades, P&L, plan timing, the
  invalidation follow-through) under "The week's facts (the copilot turn
  failed):", and no card is kept.
- **Delivery:** through the [notification policy](#phone-ping-policy) as kind
  `week_review`, ranked with the pre-market prep, and the same at-most-once
  outbox as the prep: a send that may have reached ntfy is `unknown` and never
  resent; a review that never finished within 15 minutes, or a ping not sent
  within 2 hours, is `expired`; a gate hold reads `held` with its reason. It
  runs on the level alert monitor's loop beside the prep, the review on its own
  thread. Nothing places, changes or suggests an order.
- Tests: `backend/tests/test_week_review_auto.py`,
  `frontend/e2e/week-review-auto.spec.ts`.

The older `/weekly-review` page (`backend/app/engine/weekly_review.py`) is a
separate, deterministic review of three exit leaks with a rule the owner picks
by hand; it calls no model and the automatic review does not use it.

### The practice goal

The Improve step of the [end goal](product-roadmap.md#end-goal--october-22-2026):
one thing to practice, chosen from the week's counts, confirmed by the
owner and scored the next week (`backend/app/engine/practice_goal.py`,
additive table `practice_goal`).

- A goal confirmed on a weekday counts from that week's Monday; on a weekend,
  from the next Monday. One goal is `active` at a time.
- Each measure is "hit of of" for one Monday-to-Friday week, New York, from
  data the week review already reads (Webull left out):
  - `plan_before_entry`: closed trades with a plan captured before the entry
    (`capture_links.timing`);
  - `exit_at_invalidation`: invalidation pings the fills could judge, acted
    on (closed or trimmed within 15 minutes; [notification
    policy](#phone-ping-policy)). A week with none judged falls back to the
    plans' follow-through (invalidation hit while held, out within 15
    minutes), and `source` says which;
  - `respond_to_giveback_15m`: give-back alerts on the week's trades followed
    by a close or trim within 15 minutes (`exit_habits.follow_up`);
  - `no_trade_after_hour_red` and `no_opening_while_green`: closed long
    options without the `held_hour_lost` or `opened_green` habit flag
    (`exit_habits.habit_flags`); a trade missing the data is left out;
  - `max_trades_per_day`: trading days with at most the cap of trades opened.
- `GET /copilot/practice` (owner-only) returns the active goal and its score
  for the week holding today (the week just ended, on a weekend), or no score
  before its first week. The desk shows it in the Briefing's session line and the
  Dashboard's Review my week button carries it as a second line:
  "Practicing: exit at my invalidation · 2 of 3 this week" (or "starts Mon,
  Oct 26"). Nothing shows while no goal is active.
- No id is returned to the page or the copilot. Research jobs never see it.
- Tests: `backend/tests/test_practice_goal.py`,
  `frontend/e2e/practice-goal.spec.ts`.

## Your history at this level

The setup playbook: when the copilot drafts a trade plan, the card shows what
happened at a level like its invalidation in the owner's own past trades, as
evidence beside the card, never as a rule. Codex's
[invalidation study](../backend/reports/invalidation_study_2026-10-25.md)
(October 25, 2026) replayed 1,528 closed long option trades against session
extremes, opening ranges, VWAP, prior-day extremes, the nearest automatic
level, fixed 1/2/3% moves and 15/30/60/120-minute marks, and found
[no level or time stop that holds up as a default](../backend/reports/invalidation_study_2026-10-25.md#what-holds-up-and-what-does-not):
every mean-return interval includes zero, several flip sign between halves,
15- and 30-minute exits are harmful, and rebounds after a cross are common. Its
three wording candidates are
[for the owner's approval only](../backend/reports/invalidation_study_2026-10-25.md#defaults-the-copilot-could-suggest--approval-only);
the system prompt does not adopt them, and the card's history line links to
that section as "why this is evidence, not a rule".

- `get_level_history(symbol, level, side, entry?, lookback_days?)` (read-only,
  provenance `saved`; `copilot_review.level_history`). `side` is `below` (a
  long's invalidation; counts the owner's closed long calls) or `above` (a
  short's; long puts). The level is matched by **distance**, not price: the
  drafted level's percent from `entry` (the planned entry trigger; the current
  chart-feed price when omitted; `unavailable` when there is none or the level
  is not on `side` of it) is set
  the same percent from each past trade's own entry underlying price (the
  fill's enrichment or its market context, as the path metrics read it). Over
  the owner's trades opened in the last `lookback_days` (30-365, default 180;
  Webull out) it replays the underlying's minute bars from entry to exit from
  the on-disk cache the path metrics filled (`fetch_minute_bars_for_date`,
  cache only, never the network; windows over 10 days are skipped like the
  path metrics) and returns:
  - `sample`: trades counted and `counted` (long calls, long puts or long
    options); fewer than 10 is `small`, with a note that it is too small to
    weigh;
  - `crossed`: how many crossed the level while held (a low under it, or a
    high over it, in a completed bar between the entry and exit minutes), of
    how many had bars; of those, `recovered_to_breakeven` (the option's later
    minute close at or above the average entry premium before the exit, out of
    `recovery_known`) and `median_pnl_from_cross_pct` (the option's P&L from
    its first recorded mark at the cross to the actual exit, in percent of
    that mark, over `valued`), from the contract's minute bars in the window
    the path metrics cached (`_option_bars_cache_path`; None when not cached);
  - `pnl`: the journal's realized P&L, count and win rate for `crossed` and
    `not_crossed`;
  - `coverage`: trades with no entry price, no cached bars or no cached option
    bars; `provenance`, `units` and a fixed `note`: "Your own past trades at a
    similar distance; the invalidation study found no level that holds up as
    a default. Evidence to weigh, not a rule."
- With `minutes` (5-1440) instead of a level, the same for a time mark:
  `held_past` (trades still held then, what the option did from there,
  recovery) and `pnl` split `held_past` / `out_before`, over long calls and
  puts alike.
- No trade, fill or account identifier is returned. Never given to research
  jobs; part of `BOOK_CONTEXT_TOOLS`, so "what changed" leaves it out.
  Simulated in the fixture (31 NBIS calls, 12 crossed), unavailable in replay.
- The system prompt has the model call it for the drafted invalidation (and
  once more with `minutes` when the time stop is a length of time) before it
  proposes a `trade_plan`, say in one sentence what the owner's history shows
  there with the counts, never call a level validated, proven or recommended,
  and say the sample is too small to weigh under 10 trades. The scripted
  `fake` model does the same and quotes the sentence under "Where it's wrong".
- The turn's `tool` event for a successful level read carries `history`: the
  symbol, level, side, distance, counts and medians (`copilot.level_history_card`,
  never ids). The plan card (`TradePlanCard.tsx`) shows the row whose level is
  the plan's invalidation under that field as "Your history at this level:
  12 of 31 past NBIS trades crossed −3.8% while held; 5 recovered; median −18%
  from there", with the link above. When the owner edits the invalidation or
  the entry the line says to re-ask the copilot rather than refetching on every
  keystroke; a
  reloaded investigation has no row (evidence references keep no results).
  The Evidence strip labels the read "Your history here". A draft card also
  shows the symbol's last exit lesson (see The desk § The last lesson comes
  back to the next plan).

## Option candidates

The owner often holds a longer thesis through a short-dated option, so the
instrument question needs real contracts, not just marks of the ones held.

- `get_option_candidates(symbol, horizon_days 1-365, direction long|short,
  budget_usd?)` (read-only, provenance `fetched` with the chains' read time;
  `backend/app/ai/copilot_options.py`). It reads the expiration list and at
  most three chains in one pass through `options_feed.chains`, the Charts
  page's Tradier cache and pacing (a chain is reused for a minute).
- Expiries bracket the horizon: the last one before it, the first at or after
  it and the next one after (weeklies are listed dates like any other); when
  nothing listed reaches it, the longest two, with a `horizon_note`. Calls for
  `long`, puts for `short`, the primary root only, strikes from about 5% in the
  money to 10% out, with a usable bid and ask. At most 8: the first expiry at or
  after the horizon gets the most, each starting at the money and spreading to
  the window's ends.
- Each candidate: expiry, days to expiry, strike, bid/ask/mid per share and per
  contract (× the contract's multiplier; `unavailable` when the chain does not
  give one), spread % of mid, open interest and volume when listed, distance to
  strike %, the break-even move % by expiry paying the ask, and with a budget
  how many contracts it buys at the ask. Delta and implied volatility are
  `unavailable`: the chain carries the provider's greeks, but nothing passes
  them on and the copilot never estimates them. The answer drops rows rather
  than cut its JSON past 6,000 characters.
- No price or no readable chain says so in `state` and `reason` (for example
  "Set TRADIER_API_KEY …"); a chain missing from a pass is `partial`. Fixture
  mode runs a simulated NBIS chain through the same selection; replay is
  unavailable. Not in `BOOK_CONTEXT_TOOLS` (it is market data); never given to
  research jobs.
- The system prompt has the model call it when the owner names an option or a
  horizon, or before a `trade_plan` on options, and compare 2-3 contracts
  against the horizon: premium, spread and break-even move, a contract that
  expires before the thesis named as a mismatch, and trade-offs for the owner
  to choose from, never a recommended contract. The scripted `fake` model does
  the same for "which strike/expiry" or "calls"/"puts" with a horizon.
- The tool event carries `candidates` (`copilot.option_candidates_card`: a
  short label such as "Nov 13 '26 95C", days, ask per contract and per share,
  delta when given, and the chains' read time). The plan
  card offers them as a Contract pick list beside the copilot's own wording,
  which stays the default; the pick goes into the saved plan's note. The
  Evidence strip labels the read "Option candidates".

## Confirm a plan

When asked for a plan, the model may call `propose_plan` (at most two per
answer; one for a memory, one for a trade plan and one for a practice). The tool validates the proposal and writes nothing. The lab streams
it as a `proposal` event and shows a card with **Confirm** and **Dismiss**;
nothing exists until the owner confirms.

- **Watch:** `symbol`, `condition` (`touches`, `crosses` or `closes_beyond`,
  the last with an `interval` of 1m-4h), a positive `price`, a `label` of at
  most 60 characters and a `why` of at most 300. The symbol must have a
  current price in the turn's evidence, so a made-up ticker is refused.
  - Confirm reads `GET /copilot/quote?symbol=X` (the chart feed's last price,
    with how old the read is). A read older than a minute, or no price, is
    refused.
  - Then it calls the existing `POST /charts/alerts` with the fresh price as
    `reference`, `source_kind="copilot"`, `source_id=<investigation id>` and
    the label. That route's limits apply: 20 active alerts, 5 symbols and no
    duplicates.
  - `GET /copilot/status` reports `capabilities.copilot_alerts`, asked of the
    alerts route's own request model. While that route refuses `copilot`,
    the card says "Awaiting alert support" instead of Confirm.
- **Revisit:** a `question` of at most 500 characters and `horizon_days`
  (1-30). Proposals are not evidence, so they are left out of the saved
  investigation's evidence references. Confirm queues a reassess job through
  `POST /copilot/research-jobs/reassess` (Research queue, below). It works
  whether or not alerts are supported.
- **Memory:** something the owner said that is worth keeping across
  conversations: `memory_kind` (`statement`, `thesis`, `preference` or
  `lesson`, the memory store's kinds), `text` (their words or a faithful
  paraphrase, at most 400 characters), an optional `interpretation` (what it
  should change about how the copilot works, at most 300) and an optional
  `symbol` (1-6 letters, the store's form). The system prompt asks for one
  when the owner states a belief, preference, rule or lesson, asks to be
  remembered, or agrees with a conclusion they want kept; never from measured
  counts alone and never about their psychology. The card shows the text in
  an editable box; Confirm saves it through the existing owner-only
  `POST /jo/memories` as an `owner_statement` (the owner edited and
  confirmed the words), `status: active`, `owner_confirmed: true`,
  `source_reference: copilot:<investigation id>`. It needs no investigation
  and no alert support. The memory joins the owner context pack and
  `get_memories` from the next turn. `jo_briefing_common` is untouched: the
  memory store's schema, kinds and sources are the same as Jo's.
- **Trade plan:** one whole plan for a trade the owner wants to take, the
  card the "plan before you enter" loop ends in. When the owner says they
  want to trade something, or the message carries the "Plan a trade:"
  context (the front door's prefill), the system prompt has the model pressure-test it
  first: ask only for what is missing (why now, where it is wrong, how long),
  challenge it with the chart, the group comparison and the owner context
  (their history and habits), and when they are vague ("yolo NBIS calls")
  draft levels from `get_chart_context` rather than interrogate them. Then it
  proposes one `trade_plan` (or says it is not worth a trade):
  - `symbol`; `direction` (`long` = expects up, `short` = expects down);
    `instrument` (`stock`, `calls` only when long, `puts` only when short);
    an optional `contract` hint (text, at most 40); `thesis` (at most 300);
    `entry_trigger` and `invalidation`, each a level as a watch takes it
    (`condition`, positive `price`, `interval` for `closes_beyond`), a long's
    invalidation below its entry and a short's above; optional `time_stop`
    (at most 80) and `size_note` (at most 120).
  - Like a watch, the symbol needs a current price in the turn's evidence,
    and a plan whose price is already past its invalidation is refused.
  - The saved plan's capture context carries the investigation id, so when the
    fill arrives and the owner links it from the link ping's confirm page, that
    page offers "Open its investigation".
  - The card (`frontend/components/copilot/TradePlanCard.tsx`) shows the
    thesis, entry and invalidation prices, time stop and size as editable
    fields with phone-sized tap targets. Under the time stop it shows when it
    would ping, read by the server (`GET /copilot/time-stops/preview`), or
    "Kept as a note" when the words hold no time. Its **Horizon** (Day trade,
    Swing, Long hold; see [the desk](#the-desk)) defaults from that reading: a
    time stop due today makes it a day trade, anything else a swing. The
    pre-trade plan part saves it as a `horizon` day-journal entry.
  - **Size it for me.** A `Risk $` field beside the size (numeric keypad,
    remembered per browser in `localStorage` key `copilot.risk`, blank until
    typed; no server setting) turns a dollar risk into a size as it is typed,
    on the card itself with nothing saved: a stock plan gets whole shares =
    risk ÷ the entry-to-invalidation distance, rounded down, with the dollars
    lost at the invalidation and the cost at a fresh `GET /copilot/quote`. A
    calls or puts plan sizes the contract the card names, at its ask from the
    turn's option candidates (the card says the premium and the chain's read
    time): **max loss** contracts = risk ÷ the ask per contract (the premium
    is all at risk), and **at invalidation**, only when the chain gives a
    delta, about delta × the distance × the multiplier per contract, capped at
    its premium. Delta is `unavailable` today, so that line says so rather
    than estimate one. A contract with no premium on the card (the copilot's
    own wording, or no candidates in the conversation) gets a line saying how
    to pick one, never a guess; a risk too small for one share or contract
    says that. On Confirm the size ("2 contracts of Nov 13 '26 95C at 6.92,
    $1,384 max loss, risk $1,400"; the max-loss count for options) goes in
    front of the size note, the owner's words cut to keep its 120 characters,
    unless the owner edited the note after the size appeared. Spreads,
    account balances and orders are out of scope.
  - Confirm runs three parts
    (four with a time stop it can read), each with its own result; a failed
    part says why and offers a retry of that part only:
    - **Pre-trade plan:** the existing `POST /charts/captures`, mode
      `discretionary`, side from direction and instrument (`buy_stock`,
      `short_stock`, `buy_calls`, `buy_puts`), `setup_label` "Copilot plan",
      `wording` built from the levels, time stop and size, and `note` holding
      the thesis and contract hint, on the capture default account (or the
      only one; the card asks when neither exists). A discretionary capture may
      carry its own setup name and wording for this (`captures.build`). One
      client id per card, so a retried save never makes a second plan. Capture
      linking then suggests it for the trade when the fill arrives, and the
      owner context pack and `get_trade_review` show it.
    - **Entry alert** and **Invalidation alert:** exactly as a watch confirms:
      a fresh `GET /copilot/quote`, then `POST /charts/alerts` with
      `source_kind="copilot"`, the investigation id and the labels
      "NBIS entry: …" and "NBIS invalidation: …", plus `plan_role` (`entry` or
      `invalidation`, a nullable `level_alert` column only a `copilot` alert
      may carry). They run only once the plan is saved, and an invalidation
      the fresh price has already crossed is refused rather than armed on the
      wrong side. Without alert support the card says so and Confirm saves
      only the plan.
    - **Time stop:** `POST /copilot/time-stops` with the card's client id (a
      retry returns the first row), the investigation id, the symbol and the
      words, re-read on the server and saved in `plan_time_stop`
      (`backend/app/engine/plan_time_stops.py`).
  - **Follow-through.** A plan's pings name the plan:
    - When its entry or invalidation alert fires, the phone says
      "NBIS hit your 95.90 entry trigger. Still valid? Tap to check." or
      "NBIS broke your 92.30 invalidation. Your plan says out." The tap opens
      `/copilot-lab?investigation=<id>&context=…`: the investigation, with
      the owner's question ("My entry trigger hit at 95.90 (10:41). Is the
      plan still valid? Check the chart and group now.") in the message box,
      unsent. Delivery is the level alerts' own outbox. A copilot watch with
      no role keeps the plain level message. The open P&L is not added: no
      mark is stored for it, and reading one at send time would add a quote
      call to the alert path.
    - The **time stop** is read as a clock time (`out by 15:30`, `15:30`,
      `3:30pm`; a bare 1-8 o'clock is the afternoon) at the next regular
      session that still has it ahead, today when it can be; a length in
      minutes or hours (`45m`, `2h`, up to 6½ hours) from the Confirm, no
      later than today's close and only while today's session is open; or a
      number of days (`2 days`, up to 30) as that many trading days ahead at
      15:30 ET (half an hour before an early close). The market calendar is
      published only through the current month, so a day count landing in a
      later month skips weekends but not that month's holidays or early
      closes; the preview shows the date. A time outside regular hours, a
      length that reads as a candle or an offset ("5m closes under 92", "10
      minutes before the close"), or words with neither stay a note in the
      plan's wording.
    - At its time, if a position in the symbol whose first entry came after
      the plan is still open (Webull left out), one ntfy ping says
      "NBIS time stop: you planned to be out by 15:30." and opens the trade.
      Otherwise it is recorded `skipped` and nothing is sent. Delivery is at
      most once, as plan nudges': a send that may have reached ntfy is
      `unknown` and never resent, and one not judged or sent within 15
      minutes of its time `expired`. It runs on the level alert monitor's
      loop only while `PLAN_TIME_STOPS_ENABLED=true` (default off); the card
      and the routes work either way and say when pings are off.
    - Tests: `backend/tests/test_plan_follow_through.py`.
  - Fixture demo: "plan a trade" in the owner's words makes the fake model
    read the quote and the 5m chart and propose a long-calls plan (entry on a
    5m close above the nearest level overhead, invalidation through the
    nearest one below).
  - Browser proof: `frontend/e2e/copilot-trade-plan.spec.ts`.
- **Practice:** after a week review, the one thing to practice next week (see
  [Review my week](#review-my-week)): `text` (plain words, at most 200),
  `measure` (one the app can score: `plan_before_entry`,
  `exit_at_invalidation`, `respond_to_giveback_15m`,
  `no_trade_after_hour_red`, `no_opening_while_green`,
  `max_trades_per_day`), an optional `target` (a share above 0 and at most 1;
  for `max_trades_per_day` the daily cap, a whole number from 1 to 20,
  required) and `why` (at most 300, the week's count it rests on). At most
  one per answer: a second is refused to the model in code
  (`copilot._run_tool`'s per-turn state), not only by the prompt. The card
  shows the text in an editable box, the measure ("Scored as: …") and why.
  Confirm saves it through the owner-only `POST /copilot/practice`
  (`backend/app/routers/copilot_practice.py`) as the one active goal; a goal
  already active ends (`scored` once its first week is over, `dropped`
  before). Only when the owner ticks "Remember this too" does Confirm also
  save it through `POST /jo/memories` as a `lesson`, the way a memory card
  does. It needs no investigation and no alert support.
- **Linked activity:** under an open investigation, the lab lists its level
  alerts (`source_kind == "copilot"`, `source_id ==` its id) with their state
  (armed, or fired with a time and price; a plan's as "Entry · armed/hit" and
  "Invalidation · armed/hit"), its plan time stops (pending, sent, skipped
  with why, not sent, or may have sent) and its revisit jobs, each from its
  own route (`GET /copilot/time-stops?investigation=<id>` for time stops).
- **Kept cards.** Each card is saved with its answer in the investigation's
  transcript, so switching threads or reloading brings it back as it was
  left: pending with Confirm, confirmed with what Confirm said (a plan card
  with its fields and each part's result, locked; a failed part can still be
  retried), or dismissed and hidden. Bringing a card back creates nothing;
  Confirm stays the only way anything is made.
  - A card gets one `client_id` when it arrives, saved with it, used for its
    plan capture, time stop and memory saves, so a Confirm retried after a
    reload or from a second window returns the first record.
  - Confirm or Dismiss records the card's `outcome` at once through
    `PUT /copilot/investigations/{id}/proposals/{proposal_id}/outcome`
    (`state` `confirmed` or `dismissed`, Confirm's note, a memory's or
    practice's saved words, a plan's part results and fields). It needs no
    revision and does not bump it. A card that may not be saved yet (its turn
    still running, or that turn's save in flight) is recorded once that save
    lands.
  - A saved outcome is never lost to a save from a window that had not seen
    it, and a confirmed card stays confirmed. Before Confirm runs, the card
    re-reads the investigation; if another window already confirmed it, it
    shows that result instead of making anything. Watches and plan alerts
    have no client id; if two windows press Confirm in the same moment, the
    alerts route refuses the same alert twice in a day, so the second says
    "This alert is already set."
  - A confirmed step also remains as linked activity.
  - Browser proof: `frontend/e2e/copilot-keep-drafts.spec.ts`.
- `/copilot-lab?investigation=<id>` opens that saved investigation with
  "What changed?" ready; with `&context=…` (a plan alert's link) that text is
  ready instead.
- Conditional plans and follow-ups (Jo) are not touched.
- Browser proof: `frontend/e2e/copilot-plan.spec.ts`.

## Origin

Every pre-trade plan records what prompted it, so a trade can be traced back to
the observation behind it (the end goal's step 5).

- **On the plan.** `TradeCapture` has `origin_kind` (`radar_event`,
  `thesis_watch`, `premarket_prep`, `chart`, `dashboard`, `copilot`, `manual`),
  `origin_ref` (the Radar event id, the thesis-watch trigger id or the
  investigation id) and `origin_text` (the context line, at most 300
  characters). `captures.build` refuses an unknown kind; a plan saved with no
  origin is `manual`. Migration `c4e8a2f6d1b9` adds the columns (nullable:
  older plans have none).
- **Through the front door.** Deep links carry `origin=<kind>[:<ref>]`
  (`copilotLabHref`, read by `readDeepLink` in `frontend/lib/copilot.ts`).
  Radar's Plan a trade and Ask copilot pass the event id; a thesis-watch ping
  passes its trigger id; the pre-market prep passes its investigation id;
  Charts and the plan sheet pass `chart`, the Dashboard `dashboard`, the phone
  tab bar `manual`. The lab keeps it with the conversation (a new or another
  investigation is `copilot`, with the investigation id), and the plan card
  sends it with the capture. A plan typed on the Charts plan sheet is `chart`;
  a voice plan is `manual`.
- **Shown.** The trade page's Pre-trade plan reads "From: Radar event, MU
  +4.1% vs SMH, 10:41" and links to `/radar?event=<id>` or the investigation.
  `get_trade_review` has an `origin` section: the kind, the context line in
  words and, for a Radar event, its summary and rating from the Radar file;
  never an id (`app/ai/copilot_origins.py`). `get_week_review` has `origins`:
  one line of trades and P&L by origin kind (`no_plan`, and `unrecorded` for
  plans saved before origins). Radar's event detail shows **Planned** and
  **Traded**, and `/proof` counts events that led to a plan and to a trade
  ([Radar](radar.md#proof-read-out)).
- Tests: `backend/tests/test_trade_origin.py`, `frontend/e2e/trade-origin.spec.ts`.

## Phone ping policy

One policy for the app's own phone pings (`backend/app/engine/notification_policy.py`),
so an invalidation ping, a give-back alert, a time stop and the one-hour alert cannot
all hit one position within minutes. Jo's senders (Codex) are not gated.

- **Where:** each copilot-side sender (open-trade alerts, plan nudges and link pings,
  plan time stops, a confirmed plan's entry and invalidation alerts, pre-market prep,
  the automatic week review, Watch your day, the evening review, Radar alerts,
  thesis watch, research results) calls
  `notification_policy.decide` right before it hands a message to ntfy, and keeps
  its own at-most-once delivery, caps and expiry. `ntfy.py` stays a transport.
  Radar alerts and thesis watch are anchored per symbol (the symbol's open
  position when there is one; a Radar group event to its group); a ping they
  hold is recorded `held` and counts toward neither sender's own caps.
- **Daily cap:** at most `PING_DAILY_CAP` (default 12) pings a New York day across
  every kind. The priority order keeps the cap from dropping what matters:
  last-day final > invalidation > give-back > time stop (and the 90-minute
  last-day alert) > entry trigger > hold-hour > nudge/link > prep (and the
  automatic week review, Watch your day and the evening review) > Radar >
  thesis watch > research. The first three are
  never over the cap; the last five are held once only 3 slots are left.
- **Quiet window:** a second ping anchored to the same position within
  `PING_QUIET_MINUTES` (default 10) of one that was sent is not sent on its own:
  a different kind whose predecessor is still being resent (its send failed) is
  `merged`, its text appended to that resend; otherwise it is `suppressed`. A
  more important kind is never held by the window, and a last-day final or an
  invalidation is never held by it at all (a second plan's invalidation in the
  same symbol is its own message).
- **Evening review:** once a trading day (the market calendar: no weekend or
  holiday) at `EVENING_REVIEW_PING_AT` (default `16:30` New York; a time before
  16:00 keeps the default), `app/engine/evening_review.py` reads what the desk
  has waiting through `copilot_desk.waiting`, what Close the day walks: the
  symbols still asking their close question, today's position alerts with no
  feedback, today's Radar hits not rated and the fills waiting to link (older
  alerts and hits stay in the Briefing's lists and never ping). When any is waiting it sends one ping, "Close the day: To
  review: 2 threads, 3 alerts, 1 fill to link.", that opens
  `/copilot-lab?close=1` on Close the day (kind `evening_review`, ranked with
  the prep). Nothing waiting, the lab off, or a desk source (positions, plans,
  alerts, Radar) that cannot be read is recorded `skipped` with why and sends nothing. One `evening_review` row a day (unique day, additive
  migration `d2e7a4c9b1f6`): `skipped`, `held`, `sent`, `unknown` (may have
  reached the phone, never resent) or `expired`. A day not counted by two hours
  after its time waits for the next. A Skip or "No plan" kept only in a browser
  is not seen by the count. **Switch on:** `EVENING_REVIEW_PING_ENABLED=true`
  in the API's environment (needs `COPILOT_ENABLED=true` and `NTFY_URL`),
  restart the API; it runs on the level alert monitor's loop. Off by default.
  Tests: `backend/tests/test_evening_review.py`,
  `frontend/e2e/copilot-desk-keys.spec.ts`.
- **Record:** every decision is one `phone_ping` row (`sent`, `merged`,
  `suppressed`, `over_cap`, with the reason). A held sender row reads `held`
  with the same reason on the trade page's phone-alert list; the Dashboard Plans
  card shows `Held back today: 3 pings (2 plan nudge, 1 one-hour)`. A gate that
  cannot read or write its table tells the sender to send.
- **Acted on:** a pass on the level alert monitor's loop writes, from the fills
  and the plan links as they arrive and never by guessing, what followed each
  delivered ping: an entry trigger, an entry fill in the symbol within 30
  minutes; an invalidation, time stop or open-trade alert, the position closed
  or trimmed within 15 minutes; a nudge or link ping, a plan linked within 30
  minutes. The trade page shows it per ping (`then: closed in 6 min`) and
  [Review my week](#review-my-week) counts it by kind.
- **Pictures:** after the policy says send, each sender attaches a small chart
  (`backend/app/engine/ping_images.py`, drawn by `chart_render.py`): a plan's
  trigger or invalidation shows the last 90 minutes with the plan's levels and
  the fill, an open-trade alert the entry, peak and now, a time stop the day with
  the stop time, a nudge or link ping the fill, Radar the stock against its
  benchmark, thesis watch the move from its reference, pre-market prep the open
  options by days to expiry. The PNG goes to ntfy as the attachment; a picture
  that fails, finds no bars or takes over 2 seconds, or that ntfy refuses, leaves
  the ping as text, never later or dropped; a retry after a failed send goes as
  text. The picture never changes a decision;
  `phone_ping.image` records `attached`, `none` or `off`. `PING_IMAGES_ENABLED`
  (default true) turns pictures off without touching the pings.
- **Activation:** `ALERT_POLICY_ENABLED` defaults to **true**. It only ever reduces
  pings, every sender keeps its own switch, and a held ping is recorded rather
  than lost, so there is nothing to prove before switching it on; `false` passes
  everything through (still recorded). Settings in the table below.
- Tests: `backend/tests/test_notification_policy.py`.

## Pre-market prep

One phone ping each trading morning with what the owner already holds and has
planned (`backend/app/engine/premarket_prep.py`). It is the copilot's own short
prep; Jo's morning briefing (`/morning`) is separate and untouched.

- **When:** at `PREMARKET_PREP_AT` (default `08:30` New York) on a day the
  market calendar has a regular session, never a weekend or holiday. The day is
  claimed once (`premarket_prep.day` is unique, additive migration
  `e5a9c3d7f2b4`), so a restart or a second process never sends a second one.
  A prep not started within an hour of its time waits for the next trading day.
- **Pack:** open positions with days to expiry, expires-today, give-back watch
  state and open P&L (the owner context pack's positions section); armed plans
  with their distance to the entry and the invalidation (the Plans board's
  `copilot_plans.board`, one batched quote); earnings from today through Sunday
  for held symbols and symbols with an active thesis memory (one batched
  Tradier calendar read, at most 8 symbols); today's pending time stops; the
  plan streak. A section that fails reads `unavailable`; the rest stand.
- **Turn:** one `run_turn` on the configured backend and evidence, system
  prompt unchanged, its turn budget cap included. The message starts "Pre-market
  prep for …" and asks for at most 6 lines from those facts only: what expires
  or sits near a trigger today and one thing to decide before the open. The
  answer, cut to 6 lines, is saved as an open copilot investigation titled
  `Pre-market prep <date>`, so it shows in the desk's thread list.
- **Ping:** title `Pre-market prep`, body the first two lines; a tap opens
  `/copilot-lab?investigation=<id>`. If the turn fails (an error event,
  including the budget stop, or no text), the ping and the saved record carry
  the raw facts instead (expiries, the nearest triggers, today's time stops,
  earnings this week) under "Raw facts (the copilot turn failed):".
- **Delivery:** the same at-most-once outbox as plan nudges: a send that may
  have reached ntfy is `unknown` and never resent; a prep that never finished
  within 10 minutes, or a ping not sent within 30 minutes, is `expired`.
- **Activation:** off unless `PREMARKET_PREP_ENABLED=true`, and nothing runs
  while `COPILOT_ENABLED` is off. It runs on the level alert monitor's loop
  beside the plan pings; the reads and the model turn run on their own thread.
  Nothing places, changes or suggests an order.
- Tests: `backend/tests/test_premarket_prep.py`.

## Explain this candle

`get_moment(symbol, at, timeframe?)` (`backend/app/ai/copilot_moment.py`) reads
one moment on the chart, anchored at `at`: New York time as ISO
(`2026-10-23T10:40`; an offset or `Z` is converted) or epoch seconds, within
the last 400 days and not in the future. `timeframe` is any Charts interval
but 1W (1m, 3m, 5m, 15m, 30m, 1h, 4h, 1D), default 5m. It returns:

- the candle holding `at` and the 12 either side (New York time, OHLC, volume,
  relative volume, extended-hours flag), from the Charts page's own feeds:
  today's Tradier minutes (the workspace's cached request), an earlier
  session's stored SIP minutes (fetched once and stored when missing), the
  daily history for a 1D candle;
- VWAP and its 1σ through the candle, and the session's open, high and low
  through it (the premarket's before the open) with the prior close;
- the nearest automatic level zones each side, recomputed by
  `chart_levels.compute_levels` as of the candle's start, so a level that
  formed later never shows;
- Radar's comparison at that pass (the symbol against SPY, QQQ and its
  group, recorded passes up to `at` in that session);
- headlines published within 60 minutes either side (publisher, New York
  time, minutes from the moment; untrusted text): the news feed's cached
  week, else one bounded Alpaca read around the moment;
- the owner's fills in the symbol within 30 minutes (side, contract,
  quantity, price; Webull left out) and phone pings within 15 (sent
  `phone_ping` rows and Radar pings: kind and minutes only, never their text).

Provenance `fetched` with the bars' as-of; no account, trade, fill or ping id.
The answer is trimmed to 6,000 characters, never cut (the radar's session
window, links, then a narrower window go first). "What changed" leaves it out
(its as-of dates a past candle). The prompt says: call it for a moment or the
"Explain this candle:" context, say what moved it in order of evidence (a
headline with its time, then the group and SPY, then the symbol's own level or
VWAP), then what the owner did there and what it cannot tell, and never invent
a cause. The fixture serves a simulated session around the asked time; replay
gives the frozen store's Radar reading and the headlines before the frozen
time, with bars, fills and pings unavailable, and refuses a moment after it.
Tests: `backend/tests/test_copilot_moment.py`, `frontend/e2e/explain-candle.spec.ts`.

## Watch your day

At the close, a short replay clip of today for each symbol the owner traded,
scrubbed by thumb on `/replay/<date>` (`backend/app/engine/day_replay.py`,
`backend/app/routers/replay.py`, `frontend/components/replay/ReplayView.tsx`).
No model call; it runs whether or not the lab is on.

- **Clip:** per symbol with a fill that day (Webull left out while dormant),
  300 frames at 10 a second (30 seconds) of the regular session, widened to
  take in a fill outside it. `chart_render.frame` draws each at 720×360 on a
  fixed time and price axis: the bars up to the frame's minute as 3-minute
  candles, the confirmed plan's trigger and invalidation from when they were
  armed, each fill as a BUY or SELL dot as it happens (an option's on the
  underlying at its minute), a PING line when a phone ping for the symbol went
  out, and the clock in the corner. Bars come from storage only: the stored
  session, or for today the chart feed's minutes the chart and ping pictures
  already read.
- **Format:** an animated PNG (`chart_render.apng`), not a GIF: the dark theme
  is already an 11-colour palette, so APNG keeps it exactly with no
  quantising. Every frame is whole, so the page cuts the file into frames
  (`frontend/lib/apng.ts`) and draws the chosen one to a canvas under a range
  input; a browser cannot seek an animated `<img>`. A clip over 8 MB keeps every
  other frame, then halves the picture, until it fits. About 0.6 s and 0.8 MB
  for a full session.
- **When:** at 16:20 New York on a trading day, claimed once (`day_replay.day`
  is unique, additive migration `b7d3f1a9c5e2`), built on its own thread. A day
  with no fill is `skipped`: nothing built or sent. A day not claimed by 18:20
  waits for the next, and fills that arrive after the claim are not in the clips.
- **Ping:** one, "Watch your day: NBIS, SPY · 3 fills, 2 pings", with the
  first clip's last frame as its picture, through `notification_policy.decide`
  (kind `day_replay`, ranked with the prep). A tap opens `/replay/<date>`.
  At-most-once delivery as the week review's.
- **Kept:** files under `<CAPTURE_STORAGE_DIR>/day-replay/<date>/` for 14 days,
  then deleted. `GET /replay`, `GET /replay/{date}` and
  `GET /replay/{date}/{symbol}` are owner only and carry no ids. Today shows
  "Watch today" and a trade page "Watch the day" while a clip of it is kept.
- **Activation:** off unless `DAY_REPLAY_ENABLED=true`; it runs on the level
  alert monitor's loop. Tests: `backend/tests/test_day_replay.py`,
  `frontend/e2e/replay.spec.ts`.

## The copilot can see

Two kinds of image reach the model, never more than **two per turn**:

- **A screenshot the owner shares.** The composer's attach button (beside the
  mic; a file picker with `accept="image/*"`, so a phone offers its camera roll
  and camera) uploads to owner-only `POST /copilot/images` (multipart `image`).
  The installed app's web manifest also has a `share_target`
  (`frontend/app/manifest.ts`): sharing an image to Trade Journal from another
  app posts it to `frontend/app/share-target/route.ts`, which stores it through
  the same route and opens `/copilot-lab?image=<id>&context=Plan a trade from
  this screenshot` with it attached and nothing sent (Android Chrome supports
  share targets; on an iPhone use the attach button). With no words of the
  owner's own in the box, it fills with `Here is my chart. What do you see,
  and what would the plan be?`. The thumbnail shows with a remove button and
  then on the sent message. `POST /copilot/chat` takes `image_ids` (two at
  most), attached as image blocks ahead of the owner's text on that message
  only; every id is deleted when the turn ends, and one never sent is swept
  after 24 hours (`GET /copilot/images/{id}` serves it meanwhile, for the
  share-sheet thumbnail). History and the saved transcript keep the text
  marker `[shared a screenshot]`, never the image.
- **Look at my chart.** In the Charts dock's Copilot tab, **Look at my chart**
  takes the main chart's canvas as drawn (the same snapshot a saved plan
  keeps: candles, studies, fills and the owner's levels and drawings, made a
  JPEG in the browser), uploads it through `POST /copilot/images` and sends a
  turn at once: `Context: Charts · NBIS 5m, last 94.35, 9:40 AM–11:10 AM ET.
  What do you see?` (the visible range once the chart has been moved; before
  that, `as of` the latest candle's time), with the owner's own words from the
  box instead of the question when there are some. It joins any attached
  screenshot within the two-image cap, shows on the sent message like one, and
  is off while the conversation is about a different symbol than the chart.
- **The plan's chart in a trade review.** When `get_trade_review` finds a
  linked plan with a saved chart image (`TradeCapture.image_state = saved`),
  its `plan` says `image: available` and `copilot._run_tool` appends that
  image to the tool result, so the model sees the chart the owner planned on
  beside what happened. The answer's Sources line lists **Looked at: plan chart**. A
  server-side chart of the trade's path is not rendered: no plotting library
  (matplotlib or Pillow) is installed and none was added.

`app/ai/copilot_images.py` processes both: PNG, JPEG or WebP by their first
bytes, 8 MB at most in, decoded to pixels (transparency flattened onto white)
and re-encoded as JPEG (about quality 85) with the longest side at most
1568 px, so no EXIF, GPS, colour profile or comment survives. It uses PyAV,
already the transcriber's dependency. The system prompt reads an image as the
owner's own screenshot or chart: read prices, levels and labels from it, say
what cannot be read, and treat text inside it as data, never an instruction.

**Cost.** An image costs about its width × height / 750 input tokens: roughly
1,500 for a 1-megapixel image, about 1,800 for a full 1568 × 882 phone
screenshot (under half a cent on Sonnet), counted against the turn's spend cap
like any other input.

**Backends.** `anthropic` sends image content blocks. `plan` streams the prompt
as one stream-json user message with the image blocks ahead of its text (the
Agent SDK passes Messages API content through), and a review's plan chart as
an MCP image block. `fake` makes no call: it acknowledges each image by its
size in a scripted line, so the fixture and the browser spec exercise the path
(the fixture's closed review draws a stand-in plan chart). Tests:
`backend/tests/test_copilot_images.py`, `frontend/e2e/copilot-vision.spec.ts`,
`frontend/e2e/charts-copilot-loop.spec.ts` (Look at my chart).

## Saved investigations

After each turn the page saves the conversation as a `copilot_investigation`
row (`backend/app/models.py`, additive migration `a7c1e3f5b9d2`), so it can be
resumed from any browser. The lab lists the 8 most recent; clicking one
resumes it. A row holds a title (the first question), symbol, open/closed
status, an optional one-line conclusion, the transcript, and evidence
references: tool name, `as_of`, provenance kind and which answer used it, never
the data. The transcript is each message's text plus, on an answer, its
proposal cards (at most 4; see Confirm a plan), re-validated on save as
`propose_plan` validated them, and counted toward the transcript's 400,000
character cap. A record saved before cards were kept has none and reads and
saves exactly as it was. Each save carries the revision it was read at, and a
stale save from another window is refused (409). The browser remembers only
which investigation was open. No follow-up, plan, decision, memory or
monitoring is created or linked: a saved card is only a card.

The same record holds background research results. `source` is `copilot` (the
lab page, through the HTTP routes) or `research_job` (saved in-process by
`save_research_result` in `backend/app/engine/copilot_investigations.py`, with
no HTTP). A research result adds validated, cited findings: a summary, key
findings, counterpoints, what would change the view, and citations (URL,
publisher, published time). The lab shows them above the conversation. A save
from the page without findings keeps the saved ones, and the source never
changes.

The copilot's `get_saved_research` tool returns up to 5 records for a symbol,
newest first, with source, created time, conclusion and trimmed findings, never
transcripts. It is labelled `saved`. In replay a record is visible only if the moment its
evidence describes (a research job's `evidence_at`, else the record's creation
time) is at or before the frozen moment. Fixture mode returns none.

## Settings (private backend environment)

| Variable | Default | Meaning |
|---|---|---|
| `COPILOT_ENABLED` | unset (off) | `true` turns the routes on. On in production since 2026-10-24 (below). |
| `COPILOT_BACKEND` | `fake` | `fake` is a scripted stand-in that makes no API call. `anthropic` uses the Messages API and spends credits. `plan` runs on the owner's Claude plan through the Agent SDK and spends no API credits (below). |
| `COPILOT_EVIDENCE` | `fixture` | `fixture` returns SIMULATED neocloud data; the model is told so in its context line, in a `"simulated": true` marker on every tool result and in the system prompt, and says so in its answer. `live` reads this installation's Radar, news, Tradier and quote services. `replay` reads a recorded session at a frozen moment (below). |
| `COPILOT_REPLAY_STORE` | none | `replay` only: path to a read-only copy of a Radar store. |
| `COPILOT_REPLAY_AT` | none | `replay` only: New York time inside a recorded session, e.g. `2026-10-23T11:12`. |
| `COPILOT_MODEL` | `claude-sonnet-5-5` | Model id for `anthropic` and `plan`: the default for a turn. |
| `COPILOT_MODELS` | `claude-sonnet-5-5,claude-opus-5-5,claude-fable-5-1` | The models the panel's **Model** picker offers, comma-separated; `COPILOT_MODEL` is always offered first. A turn sends its pick as `model` in `POST /copilot/chat`; one not in this list is refused (422). The pick is remembered per browser, and the metrics line in each answer's Sources shows the model that actually answered. A model with no entry in `copilot.PRICES` is costed at the dearest known price, so the turn budget errs high. |
| `COPILOT_EFFORT` | `medium` | `low`, `medium` or `high`. |
| `COPILOT_BACKENDS` | `anthropic,plan` | The backends the panel's **Backend** picker offers, comma-separated; `COPILOT_BACKEND` is always offered first. Each is offered only when usable: `anthropic` needs the API key; `plan` needs the token and the SDK and, off a local database, `COPILOT_PLAN_REMOTE_OK`. A turn sends its pick as `backend` in `POST /copilot/chat`; one not offered is refused (422). Remembered per browser. |
| `COPILOT_PLAN_REMOTE_OK` | unset (off) | `true` lets the `plan` backend run against a hosted database: the owner accepts the Claude plan's terms for this app, as already done for research jobs (`RESEARCH_AUTH=plan`). Without it the plan backend stays local-only. |
| `COPILOT_DAILY_BUDGET_USD` | `2` | Estimated API spend (New York day, `anthropic` turns only) at which `POST /copilot/chat` refuses further API turns with a 429 until tomorrow; plan turns are unaffected. Every turn is recorded in `copilot_turn` (`app/ai/copilot_spend.py`: backend, model, rounds, tokens, estimated cost; no text), `GET /copilot/status` reports `spend_today_usd`, and the panel shows "API today $x of $y" while the API backend is picked. Turn metrics also reach the server journal at INFO. |
| `COPILOT_TURN_BUDGET_USD` | `0.25` | Estimated API spend at which a turn stops between rounds (output is also capped at 4,000 tokens per round). Not applied to `plan`, which bills nothing per token: a plan turn is bounded by its rounds and tool calls, and a failed plan turn's error carries Claude Code's own reason (for example an HTTP 400's message). |
| `COPILOT_FALLBACKS` | on | Sends the server-side refusal fallback (`fallbacks: "default"`). `off` disables it. |
| `ALERT_POLICY_ENABLED` | `true` | The [phone ping policy](#phone-ping-policy) for the app's own pings. `false` passes every ping through. |
| `PING_DAILY_CAP` | `12` | Pings a New York day across every kind; last-day final, invalidation and give-back are never over it. |
| `PING_QUIET_MINUTES` | `10` | A second ping for the same position inside this window is merged or suppressed. |
| `PREMARKET_PREP_ENABLED` | unset (off) | `true` sends the [pre-market prep](#pre-market-prep) ping on trading mornings (needs `COPILOT_ENABLED` and `NTFY_URL`). `PREMARKET_PREP_AT` (`HH:MM` New York, default `08:30`) sets its time. |
| `WEEK_REVIEW_AUTO_ENABLED` | unset (off) | `true` runs [Review my week](#review-my-week) by itself once a week and pings it (needs `COPILOT_ENABLED` and `NTFY_URL`). `WEEK_REVIEW_AUTO_AT` (`HH:MM` New York, default `16:45`) sets its time on the week's last trading day. |
| `EVENING_REVIEW_PING_ENABLED` | unset (off) | `true` sends the [evening review ping](#phone-ping-policy) on a trading day when something waits for review (needs `COPILOT_ENABLED` and `NTFY_URL`). `EVENING_REVIEW_PING_AT` (`HH:MM` New York, default `16:30`, not before 16:00) sets its time. |
| `DAY_REPLAY_ENABLED` | unset (off) | `true` builds [Watch your day](#watch-your-day) at 16:20 New York on a trading day with a fill and pings it (needs `NTFY_URL`; not the lab). |
| `ANTHROPIC_API_KEY` | none | Read only by the backend process for `anthropic`. It is never sent to the browser, and `plan` never passes it to Claude Code. |
| `CLAUDE_CODE_OAUTH_TOKEN` | none | `plan` only: the plan token from `claude setup-token`. |
| `TJ_CLAUDE_CONFIG_DIR` | a private temp directory | `plan` only: Claude Code's state directory, never the owner's `~/.claude` (shared with `backend/app/ai/plan_runner.py`). `TJ_CLAUDE_BIN` picks the Claude Code binary the same way. |

A model id the price table doesn't know (a dated id, or a fallback model the API reports) is priced at its
known base model, otherwise at the dearest known price, so the per-turn cap always applies.

**In production.** The lab is on on the VPS since October 24, 2026: `COPILOT_ENABLED=true`,
`COPILOT_BACKEND=anthropic`, `COPILOT_EVIDENCE=live`, model from `COPILOT_MODEL`, in
`/etc/tradejournal/backend.env` (undo copy `backend.env.before-copilot`). Five pings were switched on there
on October 25, 2026: `PLAN_NUDGE_ENABLED` (undo copy `backend.env.before-plan-nudge`), then
`PLAN_TIME_STOPS_ENABLED`, `PREMARKET_PREP_ENABLED`, `RADAR_ALERTS_ENABLED` and `THESIS_WATCH_ENABLED`
(undo copy `backend.env.before-four-pings`). Every one passes through the [phone ping policy](#phone-ping-policy).
Cost estimates use $2 / $10 per million input/output tokens for Sonnet 5.5
($0.20 cache read, $2.50 cache write). These are estimates only; the Anthropic
Console is authoritative.

## Plan backend (`COPILOT_BACKEND=plan`)

`backend/app/ai/copilot_plan.py` runs the same turn through the Claude Agent
SDK for Python (`claude-agent-sdk`, an optional extra:
`pip install -e '.[copilot-plan]'` in `backend/`). Claude Code signs in with
the plan token, so a turn uses the owner's Claude subscription, never API
credits.

- **Local development and testing only.** Anthropic's current terms point
  products built on the Agent SDK at API keys. The
  [Agent SDK overview](https://code.claude.com/docs/en/agent-sdk/overview)
  says: "Unless previously approved, Anthropic does not allow third party
  developers to offer claude.ai login or rate limits for their products,
  including agents built on the Claude Agent SDK." The
  [legal and compliance page](https://code.claude.com/docs/en/legal-and-compliance#authentication-and-credential-use)
  says OAuth "is designed to support ordinary use of Claude Code and other
  native Anthropic applications". It also says developers "including those
  using the Agent SDK, should use API key authentication", and that Pro and Max
  limits "assume ordinary, individual usage of Claude Code and the Agent SDK".
  The owner using their own token, made with `claude setup-token` (documented
  "for CI pipelines, scripts, or other environments where interactive browser
  login isn't available"), to test their own single-user app on their own
  machine is that kind of individual use: no one else signs in and nothing is
  routed for other users. A backend on the VPS is a running product service,
  which these pages point at API keys. So `plan` refuses to start unless the
  database is local (`app.environment.describe().is_local`, as replay does).
  Production uses `anthropic` with an API key, or written approval from
  Anthropic first.
- **Owner's decision for research jobs (2026-10-24).** The owner chose the
  plan for background research jobs on the VPS, in their words: "use my
  Claude subscription (plan token) for VPS research jobs. It's my own
  single-user app and I accept the terms risk."
  - `RESEARCH_AUTH=plan` is therefore allowed on any database
    (§ Research job).
  - This chat backend (`COPILOT_BACKEND=plan`) stays local-only.
  - The quotes above still describe Anthropic's guidance; the owner accepted
    that risk knowingly.
- **Authentication.** Run `claude setup-token` and put the value in
  `CLAUDE_CODE_OAUTH_TOKEN` in the private backend environment. Claude Code
  gets the environment from `plan_runner` (a short allowlist plus the token);
  the SDK passes the backend's whole environment otherwise, so every other
  variable is set to empty for the child, including `ANTHROPIC_API_KEY`,
  `ANTHROPIC_AUTH_TOKEN`, `ANTHROPIC_BASE_URL`, cloud-provider switches and
  the database URL. Before the first turn in a process, `claude auth status`
  run under that exact environment must report the plan token as the sign-in.
  Otherwise the chat returns 503 and asks for `claude setup-token`. It never
  falls back to an API key.
- **Same limits.** Only the eight lab tools, as in-process SDK MCP tools that
  call `copilot_tools.validate()` and the same timed, bounded runner; the same
  8-call cap (later calls get an error result), 4 model rounds (`max_turns`),
  120 s per turn and the spend cap above.
- **What it cannot do.** No built-in tools (`--tools ""`, `--restricted`):
  no shell, file, edit, web, search or subagent. No slash commands, no
  `@path` expansion of prompt text (`verbatim_prompts`), no settings files, no
  other MCP servers, no session persistence and no resume.
- **Differences from `anthropic`.** Claude Code takes one prompt per turn, so
  earlier text-only turns are quoted into it. There is no server-side
  fallback setting. Claude Code adds its own small overhead per call, so token
  counts are not directly comparable with the Messages API backend. The
  metrics' `cost_usd` is Claude Code's API-price estimate for the same tokens,
  shown as "API-equivalent · Claude plan (no API credits)". It is not a bill;
  the plan's usage limits apply instead (a limit hit is reported as
  `plan_limit`).
- **Verified live on 2026-10-24** (local backend, `fixture` evidence, Agent SDK
  0.2.174, Claude Code 2.1.278): the three-step NBIS demo ran on the plan with
  2–3 tools per turn, 11–14 s per turn and about $0.03 API-equivalent per
  turn, with no API key present. Live evidence and plan usage-limit responses
  have not been tried. A replay of Fri 2026-10-23 11:12 ET (the recorded Radar
  snapshot) also ran three turns on the plan: 3 tools per turn, 10–14 s per
  turn and $0.025–0.040 API-equivalent. The answers stayed at the frozen moment
  and named no later price or headline.
- **Streaming caveat.** A short opening line written before the tool calls
  streams live. The final answer, written after the tool rounds, reaches the
  page in one burst at the end, so first-text latency is close to the total
  when the model writes no opening line. The `anthropic` backend shows the
  same burst: on Sonnet 5.5 the API holds the whole post-tool answer
  server-side (see Live measurements), so it is not a plan-path problem. The
  status line keeps the wait visible; it does not shorten it.

## Replay

`replay` lets the lab investigate a real recorded session outside market hours
without hindsight (`backend/app/ai/copilot_replay.py`). It refuses to run unless
the backend's database is local. The model is told the clock is frozen at
`COPILOT_REPLAY_AT`, and:

- the group comparison is the existing Radar comparison with "now" set to the
  frozen moment, so later passes are never read;
- quotes come from the last recorded Radar pass at or before that moment;
  symbols Radar does not record return no price;
- news is the live feed filtered to headlines published at or before that moment;
  undated headlines are dropped;
- earnings dates are computed as of the replay date, with later reports removed,
  and their fetch time is reported as the frozen moment;
- peer moves are refused, because they read today's quotes.

A replay store is a read-only snapshot of the VPS Radar file, taken with
SQLite's backup API from a `mode=ro` connection and copied off the server.
Keep it outside the repository. It holds market quotes only, no account data.

## Live measurements (2026-10-24)

Sonnet 5.5 on the Messages API, effort `medium` unless noted, replay of Fri
2026-10-23 11:12 ET unless noted. "First feedback" is the first tool call the
UI shows; no turn returned a progress note.

| Turn | Tools | First feedback | First text | Total | Cost |
|---|---|---|---|---|---|
| Ask (script) | group, peers, news | 1.8 s | 8.9 s | 8.9 s | $0.021 |
| Ask, effort `low` | group, peers | 1.4 s | 7.9 s | 7.9 s | $0.013 |
| Ask (UI) | group, peers, news | 1.9 s | 9.4 s | 9.4 s | $0.018 |
| Pushback (UI) | group, peers | 1.8 s | 11.3 s | 11.3 s | $0.023 |
| Ask, fixture evidence | group, peers, news | 1.7 s | 8.4 s | 8.4 s | $0.021 |

The 7–9 s silence before the answer is not hidden thinking. In the round after
tool results, the API sends nothing, not even `message_start`, until the whole
answer is generated; then every text delta arrives within about 10 ms, with no
thinking block. Direct probes with the lab's request shape:

- A plain question (no tool result) streams normally: first text at 0.9 s,
  then deltas over 4 s, with or without the progress beta.
- The same answer after one tiny `tool_result` is held: 6.1 s, then all at once.
  Disabling server-side fallbacks, eager tool-input streaming or top-level
  cache control does not change it.
- Haiku 5.5 streams after the same tool result (first text 1.9 s).

So on Sonnet 5.5 the wait scales with answer length (about 100 tokens a
second) and the client cannot stream it. Effort `low` saved 1 s and $0.008 but
skipped the news check, which held the day's key context (a CRWV downgrade and
financing stress); `medium` stays the default. The status line keeps the wait
honest. Shorter answers or another model are the remaining levers; neither is
changed here.

## Research job

`backend/app/ai/research_job.py` runs one autonomous, cited investigation
through the Agent SDK. The interactive copilot stays on the Messages API.
Trigger it by hand only, with `backend/scripts/run_research_job.py "question"
--symbols NBIS,CRWV --evidence fixture|live|replay [--out job.json] [--no-save]`.
It has no scheduler, Radar wake-up or notification yet.

- **Tools.** An allowlist (`research_job.JOB_TOOLS`), so a new copilot tool
  never reaches a job by default.
  - Allowed: the market reads (group comparison, peer moves, symbol news,
    earnings dates, quotes), `get_saved_research` and `get_chart_context`,
    plus the built-in `WebSearch` and `WebFetch`, and nothing else.
  - Not allowed: `propose_plan`, `get_investigation_changes` and the book
    tools. These aren't registered for a job at all.
  - Lab tools run in-process with the same validation, timeout and size
    bound. A
  PreToolUse hook denies any other tool and caps a job at 8 searches, 10
  fetches and 12 lab-tool calls. Other limits: 24 turns, 600 s, and
  `max_budget_usd` from `RESEARCH_BUDGET_USD` (default $0.50). Built-in tools,
  settings, other MCP servers and sessions are off, as for the plan backend.
  Pages are untrusted data, and the job has no tool that could act on an
  injected instruction.
- **Auth (`RESEARCH_AUTH`).**
  - `plan` (default) passes only `CLAUDE_CODE_OAUTH_TOKEN`. It runs on the VPS
    too, by the owner's 2026-10-24 decision (§ Plan backend).
  - `api_key` passes only `ANTHROPIC_API_KEY`.
  - Either way, every other credential variable (API key, auth token, base
    URL, cloud providers) is set empty for Claude Code.
  - Claude Code must report the one credential as its sign-in before a job
    runs. In plan mode that is `oauth_token` with no API key source; a leaked
    key would show up as one and is refused.
- **Output.** A structured assessment (`output_format` JSON schema): summary,
  key findings with citation and evidence indexes, counterpoints, what would
  change the view, citations (URL, publisher, publish time, title) and
  evidence references (tool and `as_of`). The record also has the lab tool
  calls the server actually ran, with provenance, plus web counts, cost (an
  API-price equivalent on the plan) and server-side checks:
  - citations whose URL the job never got from a search result's `url`
    field, a successful fetch (a failed fetch was never read), or the lab news
    tool's structured article `url`. A URL that only appears inside some text,
    such as a headline, summary or snippet, does not count;
  - evidence references to tools it never called;
  - under replay, sources published after the evidence time. A time without
    an offset is read as New York, a bare date as that day's end in New York,
    and an unreadable or "unknown" time counts as after.

  It is research only: no plan, watch, alert or trade instruction. The prompt
  gives the evidence time in both ET and UTC, and the system prompt says to
  convert to UTC before comparing times.
- **Storage.** A finished job is saved as an open saved investigation with
  `source="research_job"` (`app.engine.copilot_investigations.save_research_result`),
  unless `--no-save` is given.
  - The title is the question and the symbol is the first symbol.
  - Findings are mapped to the store's shape. Key findings cite sources by
    number; a citation the server could not confirm, or one published after
    the replay time, is kept but marked in its title.
  - Evidence comes from the lab tool calls the server actually ran (tool,
    `as_of`, kind), not from the model's own references.
  - A failed save leaves `save_error` on the returned JSON, and `--out` still
    writes it.
- **Verified live on 2026-10-24** (plan auth, replay of Fri 2026-10-23 11:12
  ET): 1 search, 2 fetches and 4 lab-tool calls; 55 s, 10 turns, $0.16
  API-equivalent. It returned a cited assessment and labelled a hindsight
  finding itself.
  - It misread one news time: a 14:46Z headline is 10:46 ET, before the
    evidence time, but it called it later.
  - Citations that came through the lab news tool have no article URL, and the
    checks flag them as unseen.
  - A second live job after the store hookup (48 s, $0.19 API-equivalent)
    saved as an open `research_job` investigation with 5 findings, 3
    citations and 4 evidence refs. It stated the evidence time as 11:12 ET
    (15:12Z), and all its server checks passed.

## Research queue

Research jobs can also be queued and run in the background by the API process
(`backend/app/engine/research_queue.py`, table `research_job`). The runner is
off unless the private backend environment sets `RESEARCH_QUEUE_ENABLED=true`.

| Variable | Default | Meaning |
|---|---|---|
| `RESEARCH_QUEUE_ENABLED` | unset (off) | `true` starts the runner in the API process. Jobs can be queued while it is off; they wait. |
| `RESEARCH_AUTH` | `plan` | `plan`: the owner's Claude plan token, on any database (the VPS included). `api_key`: `ANTHROPIC_API_KEY` (API credits). |
| `RESEARCH_BUDGET_USD` | `0.50` | Budget for each job. |
| `RESEARCH_DAILY_BUDGET_USD` | `2` | Total spend for attempts started since midnight UTC (API-equivalent on the plan). It is checked before every attempt. At the cap, queued jobs wait for the next day. |
| `RESEARCH_RADAR_TRIGGER` | unset (off) | `true`: every 5 minutes, each new event in today's Radar session (read only from `RADAR_STORE`) gets one `radar_event` job. |
| `RESEARCH_NOTIFY_ENABLED` | unset (off) | `true`: a job with a material result about an open investigation sends one phone ping (below). |
| `RESEARCH_NOTIFY_DAILY_MAX` | `3` | Phone pings per New York day, all jobs together. |
| `RESEARCH_REASSESS_AFTER_HOURS` | `0` (off) | N: each original open investigation that has been neither updated nor reassessed for N hours, and has no job waiting, gets one `reassess` job, at most one a day. A reassessment's own output is never reassessed. |

- **Owner-only routes** (in no assistant grant):
  - `POST /copilot/research-jobs/reassess` with `{investigation_id, question,
    after_days}` queues the owner's "revisit this question": one reassess job
    for that investigation, due `after_days` (0-30) from now, at most once a
    day per investigation and due date. Its assignment adds the owner's
    question to the usual reassessment. It records `from_investigation` too,
    so `?from_investigation=` lists it with that investigation's jobs. While it waits, it counts as that
    investigation's waiting reassessment, so the automatic reassessment
    (`RESEARCH_REASSESS_AFTER_HOURS`) skips the investigation until it has
    run: up to 30 days for the longest revisit.
  - `POST /copilot/research-jobs` with `{question, symbols}` queues a question
    job. An optional `investigation_id` is kept in the job's input as
    `from_investigation`, so the lab can show the job on the investigation it
    came from; the job does not read it. The same question and symbols from
    the same investigation are queued at most once a day. A failed or
    cancelled one can be asked again: its row keeps its outcome under a
    retired key. Jobs queued by the triggers are never re-queued this way.
  - `GET /copilot/research-jobs` lists jobs with the day's spend;
    `?from_investigation=<id>` keeps one investigation's jobs.
  - `POST /copilot/research-jobs/{id}/cancel` cancels a queued job, or stops a
    running one.
- **In the lab** (`frontend/components/copilot/ResearchDeeper.tsx`): an open
  saved investigation offers "Research deeper" only while `GET
  /copilot/research-jobs` reports `queue_enabled`.
  - It opens a form prefilled with the investigation's symbol and its latest
    question; the owner edits it and queues a linked job.
  - The button is hidden while a job for the investigation is queued or
    running.
  - The job's status, cost and error show under the investigation. The list
    is re-read every 10 s while a job is queued or running, and no longer
    after that.
  - A finished job's row offers "Open result" and
    "Discuss this result". Discuss starts a new conversation on the result's
    symbol, with the result as its opening context. It is not sent.
  - Browser proof: `frontend/e2e/copilot-research.spec.ts`.
- **How a job runs:**
  - One job at a time, through the research job above, with live evidence.
  - Each attempt's budget is capped by what is left of the day. That budget is
    charged when the attempt starts and replaced by the real cost once known.
    An attempt that times out, fails, is cancelled or is cut off by a restart
    or shutdown keeps the charge, so the cap never misses spend. A job refused
    before any model call, or one whose input is missing, costs nothing.
  - Timeouts, SDK failures and missing assessments are retried after 1 and
    then 5 minutes, three attempts in all. Auth, budget and missing-input
    failures fail at once.
  - Every failure is recorded on the job, including a broken input or Radar
    store, which fails the job instead of leaving it running.
  - A job left running by a restart or a shutdown goes back to the queue.
  - A malformed number setting falls back to its default with a warning; it
    never stops the API. Budgets and caps (`RESEARCH_BUDGET_USD`,
    `RESEARCH_DAILY_BUDGET_USD`, `RESEARCH_NOTIFY_DAILY_MAX`) must be finite
    and above zero, so `nan`, `inf`, `0` and negative values fall back too.
- **Results:**
  - A finished job links to its saved investigation (`source="research_job"`).
  - A Radar job is titled `Radar: …`, and a reassessment is saved as a new
    investigation titled `Reassess: …`.
- **Phone pings for material results** (`RESEARCH_NOTIFY_ENABLED`, off by
  default):
  - Every assessment carries `material_change`, false by default, and a
    `material_reason` of at most 140 characters. It is true only when the
    linked conclusion should change or a new catalyst or risk appeared;
    routine confirmation is never material.
  - A finished job sends one ntfy push through `app.engine.ntfy.publish`,
    using the API's existing `alerts.env` (`NTFY_URL`, `NTFY_TOKEN`). The title
    is "Research: SYMBOL – reason", and a tap opens the linked investigation
    in the lab (`/copilot-lab?investigation=…`).
  - It only sends when every check passes:
    - the flag is on, and the result is material with a reason;
    - the job is linked to an investigation that is still open (a
      reassessment's, or the one "Research deeper" ran from);
    - it cites at least one source, and the server checks are clean: no
      unseen citation, no evidence reference to a tool the job never called,
      and no source after the evidence time;
    - there has been no ping yet for that job, none today (ET) for that
      investigation, and fewer than `RESEARCH_NOTIFY_DAILY_MAX` today. A
      failed ping counts toward both limits, since ntfy may still have
      delivered it.
  - Control and bidirectional characters are stripped from the reason, and
    the link is built from the investigation record's own id.
  - The ping is recorded as `sending` before it goes out, so a crash never
    sends it twice.
  - The job records `sent`, `failed` (never retried, and the job stays done)
    or `skipped` with the reason. The lab shows the materiality and that
    status on each finished job.
- **Not included:** other notifications. To try the queue locally, set
  `RESEARCH_QUEUE_ENABLED=true` with a local database (plan auth), queue a
  question with the POST route, and read the result in the lab's saved
  investigations.

### In production (VPS)

The release carries the SDK: `deploy/build.py` builds the `copilot-plan` extra
from its sdist, a 164 KB pure-Python wheel instead of the ~126 MB PyPI wheel
with a second (~270 MB unpacked) Claude Code inside. `deploy/control.py` installs that extra.
Jobs run the release's own `bin/claude`, the version
`deploy/claude-code/package.json` pins, which needs to be 2.1.257 or later
for this SDK. They find it through `TJ_CLAUDE_BIN`, which the API unit sets.

- **Auth.** Both modes work on the VPS; `plan` is the default.
  - **`plan`** uses the token in `/etc/tradejournal/claude-plan.env`, and the
    job passes only that token. The valid `ANTHROPIC_API_KEY` in the same
    service env is set empty for Claude Code, which must report `oauth_token`
    with no API key source. State goes in
    `/var/lib/tradejournal/claude/research-plan`.
  - **`api_key`** uses `ANTHROPIC_API_KEY` from `backend.env`, and the job
    passes only that key. Claude Code must report `authMethod=api_key` and
    `apiKeySource=ANTHROPIC_API_KEY`. State goes in
    `/var/lib/tradejournal/claude/research-api`.
  - Both state directories are kept apart from the nightly plan reviews'.
- **Turning it on, conservatively.** Add `RESEARCH_QUEUE_ENABLED=true`, a
  small `RESEARCH_BUDGET_USD` and `RESEARCH_DAILY_BUDGET_USD`, and leave the
  two trigger settings unset. `RESEARCH_AUTH` can stay unset (plan); set
  `api_key` to bill API credits instead. The budgets are an API-price
  equivalent on the plan. Then
  run `sudo systemctl restart tradejournal-api`. Queue one question with
  `POST /copilot/research-jobs` and watch it with `GET /copilot/research-jobs`.
  Turning the queue off again (unset, then restart) leaves queued jobs
  waiting.
- **CI.** The "Ubuntu package and MCP smokes" job checks the installed release
  without a model call:
  - `bin/claude --version` matches the pin;
  - `claude_agent_sdk` imports from the release venv without a bundled CLI;
  - the API-key preflight passes as the `tradejournal` user with a dummy key;
  - the plan preflight passes on Postgres with a dummy token, while a dummy
    API key is also in the env, which proves the key never reaches Claude
    Code.

## Thesis watch

When new information touches something the owner has a thesis on, the app
tells him once and offers the re-check (`backend/app/engine/thesis_watch.py`,
table `thesis_watch_trigger`). Off unless the private backend environment sets
`THESIS_WATCH_ENABLED=true`; it runs as its own task in the API process, every
15 minutes inside the regular session and once at 08:00 New York on a trading
day, and nothing runs when the flag is off.

- **Watched set:** symbols with an active thesis memory, the open copilot
  investigations' symbols and the open positions (Webull left out), held
  symbols first, then investigations newest first, then theses newest first,
  at most 25.
- **Reads per pass:** one batched news read for the watched set (the Alpaca
  feed through `eligible_headlines`), one batched quote read (the chart feed),
  and earnings from the events cache only. Nothing here is a market read the
  app does not already make.
- **Triggers:** a new eligible headline for the symbol since the last pass
  (deduped by URL, a catalyst headline first); a move of
  `THESIS_WATCH_MOVE_PCT` (default 4) or more since the open investigation's
  latest evidence as-of (that day's cached minute bars; the prior close when
  the day is not cached; no move at all while the evidence is from today, since
  the owner just read that price), or since the prior close for a thesis or
  position with no investigation; earnings inside two trading days.
- **One ping:** `New on NBIS since your thesis`, the headline, the move or the
  earnings date in the body, at most one per symbol per day and
  `THESIS_WATCH_DAILY_CAP` (default 4) a day; the rest are recorded `skipped`
  with the reason. Each trigger is written once by its dedupe key, so a
  restart never fires it twice; a skipped one is keyed to its day, so a cap or
  a missing ntfy does not swallow a signal that is still true tomorrow.
  Delivery is an outbox on the row (`sending`, then `sent`, `failed` or
  `skipped`). A failed push is never retried: it may still have landed.
  Headline text is third-party data, cleaned of control characters; it is
  plain text in the ping and quoted in the prepared question, never an
  instruction anywhere.
- **Tap:** opens the investigation with the What-changed question prepared
  and unsent (`/copilot-lab?investigation=<id>&context=New since my thesis:
  "…". What changed? Use get_investigation_changes for investigation <id> and
  say whether it still holds.`, at most 300 characters), or, for a thesis with
  no investigation, `/copilot-lab?symbol=X&context=New since my thesis: "…".
  Does it still hold?`. The investigation is the owner's own latest open one
  for the symbol; a research job's output stands in only when he has none, and
  is never reassessed itself.
- **Research queue:** with `RESEARCH_QUEUE_ENABLED=true`, a fired trigger
  with an investigation also queues one `reassess` job through the queue
  (`reassess:<id>:<day>`, the same key as its stale-investigation trigger, so
  one a day; the queue's budget applies when it runs). The queue's own result
  ping is the only other notification.
- **Lab home:** the desk's thread list shows each investigation's newest
  trigger today under New since you looked (kind and text), opening the
  investigation.

Tests: `backend/tests/test_thesis_watch.py` (seeded journal; stubbed news,
quotes, bars and earnings).

## Before a live API test

1. The owner approves the spend. A billing refusal is reported as "API credits
   are not available on this account yet."
2. Set `ANTHROPIC_API_KEY`, `COPILOT_BACKEND=anthropic` and `COPILOT_ENABLED=true`
   on a local backend only, and unset `ANTHROPIC_BASE_URL`. The client pins
   `https://api.anthropic.com` regardless.
3. Keep synthetic runs (`fixture` evidence) and live-evidence runs separate
   when comparing against Jo. Record latency and cost from the metrics line.
