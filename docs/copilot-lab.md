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
  - **Charts:** **Ask Copilot** beside the chart symbol opens the existing side dock, or its bottom sheet on a phone.
    - It opens on the chart's symbol, resuming that symbol's latest open
      investigation, or starting one with `Context: Charts · <symbol>
      <interval> chart` in the message box.
    - When the chart's symbol changes, an empty panel follows. A
      conversation is never retargeted: the panel offers "Switch to <symbol>"
      or "Keep <symbol>" (Switch waits for a turn in progress).
    - An unsent question stays with its investigation, or its ticker until the first answer is saved. The browser tab keeps it when switching threads or dock panels. If the chart changes symbols while a draft is open, **Switch** and **Keep** choose which conversation to show.
    - **Continue in Desk** opens the same saved conversation or the fresh symbol with its unsent text and attached screenshot IDs. A ticker heading on the Desk links back to that symbol in Charts. Navigation sends no turn.
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
      the plan card's lesson line, and its `setup` the plan card's setup
      record; the dock shows neither. Each
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
  `components/copilot/ThreadRail.tsx`). **Now** (filled in while open), pinned
  while the list scrolls on a wide screen, then one row per ticker, with one line for the day above it: how many
  rows need a decision, and the plan streak while one is running. The server still sends its rows
  in `DESK_GROUPS` order (Act now, Near a trigger, Waiting for you, New since
  you looked, Watching); the list regroups them by symbol in the browser.
  - **Now**: today's Main chat (below, § The desk). Pressing it opens it and sends nothing; the
    open conversation stays saved. Radar hits are in the cockpit's Feed tab and Review my
    week in ⌘K, not rows in the list. The row shows the Radar count ("18 Radar", an amber dot while one
    is unseen in this browser); alert and Radar ratings are optional and never counted here. Open conversations about no ticker (an older
    turn, a week review) are listed under it, title and date: today's, the open one and the latest automatic week
    review, the rest under **Earlier · N**. **What matters right now?** (one turn, the fixed `lib/copilot.ts`
    `WHAT_MATTERS_PROMPT`) sits at the foot of the centre's Feed tab beside Review my week, and in ⌘K.
  - **Tickers**: one row per symbol the owner has something on: an open
    position, a plan (armed, near a trigger, or exited with its exit review
    waiting), a plan or alert card waiting on Confirm, a thesis-watch trigger
    today, an open conversation, or a conversation closed since Monday (New
    York). A row shows the symbol, the position's unrealized P&L
    (an option's from its own mark; two or more open positions on one ticker show their sum) or the exit day, and the status line of
    its most urgent row (Act now's reasons, a plan's nearest level, "N to
    confirm", the close question) on one line, cut with the full text on hover; "Want a plan for this?" is muted, not amber.
    Its state (Held, Plan armed, Exited, Watching or Closed) is named to a screen reader, not drawn as a chip: the status
    line says it, and the plan's meter is the plan ladder in its thread. An amber dot means it needs the owner: an
    Act now position, a card waiting on Confirm, a fill to link, or a close
    or exit question not yet answered or skipped today; something new since the last look is a grey dot. The order is
    **Needs you** (the only heading), then held and armed, then the others (exited,
    watching, closed), the biggest loss first within each state, then the newest; six of the others show and
    the rest wait behind "+N more".
  - **Subthreads**: pressing a ticker opens its newest saved conversation in
    place (from the latest 50 in `GET /copilot/investigations`, open and
    closed) or, with none, follows its row's link (a position with a fill to
    link, an unplanned position, a trade) and shows its subthreads. A ticker
    with more than one conversation carries a count and arrow at the row's
    end, which show or hide them without changing the open conversation; any
    number of tickers can stay open. Beneath it, indented, title and date, its
    three newest open conversations and the open one, the plan's tagged
    **Plan** and the exit review's **Exit review** (a thread planned from a
    Radar hit or setup card is tagged **From Radar** instead of Plan: the list's
    `origin: "radar"` from `GET /copilot/investigations`, read from the plan
    capture's `radar_event` origin or the setup's own thread, else a title
    starting "Radar setup:"), then the other open ones
    under **Earlier · N** and the closed ones under **Closed · N**. A ticker
    with one conversation shows no children. Thesis news is remembered as seen in
    this browser (`localStorage`) once its ticker is opened.

  A **breadcrumb** tops any conversation but Main chat: "Now › <conversation>" for one about no ticker (Now goes
  back to the front door), or "NBIS › Neocloud group bounce · Oct 29" (the date the conversation was last saved).
  On a phone the tabs are **Now**, **Threads**, the open thread's (its ticker, or Main chat for an earlier day;
  shown only while it is not Now) and **Context**.

  **All | Plans** under the day line switches the list to the **Plans**
  view and back; the choice is remembered in this browser (`localStorage`),
  and on a phone it sits inside the Threads tab. The Plans view lists every plan
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

  **Plan a
  trade** sits under the tickers, then the key hint. It refreshes every minute while visible and
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
  only while the lab is on. The collapsed summary shows plan coverage, fired give-backs, hit invalidations, time stops and recent alert counts. Refresh and pricing warnings stay visible. Expand **View positions** for one row per open position (Webull left out): the
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
  (Dashboard is the second phone tab). One column, top to bottom, each
  section collapsed to its count when empty:
  - **Act now**: open positions within 1% of an armed invalidation (or past a
    hit one), expiring today, with the give-back alert fired, or with a time
    stop due within 30 minutes.
  - **Plans near a trigger**: armed plans not yet in a position within 1% of
    their entry or invalidation.
  - **New since you looked**: Radar events since the last Radar visit,
    thesis-watch triggers fired today and today's pre-market prep.
  - **Held back**: pings the notification policy held today (merged, quiet
    window or over a category budget), with their text.
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
  call twenty-five read-only tools (`backend/app/ai/copilot_tools.py`): Radar group
  comparison, peer moves, symbol news, earnings dates (with the next dividend
  and recent splits), quotes (last, day change, volume), the market regime and
  Radar today, the symbol profile and the proof read-out, macro series and
  drawdown base rates, S&P 500 breadth and options positioning (all below), saved research,
  investigation changes (below), the chart and book tools below (including the
  trade review and the week review), option candidates (below), one moment on
  the chart (Explain this candle, below), and the owner
  context pack for another symbol (Owner context, below). It can
  also call `propose_plan`, which writes nothing (see Confirm a plan). Each tool
  reads an existing service in-process and returns a compact result with its
  source and as-of time. No market math is reimplemented.
- **Market regime and Radar today** (`backend/app/ai/copilot_regime.py`, since
  2026-11-02; the review of 2026-10-31 found the copilot had no way to say
  whether a move was the stock or the market):
  - `get_market_regime(symbol?)` is the backdrop: SPY, QQQ, IWM and RSP (day %,
    since open, opening gap, last 15 minutes) and, with a symbol, its sector
    ETF with the symbol's distance from it and from SPY, all from the latest
    recorded Radar pass (`app/engine/radar_regime.py`, the arithmetic Movers
    now uses, benchmark rows kept); VIX and the 10-year yield through the chart
    feed's index quotes (`chart_indices`, one bounded GET, 15 s cache); the
    macro calendar's FOMC, CPI and jobs releases for today and the next trading
    day; and the symbol's next earnings from the fundamentals cache only (a cold
    symbol says so and refreshes in the background; `get_symbol_events` waits
    for it). On a day Radar has not recorded, the newest recorded session stands
    in and the result says `prior_session`. Each block degrades alone: Radar
    off, the feed cooling down or an uncovered calendar day each read
    `unavailable` with a reason, never a guess.
  - `get_radar_today(group?, limit 1-12)` is the session's Radar feed as the
    screen shows it (`app/engine/radar_today.py`): saved events newest first
    with kind, symbols, benchmark, group, first-seen time, summary, measures,
    the latest revision, the latest news check's first three headlines (no
    links) and the owner's rating; and the latest pass's movers (SPY and QQQ
    day %, five leaders and laggards against SPY, six curated groups). `group`
    keeps one curated group's events or one symbol's. Longer feeds drop the
    oldest events, never cut JSON.
  - Both are market data only, so research jobs and the shadow book get them
    (`research_job.JOB_TOOLS`); the system prompt tells the model to read the
    regime beside the group comparison for "why is X moving" and to cite a
    Radar event by its summary and first-seen time.
  - In replay, every recorded read is cut at the frozen moment (events first
    seen, revisions recorded, news checks made and passes started after it
    never appear; ratings carry no time, so a cut never shows them) and VIX and
    the 10-year read `unavailable`: the snapshot has no index quotes. The
    fixture serves the NBIS scenario's backdrop and three simulated events.
    Tests: `backend/tests/test_radar_regime.py`, `test_radar_today.py`,
    `test_copilot_regime.py`.
- **Symbol profile and proof** (`backend/app/ai/copilot_profile.py`, since
  2026-11-02; the review of 2026-10-31 found the copilot could not answer a
  catalyst, valuation or "are the alerts helping" question from evidence):
  - `get_symbol_profile(symbol)` composes what the Symbol page's tabs already
    cache, each block read on its own: company and sector with a 240-character
    description, valuation (market cap, enterprise value, shares, P/E, price
    to sales and book, EV/EBITDA, 60-month beta, 30-day volume) and 13F
    ownership from `symbol_events.overview`; next earnings, last report, next
    dividend and recent splits from `symbol_events.events`; FINRA short
    interest (shares, % of shares outstanding, days to cover, change from the
    previous settlement, settlement date and its lag note), the short-volume
    share and the easy-to-borrow flag from `short_feed.view`; analyst targets,
    ratings, next-quarter estimates, the last three actions and recent report
    results from `symbol_analysts.view` (unofficial). Every block carries its
    source and fetch time, a cold or failed block reads `unavailable` with the
    rest standing, and the prompt tells the model to name the source and age
    of any figure it quotes. Market data only, so research jobs get it.
  - `get_proof(scope week|symbol, symbol?)` is the product's own proof as
    counts and verdicts: the exit-habit scorecard since the position alerts
    went live (`exit_habits.build`: verdict and reason, each habit's recent
    and baseline rate, alert responses and feedback coverage), the plan proof
    (`plan_proof.build`: verdict, caveat, planned and unplanned groups), the
    outcomes by kind (`outcomes.week` for this week, `outcomes.build` for one
    symbol) and the 30-day alert scorecard by the owner's decision
    (`alert_scorecard.scorecard`). No alert, trade or row ids leave; each proof
    fails alone. It is book context (`BOOK_CONTEXT_TOOLS`), never offered to
    research jobs, and the prompt says to quote its verdicts as they stand,
    "not enough data" included, and never to turn a count into a judgement of
    the owner. The Radar proof is not in it: `radar_proof.build` reads every
    pass of every event session and has no as-of cut, and the Proof page's
    Radar tile shows its verdict.
  - In replay both say `unavailable`: fundamentals are as they are now, and
    the proof is hindsight by construction. The fixture serves a simulated
    NBIS profile and proof card. Tests: `backend/tests/test_copilot_profile.py`.
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
  - There is no memories tool since 2026-11-10: the owner context block
    carries the approved memories (§ Jobs). `get_positions`, `get_trades` and
    `get_owner_context` stay for what reaches beyond the block.
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
- A round's tool calls run side by side, each in its own worker thread with
  its own timeout and error handling, and their results go back in the order
  the model asked for them, followed by the answer-shape reminder; a failed or
  timed-out read keeps its place as an error block. Since 2026-11-08 the chart
  feed no longer queues them: its lock covers only its cache, budget and
  backoffs, a request already in flight is joined rather than sent twice, and
  different Tradier reads (this round's, the alert monitors', the Charts
  tab's) go out together, at most four at once so the alert monitors' quote
  reads keep room in the shared connection pool (`backend/app/engine/chart_feed.py`). Before, one
  lock was held across every Tradier call, so three 300 ms reads in one round
  took 936 ms; now 310 ms (§ Where the wait goes).
- Before the first round, the owner context and the carried evidence are read
  side by side, and a live turn with a selected symbol starts that symbol's
  quote read beside them (`copilot.prefetch`); when the owner's words name a
  price (`$142`, `142.50`, a whole number of two to five digits that is not a
  time, date or percent) it starts the symbol's 5-minute chart context too.
  These are the reads the first tool round nearly always makes. They fill the
  chart feed's own short cache (quotes and today's minutes 15 s, the daily
  tail 60 s), so the model's call for them is served from it with the feed's
  as-of, and a call after it expires reads again: nothing new is cached and
  nothing is kept across turns. The as-of the model sees is the prefetch's,
  at most the cache's 15 s before its own call. The turn never waits for a
  prefetch and drops its result. A prefetch that fails puts that read in the
  feed's usual 15 s backoff, as any failed chart read does, so a model call
  inside it reports the source unavailable (or the older data, marked) rather
  than trying again; a model call made while the prefetch is still reading
  waits for it instead of sending a second request. Fixture
  and replay evidence are never prefetched. What the model is told and asked
  is unchanged.
- The browser sends text-only history: at most 24 messages, 4,000 characters
  each, 40,000 in total. Tool results are never accepted from the browser.
  Evidence is re-read when the model needs it.
- The answer streams as `text` events. While nothing else is visible, a quiet
  status line shows the model's progress notes (`progress` events, from
  `thinking: {type: "adaptive", display: "updates"}` with the
  `thinking-display-updates-2026-08-18` beta) or what the turn is doing
  ("Reading evidence…", "Weighing the evidence…"). Under it, each completed
  read adds one small fact line as it lands, in arrival order ("NBIS +0.84%
  vs SPY +0.09%, 4 of 6 peers up (15m, 11:12)", "3 headlines since 08:10,
  latest 10:40", "Web: 3 results"). The server builds it from the result
  itself, never the model (`backend/app/ai/copilot_tool_summary.py`, the
  completed `tool` event's `fact`): numbers at the result's own precision,
  times New York, at most 90 characters, headlines counted and never quoted,
  and none for a read with nothing to summarise or a shape it cannot read
  (plans, the book and the owner context get none). Both disappear when the
  answer's first text arrives; the Sources line still lists every read.
  Telegram, the eval, the companion and the research job ignore the field.
- Prompts and answers are never logged; they are stored only as a saved
  investigation. One metrics line per turn is
  logged: model, first feedback (first progress note, tool call or answer
  text), first text, longest wait between visible events, total latency, tool
  names, tokens and estimated cost. The UI shows the same metrics inside each
  answer's folded Sources line.

## The desk

Open Desk to land on the **cockpit** (since 2026-11-10, stage 1 of the approved cockpit; it replaced the stacked Now
screen of #733): one screen that says in a few seconds what is going on and puts the best information one tap away
(`frontend/components/copilot/CopilotLab.tsx` lays it out, the pieces are in `Cockpit.tsx`, the look in
`CopilotLab.module.css`). From reads the desk already makes (`GET /copilot/desk/session`, `GET /copilot/desk/threads`)
plus one small one for the book's sparklines (`GET /copilot/desk/sparks`):

- **Top bar.** Desk, the market phase with the New York clock of the session read ("Live · 11:48 ET", "Pre-market ·
  8:52 ET", "Closed 16:00"), SPY / QQQ / VIX's change, **Realized today** (the trades closed today, New York's day,
  Webull left out: the session read's `realized_today`) and **Open** (every open position's unrealized P&L now,
  followed or not). Then **Now** (back to today's Main chat; dropped on a phone while already there), **Threads** (the
  thread list's drawer; no count on the button, since the strip counts what needs him), Jump to… (⌘K) and Plan a trade (the same words as ⌘K).
  Account chips come with the Robinhood stage; nothing fake stands in.
- **Needs you** (`NeedsStrip`). One amber card for the single most urgent item, with its own answers, **Seen** (out of
  the strip for today, in this browser: `localStorage` `desk.seen.v1`; an item that changes, a new status line, a day
  closer to expiry or another fill, asks again) and **+N more** opening the rest. The order is
  `lib/desk.ts` `deskNeeds`, followed tickers only: (1) a position alert asking for a decision (Act now; **Decide**
  opens its thread on the decision bar, **Ask why** sends "Why is NBIS moving today?" in today's conversation); (2) a plan at or near its trigger (the
  thread list's Near a trigger; **Open the plan**, Ask why) or a card to confirm (**Open the card**); (3) an option
  expiring within three calendar days with no confirmed invalidation or time stop (an adopted draft counts as none;
  **Plan it**); (4) before the close, the fills waiting to link
  (**Link it**); (5) after the close, the close-of-day questions and fills (**Close the day**). Nothing in the strip is
  a rating ask. A position's P&L and distance to its stop are the book row's, so the strip's line names only what
  fired. Amber on the desk means this strip and nothing else: tabs, tags, buttons and verdicts elsewhere are neutral.
  When nothing waits, the strip is absent.
- **Left: the book** (`Book`). One dense row per open position the owner follows: ticker, contract, unrealized P&L in
  dollars and percent, a sparkline of the underlying today, the bar placing it between the plan's invalidation (left)
  and entry (the tick) (nothing without both: the tag says No plan), the distance to the stop ("4.3% to stop"), days to
  expiry and one tag (this year's expiry drops the year: "11/14 105C"):
  **Near stop** (Act now names the invalidation hit or near), **Giving back** (the give-back alert fired), **No plan**
  (no invalidation and no time stop) or **On plan**. These come from each position row's `book`
  (`copilot_desk._book`). Selecting a row shows it in the centre at once and, where the copilot sits beside it, opens
  its conversation (its own, else the ticker's newest open one, else its link; a position whose link leaves the desk
  opens the symbol's desk view). Each row's eye sets its ticker to **Not following**; those sit behind "N not followed
  ▾" at the bottom, each with Show again. Under the book, the time of day's block (below), then one quiet facts line:
  **At risk now** (see Exposure) and the practice goal.
- **Live from Robinhood** ([robinhood-read-feed.md](robinhood-read-feed.md); off unless `ROBINHOOD_READ_ENABLED=true`
  and a usable sign-in file). `GET /copilot/desk/threads` carries `robinhood`: its `state` (`off`, `signed_out`,
  `expired`, `loading`, `unavailable`, `stale` or `ok`), `as_of`, and each shown account's label, masked number, total
  value, cash and buying power. While it is `ok` (and `joined`): the top bar shows one chip per account (label, `••last
  four`, value); each book row carries its quantity, and its account tag when the book spans more than one account
  (one account is the chip's, not a word on every row); a journal position matched by contract (same
  account first) takes Robinhood's P&L, quantity and mark (`book.live` `matched`) and keeps its plan, meter, state and
  thread; a position only Robinhood shows (the fill email has not arrived) is a `robinhood:` row tagged **New · not in
  the journal yet** with no plan; a journal position Robinhood does not show stays as the journal has it, tagged **Not
  on Robinhood** (only when every account's positions read). Options come first; stocks with no plan wait behind
  "N stock positions ▾". A quiet line beside the heading says **live from Robinhood · as of HH:MM** (tap: read again,
  `POST /copilot/desk/robinhood/refresh`, no input) or, signed out, expired or stale, says so; then the book is exactly
  the journal's. Off, nothing changes and no line shows. Not followed tickers stay hidden. Display only: nothing is
  written to the journal and nothing from Robinhood reaches the copilot.
- **Centre.** A tab strip, **Chart** first, **Feed**, **Check a call** (§ Check a call) and **Ticket** (see
  [Ticket](#ticket); no tab shows before it works). Chart: the selected ticker (the book's pick, else the copilot's, else the first followed
  position; none is QQQ, the market) as an interactive chart with the plan's entry and invalidation lines, the owner's
  fills, today's pings and Radar hits and a time stop still ahead, on 2m, 15m or 1D, with **Open in Charts →**; then, for a held
  position, two tiles the book row does not carry: vs SPY today (the stock's change today less SPY's, from the sparks
  read) and Held (its P&L, distance to the stop and expiry are the row's, beside it); and **Timeline ▾** folded under it. The sparks read takes at most 12 symbols (the centre's first) and
  answers a repeat within 30 seconds from memory, so several open desks cost one chart-feed read a minute. The chart is
  its own small component on the library `/charts` uses (lightweight-charts), not the workspace's `PriceChart`: that
  chart is bound to the workspace's live feed, crosshair links, command bus and clock stores, so the desk draws from
  its own read instead of embedding it.
- **Feed** (`components/copilot/DeskFeed.tsx`, `GET /copilot/desk/feed`, `app/engine/desk_feed.py`): one stream of what
  the app already knows today, so there is a reason to open the desk that is not a ping. Its tab carries a grey count of
  the items new since the Feed was last opened in this browser. Each item is one row: its source (**Alert**, **Plan**,
  **Radar**, **Radar setup**, **News**, **Calendar**, **Copilot note**), its time, its symbol and one or two plain
  sentences. Sources: the phone pings judged today, sent or held (position alerts; plan pings for an entry or
  invalidation reached and a time stop; the position companion's updates as Copilot notes), plan time stops still ahead
  and a plan level that fired without a ping, today's Radar events and setup cards (a card shows its level, contract
  and his record as the desk's Radar card does, and stands for its event), headlines since the previous close naming a
  symbol he holds or has a live plan on (catalysts first, two per symbol) and up to three market-wide ones (Fed, CPI,
  yields...), this week's earnings for those symbols (the earnings cache only) and FOMC, CPI and jobs reports today
  through Sunday, and the morning brief's saved lines as Copilot notes. Nothing calls a model. Order: items on his book,
  plans and day first, then the rest, each newest first, then **Coming up**, soonest first; at most 40 rows (8 ahead),
  with the total. A ticker set to not followed is left out of every source, including a headline, Radar event or
  brief line that names it among others (if that setting cannot be read, only the macro calendar shows). Each source fails on its own and is left out quietly. Filters: **Mine**
  (the default: his book, plans and day), **Market**, **Mine + Market**; tapping a symbol shows only its story, with
  **All items** back. Actions: **Ask the copilot** puts the item, quoted, in the box unsent, in the item's plan thread,
  else the symbol's open conversation, else the symbol's desk view (an item with no symbol: today's conversation; a
  phone opens the sheet); **Open in Charts**; **Read at <publisher> ↗** for a headline (a new tab); **Open** for a
  Radar event or the brief; and **Plan it** only on a Radar setup card (it opens the desk's Radar card, whose Plan it
  is the setup's own) and on his own position or plan items, alerts and plan events (its plan thread, else the plan
  form); never on news, calendar, Radar events or a Copilot note. Headline text is
  third-party data shown with its publisher and time, never read as an instruction and never given Plan it. What
  matters right now? and Review my week are in ⌘K and the thread list, not repeated under the feed. The route reads the journal for his symbols (no
  quote read) and makes at most two news-provider reads (one batched for his symbols, one for the broad tape), each
  cached 120 seconds, plus the earnings cache, which refreshes stale symbols in the background; the screen reads it
  once a minute. A fourth filter, **Chatter** (r/wallstreetbets buzz and NYT headlines, [§ Chatter](#chatter)), appears
  only while a chatter source is on and has rows; chatter rows never show under the other three filters or a symbol's
  story and never count toward the tab's new number; what a chatter source did not deliver is said only under it.
- **Right: the copilot**, always open from 1180 px: today's Main chat or the open thread (its header, decision bar,
  close pass or checklist on top), scoped to its ticker, with **Why is it moving?**, **What changed since I looked?**
  and **What does my plan say?** first above the box (one turn each in that conversation; then at most two of the
  thread's own next steps). Answers keep the verdict-first format: the verdict set off with a rule, the Thesis ·
  Timing · Contract read as three tiles, the body, **Against** and **Changes if** labelled; what is sent to or stored
  from the model is unchanged.

**Time of day.** The book's lower block follows the New York clock, one block each: before 9:30 on a weekday it is the
**Morning brief** (`MorningBrief.tsx`, cut to three lines with **Read the whole brief** a tap away; nothing before it
is written); after 16:00 it is the **day report** (below); otherwise **Since you looked**: what changed since the
owner last left the desk in this browser (`localStorage` `desk.looked.v2`, by position, saved when the page is hidden
or left), four lines at most: the biggest open-P&L changes since then ("NBIS 11/14/26 105C −$235": the change, since
the row has the P&L now; a move under $25 and 10% left out), positions opened or closed since, and the fills, pings
and Radar events since (a ticker not followed counts in none). **Arm today's plans** and **Close the day** are ⌘K
commands, not buttons in the block; the strip carries Close the day while anything is left to review. No mode shows
more than the session mode does.

**Day report** (`DayReport.tsx`), after 16:00 New York on a weekday: one compact card of up to three single lines, each
opening its rows on tap, in this order. The app scores everything itself; nothing asks him to rate a ping, a Radar hit
or a call. Facts and counts only (no line tells him to buy, sell or hold, and none says money was missed); a ticker
marked **Not following** is left out of every line; realized P&L is the top bar's and an open position without a plan
is the book's (its No plan tag, and the strip when it expires soon), so the card repeats neither; a line with nothing in
it is absent, and a day with nothing at all says so in one sentence ("Nothing to report today: …").

1. **Today**: how many entries were opened today and how many of them had a plan saved before the fill
   (`GET /copilot/desk/day-report`, `entries`, from the plan streak's per-entry state: planned, late, no plan). On tap,
   each entry with its time and which of those it was.
2. **How the pings did**, today's only (`GET /copilot/desk/pings?day_only=true`; without the parameter it still reads
   since the previous trading session): for each position alert, what its contracts fetched against selling at the alert
   (sold or expired for how much, still open, or not measured and why); for each alerted Radar stock hit or setup card,
   the stock's move against SPY the way Radar flagged it an hour on and at the close ("not measured" with why, as while
   its session is open) and a setup card's paper result. On tap, each ping, and **Last 30 days** unfolds the alert and
   Radar scorecards (the line, and so that button, shows only on a day with a ping). Example line: "4 alerts · selling at the alert would have been better on 2, worse on 1 · 2 Radar
   hits · 1 kept going".
3. **Calls checked, last 30 days, since you checked**: the running total leads ("14 · 5 up, 7 down, 2 not measured"),
   then today's. On tap, each call checked today with its verdict, whether he planned it, passed it or did neither, and
   the move since the moment he checked (below). A passed call is reported the same flat way as a planned one.

**Checked-call scoring** (`backend/app/engine/day_report.py`, `GET /copilot/desk/day-report`, `checks`). A call is scored from
the underlying's price **when he checked** (`call_check.underlying_price`), never the price in the Discord post, to the
underlying's regular-session close that New York day, and when the call named a contract and a quote of it was stored at
the check, from that quote's mid to the contract's mid at the close. **Up**, **down** or **flat** is the contract's move when
both its prices are known, otherwise the stock's (reversed for a put); a row prints the stock's and the contract's move
as numbers. **Not measured** (with why) when a price is missing: no ticker read, no price stored at the check, a check
from the fake backend, a check made after the close, or no closing price. The session's end is the market calendar's close (13:00 on an
early-close day), else 16:00, and a row says "reads up", "down" or "flat" so a put's reversal is never silent. Nothing is ever fetched for the card. The closing
price is the last regular-session minute of the completed session in the chart cache on disk
(`ping_images.stored_bars`) or, for today after 16:00, of the chart feed's cached minutes if they were read after the
close (`ChartFeed.peek_minutes`); the contract's close is the options feed's cached chain for that expiry, if it was read
after the close (`OptionsFeed.cached_contract`, today's chains only). A day's measured score is kept in memory per
check once final, so a past day is read from disk once; a score that is not measured is asked again each time. So a
call from an earlier day is measured only from the stock's stored session (a contract's close is not stored anywhere),
and a symbol whose session was never cached reads "not measured": more rows say so until the chart cache has the
symbols he checks. The 30-day total counts every check in the window, today's included. Radar's own quotes are not used
for a closing price.

**Phone (375 px).** The same pieces stacked: the strip, the book, then the centre. The copilot is a full-screen sheet
opened by **Ask the copilot** (about the picked position when the copilot is on another ticker) and by any Ask action;
**Desk** closes it. A deep link or a saved thread opens on the sheet; the bare address opens on the cockpit. One tab
bar only: the app's. From 768 to 1179 px the book and the centre sit side by side and the copilot is a sheet on the
right. The thread list is a drawer at every width (over the whole screen on a phone).

**Not following.** A ticker the owner does not follow (an old position no longer watched)
is hidden in one tap from its book row (the eye) or its thread header (**Not following**), and back with **Show again**
in the same places. It is saved as a `follow` day-journal entry ("Not following" or "Following"; the newest wins, on
every device; `day_journal.not_following`), separate from the horizon, so a long hold stays a long hold for Review my
week. A hidden ticker's rows carry `hidden` in `GET /copilot/desk/threads`: it leaves the book and the thread
list's groups for one collapsed "N not followed ▾" line at the bottom of each, every row with Show again; it is never
in the strip, "needs you" or the Threads count; it asks no close-of-day question and is not in Close
the day or the evening review. Its thread still opens normally. The setting belongs to the ticker, not one position:
a new position in a hidden ticker starts hidden too, until Show again. It leaves no mark on the market chart and is not
counted in Since you looked. Phone alerts, the position companion, the copilot's
context, the top bar's Open and "At risk now" (the money actually at risk) still include it. The top bar's **Now**
comes back to today's Main chat; `?view=briefing` (the old Briefing address) and the evening review's `?close=1` land on
the cockpit too.

Main chat is the same saved conversation on desktop and phone. Unsent words belong to their browser tab. Returning to a saved link keeps its original
conversation, including after midnight. The heading names the day ("Main chat · Wed, Nov 4"; a busy day's next
part adds "(continued)"). The Rate yesterday card that used to open Main chat was removed on 2026-11-10 (the owner
did not rate from memory at the end of the day; the day report's How the pings did shows what followed instead). Its read,
`GET /copilot/desk/to-rate`, still answers but nothing on the desk calls it.
The morning brief card's **Ask about it →** puts the brief in today's Main chat's message box as context, unsent, so
questions about it stay in the day's conversation. **Previous days** (beside the Main chat heading) opens earlier days that have at least one exchange; a day the Desk was
only opened on is not listed. A busy day's full
segment stays in history when opening Main starts its next part. Opening, switching or browsing history
uses no model turn or automatic research job. Concurrent answers append separately, each beside its own question. A proposed trade plan opens in its own ticker thread for review and confirmation so it has a distinct place in Plans and its alerts link back to it. A blank conversation of its own is **New** (`?view=new`). In Main chat a proposed plan's
button also gives its levels in one line (side, entry, invalidation, time stop). Existing symbol, plan, chart and evening-review links still open their own workflows.


The cockpit's panes in detail:

- **Threads** (the drawer): the thread list (above), opened from the top bar or with `[`, closed with ✕ or Escape. A
  row or a pinned question opens or asks in the copilot through the panel's `desk` hand-off; beside the copilot the
  drawer stays open, over a phone's whole screen it gives way. **This week** sits folded at its foot (`ThisWeek.tsx`,
  below).
- **Conversation** (the copilot column): the page variant of `CopilotPanel.tsx` in `desk` mode. Its
  message box stays in reach while the conversation scrolls. One quiet line
  names the model (in its picker when the server offers several) and only what is unusual: the simulated model,
  simulated or replay data, the day's API spend once past half the budget, a missing key (read-only live data,
  the usual case, needs no label). It ends with **New** and a **…** menu (the
  thread's one-line conclusion or lesson, Save, Close thread / Reopen, and
  Mark plan done on a plan's thread; see Plans end below) at its end. There is no Recent row (the thread list does that) and no Symbol box:
  the message box carries a scope chip, "About NBIS ×", where × asks across
  everything and "add a symbol" scopes it again. Above the box, the three
  asks (above), then at most two of the thread's next steps: **Size it** (a plan card
  in the thread; fills the box unsent, the owner adds the dollars at risk), **More** (the full reasoning; one turn),
  **Look at my chart** (sends the centre's picture of today with the plan's lines; one turn) and **Close with a
  lesson** (opens the menu on the conclusion; the … menu always has it). Below
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
  one line ("3.1% above invalidation", invalidation · bar · 2R, the R multiple,
  with a time stop on its own line when the plan has one), `dimmed` for a plan
  not armed yet. The thread opens on that one line so the conversation stays in
  view; **Full plan** unfolds it and **Fold plan** folds it, remembered in this
  browser.
  Both read `GET /copilot/plans` (the plan is the row for the open
  investigation) and `GET /copilot/plans/positions` (the open position in its
  symbol, matched by the plan's invalidation; none for an armed plan not yet
  entered), once a minute; a thread with no plan shows only the header.
- **Centre** (above): the chart (`components/copilot/DeskChart.tsx`) and its folded timeline
  (`components/copilot/Inspector.tsx`), reads in
  `backend/app/engine/desk_context.py`. A ticker with no saved conversation (a position or plan from the book or the
  thread list, a `?symbol=` link, a Radar hit) reads them by the symbol at once, as `symbol:<SYMBOL>` on the same
  routes: its plan's lines when it has one (in a position first, else armed), else the fills of its open trade; a
  position whose plan has a conversation, or the open conversation's own ticker, reads by that conversation. The
  timeline reads only when unfolded, and again when something is confirmed in the conversation; nothing here arms or
  sends.
  - **Chart** (`GET /copilot/desk/{id}/chart?timeframe=`, `desk_context.chart`): the symbol's candles as data, drawn
    in the browser with lightweight-charts. Timeframes **2m** (the default: today's minutes from 04:00 to now, from the
    same cached chart-feed read as a ping picture, as 2-minute candles on the even minute; pre-market and after-hours
    candles are shaded), **15m** (regular-session 15-minute bars of today and the two completed sessions before it,
    those from the chart history: disk, or fetched once and stored) and **1D** (the last 120 days of the chart feed's
    daily bars). The buttons keep their choice for the tab's session (`desk.chart.timeframe.v1`), across positions
    and tab switches. On every timeframe: the plan's **entry** and **invalidation** as labelled dashed lines (named in
    the row above the chart too; a line more than 10% from the last price does not stretch the price scale and says
    "(off the chart)"; "no plan lines saved" without a plan); the owner's **fills** in the symbol since the first
    candle shown (amber arrows, up for a buy and down for a sell; at the fill's price for shares, at the underlying's
    recorded price for an option, else on the candle; a mark with no candle of its own, such as an extended-hours
    fill on the 15m candles, sits on the nearest one; Webull left out; at most 40); today's **phone pings** sent on
    the symbol (violet circles, the session strip's ping reader) and **Radar hits** (blue squares, the Radar store
    read-only, none when it is off); and on 2m and 15m a **time stop** still ahead as a dashed vertical line at its
    time past the last candle, labelled, with room kept for it on the right. Hovering a mark (within 10 px, so a full
    day of 2m candles still answers) shows what it was and its New York time; the readout row shows the candle under
    the crosshair (time in New York, OHLC, pre-market or after hours). Drag or a horizontal swipe pans, the wheel or
    a pinch zooms, a vertical swipe on a phone still scrolls the page, and **Reset** returns to the whole range. A
    full 2m day fits a 375 px screen (candles down to half a pixel; zoom in for candles). The chart reads again each
    minute while bars can still change (`live`: a weekday 04:00 to 20:00 New York, the tab visible); no stream. A read
    is at most 600 candles and 60 marks and costs what the picture's does: one cached Tradier minute read (15 s
    cache, shared with ping pictures and Charts) for 2m and 15m, plus the two earlier sessions from disk for 15m; the
    day's daily history once per New York date and a 60 s tail read for 1D. No bars, a failed read or a read past 6
    seconds shows **No chart data** with the reason, never an empty box; a once-a-minute re-read that fails keeps the
    chart already shown. The picture route
    (`GET /copilot/desk/{id}/picture`, `chart_render`) stays for **Look at my chart** and the phone pings.
  - **Timeline ▾** (`/timeline`): one list, newest first, New York time on the
    right and a dot by kind: the investigation's alerts (armed, hit; a sent
    ping for one rides on its row, a held one shows with why), time stop (set,
    pinged, skipped with the reason; whether time-stop pings are off), revisit
    jobs, the fills of the trade
    linked to its plan, and for the symbol over 7 days its thesis-watch
    triggers, phone pings (sent or held back) and today's `decision` journal
    entries. A source that cannot be read is named under the list.
  The `/history` route (`copilot_review.level_history` at the plan's invalidation) still answers; the desk no longer
  shows it (a draft plan card carries "Your history at this level").

  With no ticker (no position, and Main chat or a conversation about no symbol) the centre charts QQQ on the same
  timeframes with the day's fills (any symbol, on their candle) and phone pings sent, from the reserved id
  (`GET /copilot/desk/market/chart`, fed by the session timeline's own fill and ping readers); no plan lines.
  When Main chat's latest turn names a ticker (its question first, then its answer; one of the owner's desk tickers
  or a market or sector fund such as SMH, `lib/desk.ts` `answerSymbol`), the centre charts that ticker instead unless
  the owner picked a position.
- **This week** (`ThisWeek.tsx`, folded at the foot of the thread list's drawer): the copilot's week ("Copilot: Helped
  7 of 9 rated · 23 answers · first text 4.1 s median · $0.38", `GET /copilot/answer-scorecard?days=7`), the morning
  brief's (`GET /copilot/brief-scorecard?days=7`), then the two proofs as /proof reads them, read-only and
  never recomputed: "Alerts: <habit label> · based on 9 of 14 alerts
  answered" (`GET /analytics/exit-habits`, its feedback counts, or its trade
  sample when there are none) and "Radar: <label> · 6 hits rated"
  (`GET /radar/proof`, or its reason when there is no verdict), each saying
  "could not load" when its read fails; under them the Radar setup cards, one
  line per kind and direction from the same read's `setups` ("Dip turning up:
  6 cards · 2 planned · paper 3 of 4 green, +$210", all cards so far, or "No
  setup cards yet."), and Open Proof →; then the plan
  streak's record (`GET /charts/captures/streak`): a tile per
  entry this week in time order (+ planned before entry, − no plan or a plan
  saved late, · a suggested plan waiting to be linked), each titled like
  "NBIS 100C · Tue 10:31 · planned" and opening that trade's page, where its
  linked plan shows; then the counts, the streak and best, and what one more
  planned entry makes. The desk's day timeline (the old Context pane's day Timeline tab) is gone: the centre's
  Feed lists the day's pings and Radar.

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
asking. The thread list and the Needs-you strip count the fills
still waiting, one per trade ("2 fills to link"); pressing it opens the first,
and each Link or No plan opens the next. Proof: `tests/test_copilot_desk.py`,
`frontend/e2e/copilot-desk-fill-link.spec.ts`.

**Pings open on the decision.** A position alert's phone ping opens the
desk thread for that position (see Review a trade or position), so a tap
lands on the decision bar: on the plan's conversation when there is one, else
on the symbol alone, where the bar shows without a saved conversation.

**Alert scorecard** (`components/copilot/AlertScorecard.tsx`, under How the
pings did › Last 30 days in the day report; `GET /copilot/desk/scorecard`,
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
A stock Radar hit (its row in the centre's Feed, or its ping) opens the desk on that hit: what
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

A hit that has a [setup card](radar.md#setup-cards-off-by-default) shows the
card under the summary, worded as the phone ping words it
(`GET /copilot/desk/radar-setup?event=<id>`): the setup in words, "In near 61.20 · out below 59.85 (−2.2%)", how
far the latest recorded Radar price is from the level (today's session only),
the candidate contract or "No liquid contract found.", the owner's record line,
the paper record for the setup once there are enough, and this card's own paper
result. Its **Plan it** does what the ping's button does
(`POST /copilot/desk/radar-setup/{id}/plan`, the same claim and refusals: an earlier
session, a price through the level, a stale quote), stays on the card and
shows the reply, and wakes the alert monitor as the ping's tap does; once
planned the card says so and links **Open its thread →** instead of offering
Plan it again, and a refused card shows why. A plan made today also logs
"Planning. …" as above (if that entry fails to save, **Log planning** retries
it). A card from an earlier session is shown, but its Plan it opens a plan
conversation as for any older hit, since its level no longer applies. Ask
about it asks about the setup.

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
optional, offered only where the item itself is seen and never counted as
waiting (since 2026-11-10). A position's thread (a ping opens the desk on its
decision bar) lists the alerts sent today for its symbol under the decision
bar, each with Prompted a review, Already aware, Too late and Not useful and an
optional reason saved with the tap. A Radar hit's thread puts Useful, Already
knew, Too late and Irrelevant in its own box under the hit's decision, not
inside it. The Telegram ping buttons stay too. Now, the thread list, Close the
day and the evening review never ask for them. An answer is a line with
Change. Saves go through the routes the trade page and the Radar feed use
(`PUT /trades/{trade_id}/phone-alerts/{id}/feedback`,
`POST /radar/events/{id}/feedback`), so /proof counts each one at once. The
thread's rows come from the session read's `to_answer` (below), which still
carries /proof's counts. Proof: `tests/test_copilot_desk_session.py`,
`frontend/e2e/copilot-proof-answers.spec.ts`.

**One main element per thread.** The thread's top reads header, then its
main element, then the conversation: while the decision bar (below) is
asking, it sits between the header and the plan ladder, and the ladder stays
one line, without Full plan; once a decision is logged, or when nothing needs
one, the ladder can be unfolded again. The bar reports whether it is asking
through `onActive`; `DeskThreadTop` places it (`hero`, `compact`).

**A saved conversation opens on its latest question.** When that question
would sit under the message box, the pane scrolls it to the top, under the
breadcrumb (pinned on a wide screen), and a short conversation stays where it
is. A decision still asking, or an alert sent today and not yet answered, keeps
the thread at its top instead (`DeskHooks.holdTop`). The reader's own scroll or
send stops this. The idle message box is one line, in a row with its tools; a
tap in it or any words in it open it to its full size, with the settings and the
read-only note (on a phone, Send too, and an "Across everything" scope).
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
**Close the day** (the strip's item while anything is left, or the ⌘K
command) is a pass through them: it opens the first unreviewed thread in list
order on its question (a position with no conversation opens by its symbol,
`/copilot-lab?symbol=…`, and the pass carries on in this tab), and each answer
or Skip opens the next. Then, in the conversation pane (`ClosePass.tsx`), it
asks the fills waiting to link one at a time (the link bar). An answer or Skip
moves on, the ✕ ends the pass, and the last one ends it. Alert and Radar
ratings are never asked (since 2026-11-10), and a ticker not followed asks
nothing. With nothing left it puts the day's question in
the message box, unsent. Nothing is sent to the model, and the answers go
through the same routes as everywhere else. The strip's item counts all of it
("Close the day: 3 to review", less what was skipped), and the pass itself shows "N of M done": the close questions
(one per symbol) and the fills to link, a skip not counting as done.
`/copilot-lab?close=1` (the [evening review ping](#phone-ping-policy)'s link)
starts the same pass once the list and the session have read, after 16:00
only: the first unreviewed thread by its link, else the fills; with nothing
left, or read before 16:00, it opens the desk as usual.
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
closing the conversation puts it in the drawer's This week record. A
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

**Your record for this setup.** A draft option plan (calls or puts, not stock)
also shows how the owner's own closed option trades opened in the session's
first hour went in the same setup (`SetupRecordLines.tsx`), from the same
read's `setup` (`setup_record.for_symbol`), which the card asks for with
`?setup=true` so the Charts dock's polling never computes it:
- **Gap.** "Gap −2.4%. Your opening calls bought against a gap down of 1%+:
  12 trades, 67% won, +$1,240." Against, with or a gap under 1%, from today's
  gap.
- **Trend.** "NBIS is 3.1% below its 20-day average. Your opening calls bought
  below it: …"
- **Size.** Once Size it for me prices the plan, its sizing lines add "This
  plan: $1,384 of premium, 2.8× your usual $500", and the owner's record at
  that premium or more when it is in his largest quarter.

History is each trade's first entry fill and its market context
(`entry_gap_pct`, and the entry price against `entry_sma_20`). Today's gap and
20-day average are from the chart feed's daily bars, so before today's daily
bar there is no gap line. A cohort under 5 trades, or a size record under 20,
shows nothing; Webull is left out. These are lines of history, never a verdict.
Read-only, no model call; a failed read leaves the lines out (`setup`
unavailable). This is the app's half of the October 29, 2026 opening review;
the Check service's pre-trade check does not see it.

**The top bar's day** (`DeskStatus` in `SessionTape.tsx`, `DayPnl` in `Cockpit.tsx`): **Live** (green dot) with the
New York clock in the regular session, **Pre-market** with the clock, **Closed 16:00** (the calendar's close) after it,
or **Market closed**; SPY, QQQ and VIX's change; Realized today and Open. The phase actions are ⌘K commands (Jump to… on
a phone): **Arm today's plans** before 9:30 on a weekday, and **Close the day** after 16:00 (also the strip's item while
anything is left), which walks each thread's close question (see Close of day).

**Arm today's plans** opens a checklist in the copilot column
(`ArmChecklist.tsx`; below 1180 px it opens the copilot sheet): each armed plan
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
phone Jump to…, Threads and Plan a trade show as icons. One
read, `GET /copilot/desk/session` (owner only, refused while the lab is off),
once a minute while the page is visible, read once by the desk
(`useDeskSession`) for its top bar, strip and lower block, composed in `copilot_desk.py` from readers
that already exist: `day_replay.traded` (Webull left out), the notification
policy's `PhonePing` rows, the Radar store's events for today,
`decision` day-journal entries, scheduled `PlanTimeStop` rows, `today._prep`
and one `chart_feed.quote_rows` read of SPY, QQQ and VIX (the feed's index
mapping), and `realized_today` (the trades closed today, New York's day, Webull left out). Under `to_answer` it adds the position alerts and Radar hits still
waiting on an answer (see Answers for /proof), with the alert, trade and Radar
event ids those answers save against; no other ids go out. Each source fails on
its own. No futures quote is read yet.

**Keys and the palette.** ⌘K (Ctrl+K off a Mac; either works), or the desk bar's
"Jump to…" button, opens a palette over the desk (`CommandPalette.tsx`, a
modal dialog): a search box, then Threads (the thread list's rows in list
order, each with its status line and value), Conversations (from two letters
typed, every saved conversation whose title, symbol or conclusion holds the
words, up to the newest 50 matches, from `GET /copilot/investigations?q=`, so a
closed or old thread stays reachable) and Commands (Plan a trade, Review
my week, What matters right now?, and the day's phase commands: Arm today's plans
and Prep the day before 9:30 on a weekday, Close the day after 16:00). Type to filter, arrows
and Enter to choose, Escape or a click outside to close. A thread opens through
the list's own path (in place, or its deep link); Plan a trade opens the same
unsent "Plan a trade: " link as the desk bar's Plan a trade; Review my week and What
matters right now? send their one turn exactly as their pinned rows do; Prep
the day and Close the day only put a question in the message box, unsent.
The open thread is in the address (`/copilot-lab?thread=<id>`), so Back returns
to the thread before it and a reload stays on it. The bare address opens Main chat for the current New York date. While not typing in a field: J / K open the next or previous
conversation as the list shows it (those under Main, then each ticker's
subthreads when shown, else its newest; folded ones are skipped), N opens Plan a trade (not while the message box holds unsent words), `[` opens or closes the thread list's drawer, and Escape closes the drawer, else the copilot's sheet. No desk key fires in an
input, text area or editable field, ⌘K included, and no other browser shortcut
is taken. A one-line key hint sits at the foot of the thread list on a wide
screen. Browser proof: `frontend/e2e/copilot-desk-keys.spec.ts` (palette,
J/K order, the drawer, keys ignored while typing, the cockpit by the time of day at 1440 and
375 px, the strip and Seen).

The layout follows the screen's width (above: three columns from 1180 px, two from 768 px with the copilot as a right
sheet, stacked below that with a full-screen sheet). While the lab is off only the conversation shows, saying so. On
a wide screen (1024 px and up) the desk takes the whole screen, as Charts does (`AppMain.fullScreenRoute`), and the
book, the centre and the copilot each scroll on their own. From 768 px the
app's navigation folds into one **Menu** button at the left of the top bar
(`useFoldedNav` / `openNavMenu` in `Nav.tsx`), so the desk gets the full
width; it opens the labelled menu (every page, sync, the plan streak), whose
**Keep the sidebar open** shows the full sidebar instead, remembered in this
browser with the same key as Charts' expanded rail (its Collapse folds it
back). A phone keeps its tab bar. Every icon in the Charts rail names itself
on hover or focus (`NavHint`), the sync dot included. Plan a trade is outlined, not the bar's loudest button; with N and
the Jump entry it is the one way to Plan a trade from the desk. The read-only note sits under the message box.

**The desk is home.** While the lab is on, the desk takes the Today screen's
place: it is first in the menu and the phone's first tab ("Desk",
`withDesk` in `frontend/components/Nav.tsx`), `/today` forwards to it, and
the Labs entry for the same page goes. What Today showed that the desk did
not now sits in the centre's Feed: the pings held back today (each saying why), and Watch
today at its foot. With the lab off, Today is unchanged.

The message box (desk and side panel alike) is one box: on the desk the
"About <symbol>" chip, then a full-width text area that starts three lines
tall and grows with what is typed (up to 40% of the page, or about 14 lines in
a panel), then a toolbar inside it (attach and read aloud; mic and Send). A
streaming answer is followed only while the reader is at the bottom of the
conversation: scrolling up to read stops following, and the end follows again
on their next send.

The whole app now uses the desk's look: its graphite surfaces, text and
borders, amber as the one accent (`frontend/app/globals.css`) and its type
(Instrument Sans, with IBM Plex Mono for anything set in `tabular-nums`,
loaded once in `frontend/app/layout.tsx`). `CopilotLab.module.css` restates
the same tokens inside the desk so it reads the same under either theme.
`frontend/lib/desk.ts` holds the shapes the desk's pieces share (the conversation hand-off, the strip's order
(`deskNeeds`), Since you looked, thread-list rows and groups, logged decisions,
the decision bar's wording).
Browser proof: `frontend/e2e/copilot-home.spec.ts` (including a 375 px phone),
`frontend/e2e/copilot-thread-list.spec.ts`,
`frontend/e2e/copilot-thread-head.spec.ts` (option and stock, 375 px),
`frontend/e2e/copilot-answer-format.spec.ts` (the answer format, Sources,
the cleaned conversation and the 375 px composer) and
`frontend/e2e/copilot-desk-context.spec.ts` (the centre's chart and timeline: the plan's lines, the marks, the time
stop, the timeframe buttons and their memory, the no-chart-data state, 375 px, the market chart and This week).

### Ticket

**The Ticket copies; it never sends.** It fills in what the owner types into the Robinhood app by hand. No order is
placed, previewed or staged, no broker API or Robinhood connection is called, and its two routes only read
(`GET /copilot/tickets`, `GET /copilot/tickets/{investigation_id}`; `app/routers/copilot_ticket.py`,
`app/engine/desk_ticket.py`, `frontend/components/copilot/DeskTicket.tsx`). `backend/tests/test_desk_ticket.py` checks
that nothing in it places or sends anything.

- **Only a saved plan has a ticket:** a confirmed plan on the Plans board with its pre-trade plan capture (a plan card's
  Confirm, a Radar setup's Plan it, a checked call's plan), still armed and not yet entered (no fill linked to it and no
  open trade in the symbol opened since the plan, linked or not). Anything else (no capture,
  an open position, a feed item, a chat message) gets 404 or 409. It opens from the Ticket tab's list of those plans,
  newest first, and **Open its ticket** on a confirmed plan card and on the plan thread's header (the book's rows carry
  no ticket icon: a held row is not a new order). With none, the tab says so and offers **Plan a trade**.
- **Contract:** the capture's own strike and expiry, else the plan's "Contract: …" words when they state one strike,
  one type and one date plainly ("NBIS 11/14 105C", "Nov 14 '26 105C"; a year only as "'26" or four digits, so
  "Nov 21 30 calls" is the 30 strike); a spread, a strike range or anything vaguer is not guessed, and the plan's own
  words show under the contract. Then the tab
  offers three real contracts from the option-candidates read (the expiry first at or after the horizon: a pending
  time stop's day, else the symbol's horizon) with the premium a contract, spread, break-even move and the expiry's
  expected move; none is picked for him. A long call or put only; any other plan says so.
- **Quantity** comes from the capture, else the plan's size note (a contract count, else "risk $X" at the default
  limit, rounded down); otherwise blank. **Limit** defaults to the contract's mid, only from a fresh quote, and is
  editable; cost, the most he can lose (the premium) and break-even with the move it needs follow what he types.
- **Quotes:** every figure carries its quote time. A bid or ask older than 15 minutes (or with no time), or a chain or
  price read older than 5, reads **stale** with no number (and no default limit); an open ticket keeps judging the
  quote's age and turns stale on screen (taking back the default limit unless he typed his own), with **Read the quote
  again**; no usable bid and ask reads **missing**. Fixture mode
  shows the copilot's simulated NBIS chain, labelled; replay shows no ticket.
- **Your record** is the plan card's setup lines (`SetupRecordLines`) and the premium against his usual size.
- **Accounts:** the plan's journal account selected, then the Roth IRA and the MCP account, by journal label and the
  last four digits only (Webull stays out; an MCP account not yet in the journal shows as "MCP"). Roth IRA: he places
  it himself in Robinhood. MCP: **Send to Robinhood for your approval** is drawn disabled with the reason (Robinhood
  has not given his account the approvals setting, and the account is empty); there is no sending code behind it.
- Each of contract, quantity and limit has **Copy**; **Copy all for Robinhood** puts them on the clipboard in the order
  Robinhood's option order screen asks for them (symbol, Buy · Call/Put, expiration, strike, limit price, contracts),
  with a fallback copy where the page has no clipboard API. **I placed it** records nothing (the fill arrives by
  Robinhood's email as today) and returns to the symbol's chart; **Not now** closes the ticket.

## Chatter

Buzz from r/wallstreetbets and NYT business headlines, behind the desk Feed's own **Chatter** filter
(`backend/app/engine/chatter.py`, read through `GET /copilot/desk/feed` as its `chatter` block). Isaac asked for it;
his own trade audit says unplanned entries lost the money and buzz is where those start, so it is fenced:

- Only behind the **Chatter** filter: never in Mine, Market or Mine + Market, never in a symbol's story, never counted
  as new, never on the home view or the Needs-you strip, never a phone or Telegram ping. The filter appears only while
  at least one source is on and has rows; when a source is on but cannot be read or has nothing yet, the Feed's foot
  says so. `chatter.sources` names each source's state: `on`, `not set up` or `unavailable`.
- A chatter row's only actions are **Ask the copilot** (the row, quoted, in the box unsent) and the outbound link,
  which opens Reddit or the NYT in his own browser. No Plan it, no Open in Charts, no countdowns, no hype relayed as a
  headline. Facts and counts; nothing tells him to buy, sell or hold.
- Third-party text (post titles, headlines, summaries) is data shown as data. None of it enters the copilot's owner
  context, no model reads it in the background, and a ticker set to not followed is left out here too.

**r/wallstreetbets.** Every 15 minutes on market days, 06:00–20:00 New York, the reader takes the subreddit's hot,
rising and new listings (three calls, 100 posts each) through Reddit's official API with the app's own credentials
(application-only OAuth, the user-agent Reddit's rules ask for; it waits for the window to reset if Reddit's
remaining-calls header runs low). It never loads reddit.com pages or the unauthenticated JSON endpoints. Ticker mentions
are counted in post titles against the app's known symbols (Radar's universe, his traded tickers, SPY/QQQ/SMH), each
post once, by when it was posted; all-caps words that are not tickers (the brief scorecard's list plus the
subreddit's own: YOLO, DD, CALLS, ALL, ON...) count only written as a cashtag (`$ON`). Thirty days of mentions are kept
in `backend/data/chatter/reddit.json` (no table). Only an error's type is logged or saved (an HTTP error's text could
hold a request URL with the NYT key), and a failed read waits the full 15 minutes even when its state cannot be saved.
Rows:

- **Buzz**: a ticker named in at least 3 posts in the last hour and at least 3× its usual rate, where usual is the same
  New York hour on up to 5 recent weekdays the reader covered ("NBIS mentioned 6.2× its usual rate in the last hour";
  "usually none at this hour" when it was never named then). Until 3 such days exist, the raw count and "No usual yet."
  Beside it, when the journal can compute one, his own record on entries made while the entered ticker was buzz (one
  total across every ticker in the 30 days kept, not-followed tickers left out; Webull left out): "Your entries during a
  mention spike: 12 closed trades, 5 up, net −$1,240." At most five; the same tickers show as chips
  (ticker and multiple) at the top of the filter, outlined when he holds the name. Its link is the subreddit's search
  for the ticker.
- **Rising posts**: the top five rising posts (not pinned, not marked NSFW): title, points, comments, and a link to
  the post.

**NYT.** Every 15 minutes, 06:00–22:00 New York, every day: the public Business and Economy RSS feeds, or the official
Top Stories API (business section) when `NYT_API_KEY` is set. Headline, the feed's own summary, time and link, at most
eight from the last 36 hours, tagged **NYT**. No article page is ever fetched and no subscription login is used.

### Switching chatter on

Both are off until set up; while off nothing is read and nothing is spent. Setting these on the server is Isaac's call.
They go in the server's private backend settings file (`/etc/tradejournal/backend.env` on the VPS), then the API is
restarted.

**r/wallstreetbets** (free):

1. Sign in to Reddit in a browser and open https://www.reddit.com/prefs/apps.
2. Choose **create another app...** (or **create app**). Name: `tradejournal-chatter`. Pick **script**. Redirect URI:
   `http://localhost:8080` (required by the form, never used). Choose **create app**.
3. The app's box now shows two values: the short string under the app's name ("personal use script") is the
   **client id**; the longer one labelled **secret** is the **client secret**.
4. Add these lines to the settings file, with your own values:

   ```
   CHATTER_REDDIT_ENABLED=true
   REDDIT_CLIENT_ID=<the client id>
   REDDIT_CLIENT_SECRET=<the secret>
   REDDIT_USERNAME=<your Reddit username, without u/>
   ```

   The username only goes into the polite name the app gives itself when it calls Reddit, as Reddit's rules ask.

**NYT headlines** (free, no account needed):

1. Add `CHATTER_NYT_ENABLED=true` to the settings file. That alone reads the public RSS headline feeds.
2. Optional: create a free key at https://developer.nytimes.com (sign up, **My Apps**, **New App**, enable the
   **Top Stories API**, save, copy the key) and add `NYT_API_KEY=<the key>`. With a key the reader uses the API instead
   of the RSS feeds.

To switch either off again, set its `CHATTER_..._ENABLED` line to `false` (or delete it) and restart the API.

## Check a call

Isaac shares a trade call from his Discord group and gets one card back saying
what the evidence shows (`backend/app/engine/call_check.py`). From the iPhone:
long-press the Discord message, Share, Telegram, the TradeJournal bot; or paste
it in the desk's **Check a call** tab (the centre tab strip).

- **The check.** One bounded copilot turn as the `check_call` job (§ Jobs),
  under the turn and daily budgets, recorded like every turn (`kind`
  `check_call`). The model reads the call (ticker, expiry, strike, call or put,
  entry, stop, target: a value or `?`), reads `get_call_facts` (the underlying
  now; when expiry, strike and side are known, the contract's bid and ask
  against the posted entry and whether the ask is already past it; the
  contract's cost against his usual opening option premium, the plan card's
  sizing median; his closed option trades in the symbol, in it on that side,
  and on that side with the same kind of expiry: 0DTE, 1-7 days or longer)
  and writes the card: a verdict (Pass, Wait or Draft), three or four tiles,
  Against and Changes if. The verdict weighs his record, not only freshness.
  "0dte"/"odte" is today's expiry; several calls: the first is checked, the
  rest listed. Nothing is guessed: for a text message `call_check.confirm`
  blanks any ticker, number, call/put marker or expiry the message does not
  state (a price like `.50` included), and with no ticker the card says "Could
  not read a ticker" and has no buttons. When it blanks a value the model had
  filled, the model's card rested on a guess: it is replaced by Wait, "the
  message does not state the …", with no tiles. A screenshot is read by the
  model alone.
- **Call or question (Telegram).** `call_check.classify` counts call markers:
  a strike with c/p counts two; 0DTE, a month/day, an entry word or `@ price`,
  a stop/target/"hits" word, a `$` price and a `$TICKER` one each. Two or more
  with no question marker is checked at once. Question markers: a closing `?`,
  a first word such as what/why/should, "my", his own trade in his words ("I
  bought…", "rolling to…", "took profit…", "set stop…"), or a reply to another
  message (a reply to a ping keeps the ping's context). Two or more with a
  marker, or exactly one, is ambiguous: answered as a normal question with
  **Check as a call** on its own row under Helped and Didn't; none is a
  question. `check` first forces a check unless what follows asks something
  ("check my positions", "check on NVDA…" stay questions); `check` or `check
  this` as a reply checks the message replied to. A photo with no caption is
  checked first and, when the model says it holds no call ("Not a call"),
  answered as the broker-screenshot reconcile as before: one extra turn for a
  broker screenshot.
- **The reply.** The card in chat lines: the verdict line, `Read:` with blanks
  named ("call or put: not stated"), the tiles, Against, Changes if, and the
  other calls. Buttons: **Plan it** (a link, `call_check.plan_href`: the desk's
  plan flow for the symbol with the poster's levels as editable text in the
  message box and the check as the plan's origin, never a ticket), **Pass**
  (`cc:<id>:pass`, recorded once; the keyboard shows "✓ Passed") and **Why?**
  (the existing ping Why?). No rating ask.
- **The tab.** A paste box, the reading as chips (blank entry, stop and target
  are inputs he can set; they join the Plan it text as "my stop 664"), the
  card, Plan it and Pass, then **Checked today** once anything was checked (from the desk and Telegram:
  time, contract, verdict, the underlying's price then, passed or plan saved). The verdict tags and buttons are
  neutral, not amber: on the desk amber is only the Needs-you strip.
  Only a saved plan counts as planned; its ticket then opens from the saved plan ([Ticket](#ticket)).
- **The log.** `call_check` table, one row per check: when (UTC and its New
  York day), the source, the raw text, the reading, the verdict and card, the
  underlying's price and the contract's quote at that moment (`quote_json`),
  Pass (`outcome`) and the turn. Planned is read from `TradeCapture` with
  `origin_kind = checked_call` and the check's id. `GET /copilot/checks?day=`
  is the day's list for the tab; the desk's day report scores each check from
  the price when he checked, never from the posted price (§ The desk, Checked-call scoring). `POST /copilot/checks` checks a pasted call;
  `POST /copilot/checks/{id}/pass` records Pass.

## How the copilot reasons (system prompt)

Every model turn has a job, and its instructions are assembled for that job
in `backend/app/ai/copilot_prompt.py` (§ Jobs below). The desk's,
`copilot.SYSTEM_PROMPT`, frames a question asked on the desk, Charts, Radar
or the panel:

- **Who it works with**, as working hypotheses to test against what the owner
  does, never a diagnosis: debate-driven; semiconductors, AI infrastructure,
  recoveries, relative strength and catalysts; a longer thesis often expressed
  through a short-dated option. One sentence says exits, more than entries,
  decided their results and points at the owner context block's live
  exit-habit counts (the [behavior audit](../backend/reports/behavior_audit_2026-10-21.md)'s
  habits, scored on recent trades): associations, not rules, since the exit
  counterfactual rejected the mechanical exits; raise one only when the
  position in front of it resembles it, never recite them. The audit's fixed
  figures left the prompt on 2026-11-10: the block carries the live counts.
- **Four separate questions** for any trade idea: thesis, setup now,
  instrument fit (expiry, strike and premium against the horizon, from real
  contracts through `get_option_candidates`, with the provider's implied
  volatility, Greeks and each expiry's expected move; a figure the provider
  did not give stays null, never estimated), and
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
- **Short answers.** A hard limit: at most three one-sentence bullets in the
  body, one-sentence Against and Changes if lines, under 120 words in all,
  leaving out whatever does not change the verdict; no preamble, tool tour or
  closing summary, and a plan's fields stay on its card rather than in the
  text. The rule comes with word budgets that add up under it (headline 15,
  each bullet 16 as one sentence, Against 20, Changes if 15, a compare cell 6:
  `copilot_answer.MAX_WORDS` and the `*_WORDS` constants) and is repeated
  where the answer is written: the
  `copilot_answer.ANSWER_SHAPE` reminder ends the owner's prepared message and
  follows every tool-result batch as a text block, because the same rule in
  the middle of the 3,700-word system prompt was not followed (the first,
  softer "about 120 words" rule produced about 300-word answers in the
  2026-10-29 live check; the hard rule still gave 150–295 words, four or five
  multi-sentence bullets and a closing note on 20 of 22 cases in the
  2026-11-06 eval, § Follow-up model eval; with the reminder the median fell
  to 128 words and 38% of cases came in under the limit, the rest 121–153
  words on two- or three-sentence bullets, so the bullet budget went from 22
  to 16 words on 2026-11-08, after which 82% of cases came in under the limit
  at a 108-word median, § Answer-length re-measure).
  `copilot_context.user_text` strips
  the reminder, so the scripted model and the spend record read only the
  owner's words. A trade review, a
  week review or an explicit "more", "why" or "go deeper" gets the room it
  needs. Length is the wait: after a tool result, Sonnet 5.5 sends the whole
  answer at once at about 100 tokens a second (§ Live measurements).
- **The answer format.** Market reads, trade ideas, position reviews, plans
  and other trading decisions start with
  `Verdict: <word> — <headline>`, the headline one plain sentence in the
  model's own words for the case, with the word from a fixed
  set: Hold, Wait, Pass, Focus, Draft, Pattern, Broken (the plan's
  invalidation or the thesis broke: what the plan says, never an order) and
  Unclear. For app capability or navigation questions, definitions and other
  general information, the answer is direct prose without a Verdict line.
  This avoids presenting an informational answer as a trading action. Then
  the body in short paragraphs or bullets, and, when one thing
  would change the answer, a last line `Changes if: …`. The frontend parses
  the structure rather than guessing it from prose (`lib/copilot.ts`
  `answerParts`, `VERDICTS`): the verdict as a small tag, the headline in
  bold, the body, then a plain "Changes if …" line. An answer without it (one
  saved before the format, a backend that ignores it, an unknown word, an
  error) renders as plain text. A full stop or colon after the verdict word
  (`Verdict: Wait. Not yet.`) reads like the dash in both parsers, since the
  model writes one now and then (two of 23 answers on 2026-11-07). The scripted `fake` backend writes every
  answer this way (`copilot.scripted`), with its simulated-model note (and
  any image note) under the Verdict line. Read aloud, the line becomes
  "Hold. The thesis has not broken."
- **The case against.** On an answer about a trade idea, a thesis or a
  position decision, the line after the Verdict is the Read line: `Read:`
  then Thesis, Timing and Contract, each with one or two plain words of the
  model's own, separated by middle dots (`n/a` for Contract when none is in
  question), and the body ends with `Against: <the strongest case against
  the verdict, with its number or source>` before any Changes if line;
  "nothing in the evidence" only when that is true. A claim no tool or owner
  context shows gets a body line `Unsupported: <claim> — <what would support
  it>` instead of being reasoned from. `answerParts` returns `read` (only when
  all three parts parse) and `against`; the desk shows the read as one small
  line under the headline and Against set off in amber above Changes if, and
  read aloud they become "Thesis holds, Timing early, …" and "Against that,
  …". The scripted group reads carry both. Every finished answer's headline,
  bullets and Against line carry a small reply button, **Push back on
  this** (with a mouse it shows while its line is hovered or it has focus; a touch screen always shows it): it puts `Push back on "<that line>": ` in the message box, unsent,
  for the owner to finish (the disagreement rule then re-checks the evidence
  they dispute). Under a finished answer the desk's chips include **More**,
  one turn asking for the full reasoning behind it (the length rule gives the
  room back on "more"). A new conversation is named on its first save by its
  ticker and purpose, then a few of the owner's own first words: "NBIS · plan"
  (started from Plan a trade, or its answer proposed a trade plan), "AAPL ·
  question: is the group confirming" (`CopilotPanel.tsx` `threadTitle`; "Question"
  or "Plan" when it is about no ticker). It was the first answer's headline
  until 2026-11-10; a saved name is never changed. A thread list row for an open
  conversation with no conclusion yet says "Open question". The scheduled turns' phone pings and
  saved conclusions drop the "Verdict: " label (`premarket_prep.unlabelled`,
  `week_review_auto._plain`); their saved answers keep it.
- **Comparing two choices.** When the owner weighs two options (two
  expiries, entering now or at a level, adding or replacing), the body is
  a compare block instead of the bullets, under the same length limit:
  `Compare: <A> | <B>`, then the rows `Needs: … | …`, `Risks: … | …`,
  `Breaks if: … | …` and, when a contract is involved, `Costs: … | …`
  (premium, break-even move or time value from `get_option_candidates`),
  then Against and Changes if as usual; the block is the whole body, no
  bullets beside it and no fifth row. The headline says which side the
  evidence favours, or that it is a coin flip; it never recommends a
  contract. `answerParts` returns `compare` only when the Compare line and at
  least two rows parse (otherwise the lines stay in the body); the desk shows
  a two-column grid with the scenario names as headers and the row labels on
  the left, and where the answer is narrower than 28rem (a phone, the chart's
  side panel) two labelled cards, A then B, with nothing scrolling sideways.
  Each cell carries Push back on this (`Push back on "Needs (<side>): …": `).
  Read aloud a row is "Needs: A, …; B, …". The `fake` backend answers a
  message with " vs " or " or " plus "which" or "compare" with a scripted
  coin-flip compare (`FakeAdapter._compare`), so the sandbox and the browser
  tests show it without a model call.

Tests pin the sentences other guards depend on (`tests/test_copilot_answer_format.py`
on the answer format and the scripted answers, `tests/test_copilot_book.py`
on account identifiers, `tests/test_copilot_adversarial.py` on "you cannot
create alerts or research jobs yourself", `tests/test_copilot.py` on the
four-question frame and the memory rule).

### Jobs

Until 2026-11-10 every turn the app runs got the desk's prompt (3,792
words), all 26 tools (about 22,700 characters) and the desk's shape
reminder, so the morning brief was told "at most 10 plain lines, no
headings" and then the Verdict / Read / bullets / Against shape, and the
companion "at most 80 words" beside the same five-part shape.
`copilot.run_turn(..., job=)` now takes the turn's job, which
`copilot_spend.recorded_turn` works out from what its callers already pass
(`copilot_prompt.job_for`: kind `check_call`, else source `telegram`, else
kind `prep`, `companion` or `week_review`, else `desk`). Each job gets the shared core (who the owner
is, the four questions, the evidence, time, untrusted-text, account,
SIMULATED and no-order rules), a line framing its own job, only the working
rules it uses, its own answer format and its own shape reminder
(`copilot_answer.*_SHAPE`, sent where `ANSWER_SHAPE` is on a desk turn), and
only its own tools; a tool call outside them is refused like an invalid one,
and no job's prompt names a tool it is not offered (`tests/test_copilot_jobs.py`).
Telegram keeps the week-review rule, so a typed "review my week" there is
answered as on the desk, in the chat format.

| Job | Who runs it | Answer format | Tools | Prompt + tools |
| --- | --- | --- | --- | --- |
| `desk` | desk, Charts, Radar, panel | as above, unchanged | all 25 | 3,715 words + 22,200 chars, about 11,700 tokens |
| `telegram` | typed, spoken or photo question, Why? | Verdict line, at most three short plain lines, Against, Changes if; no Read line, no Compare rows, no markdown; under 120 words | all 25 | 3,207 words, about 11,000 tokens |
| `prep` | morning brief (`premarket_prep`) | the lines its message lists, plain, no Verdict/Read/Against, no headings | 11 market reads | 1,173 words + 6,800 chars, about 3,700 tokens |
| `companion` | position companion (`position_companion`) | exactly the shape its message gives (the adopt draft's six lines, an update's 80 words, the exit note) | 12: the trade review, chart, group, news, quotes, level history, option candidates, trades | 1,342 words + 9,200 chars, about 4,600 tokens |
| `week_review` | automatic week review (`week_review_auto`) | Verdict line, then the review in short one-fact lines | 5: week and trade review, trades, proof, `propose_plan` | 1,278 words + 7,700 chars, about 4,100 tokens |
| `check_call` | Check a call (`call_check.run`, from Telegram or the desk tab) | a Reading line (`?` for anything not stated), Verdict (Pass, Wait or Draft; Unclear only with no ticker), three or four `Tile: label \| value` lines, Against, Changes if, Also for other calls; "Not a call" for an image with none | 5: `get_call_facts` (its own job's alone), quotes, chart, level history, trades | 1,271 words + 5,000 chars, about 3,300 tokens |

Token figures are estimates (characters ÷ 4 for prose, ÷ 3.5 for tool JSON);
the scorecard's input and cache figures are the measured ones. The brief
reads no owner context block (`copilot_prompt.OWNER_BLOCK`): its own facts
pack already carries the positions and plans, which it used to get twice.
The desk's "Review my week" still runs as a desk turn with the desk's format.

The book reads that only repeated the owner context block went on the same
day: `get_memories` is gone (the block carries the symbol's and the general
memories; another symbol's come with `get_owner_context`), and the others say
in their description when they reach beyond it: `get_owner_context` for a
different symbol, `get_trades` for more of a symbol's closed trades than the
block lists, `get_positions` only when the block shows fewer positions than
its count or every one is needed (a broker screenshot). A review of this trim on 2026-11-11 found nothing more to
remove: `get_memories` was the 26th tool, so 25 remain, and each of the three
reads has a path the block lacks (another symbol; trades past the latest four;
positions past the block's eight). A symbol's memories past the block's eight
have no read, and the block does not count them. The example answer
lines ("Verdict: Hold — The thesis has not broken.", a sample Read line, the
sample compare questions) became descriptions of the form, since earlier
example answers were copied word for word.

**Caching.** Each job's tools and system prompt are fixed strings in a fixed
order, with nothing volatile in them (the clock, the symbol, the owner block
and the earlier evidence all ride in the owner's message). The request puts
an explicit cache point on the system prompt, which covers the tools ahead of
it, so a job's prefix is written once and read by its later turns within the
cache's five minutes; the top-level automatic cache point still moves with
the conversation tail for reuse between a turn's rounds. Before, only the
automatic point was set, at the end of each new question, so the fixed
prefix was written again on every new question. A web-search turn's prefix
includes the search tool and is cached apart from a turn without it. Cache
read and write tokens are recorded as before, so the scorecard's cache share
shows the change on the next live week.

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
  - `positions` (measured): one `trader_context.for_symbol` call a turn (§
    Trader context), rendered: `get_positions`' rows, the turn's symbol first (put
    ahead before any cut, so a large book never drops it) and at most 8, each with its minutes held when opened today, days to expiry and
    expires-today flag, the give-back watch (`not armed`, `armed` or `fired`,
    with the peak gain), the last three phone alerts sent for it, its thesis
    object as `plan` (`source` plan card, Charts plan, companion or `none`;
    setup, the owner's own wording, entry, invalidation, time stop, horizon,
    timing, the latest revisions), the owner's decisions since the entry and,
    for the turn's symbol only, the `since_entry` diff: each line with its
    `from` (source) and its own `as_of` when that differs from the diff's.
    Third-party words never enter this block: headlines appear as a count only
    (the model reads them with `get_symbol_news`), a companion revision names a
    thesis-watch trigger by kind without its headline, and the companion's
    thesis guess (written by a model that had just read headlines) stays on the
    desk, like a research job's conclusion.
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
  - `practice` (owner said; its count measured): the active practice goal the
    owner confirmed from a Review my week card (`practice_goal.current`, the
    same read as the briefing's grey line): their words, the measure, the
    target and this week's count so far (or the week it starts), cached two
    minutes. `{"goal": null}` when none is active.
  - `market` (measured), read beside the pack (`copilot_context.market`, added
    by `with_market` in `copilot.owner_context`, placed right after the pack's
    header): the same reads the tools make through the turn's evidence
    (`get_quotes`, `get_market_regime`, `get_group_comparison`,
    `get_radar_today`, run side by side in worker threads; the quote is the
    symbol's alone, the prefetch's own call, so live both are one Tradier read
    through the chart feed's 15 s cache), compacted to
    lines, each with `as_of` and `from` (its source): SPY and QQQ day change
    from the latest Radar pass, and VIX; for the turn's symbol its last and day change, its off-hours move
    outside the regular session, its sector ETF from the latest Radar pass,
    and its Radar group against SPY since the open with the last 15 minutes'
    breadth; then today's Radar events that name the symbol (read for that
    symbol, so other events never push them out; summary, first seen, latest
    status, at most 3, with their count). With no symbol: the index line and the
    day's Radar leaders and laggards against SPY (three each) and the newest
    three events, with the session's event count.
    A read that fails or is still running at `MARKET_TIMEOUT_S` (3 s) is listed
    under `unavailable` and the rest stand; the turn never waits longer for it.
    The pack's header tells the model these lines are fresh enough to answer
    from and that the tools are for anything beyond them. It is the turn's
    block only: `get_owner_context` and the Open threads read do not carry it.
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
  round (beside the carried-evidence read and the symbol's prefetch), so a slow
  quote provider adds up to the tool timeout to a turn. Over the size cap, the pack sheds the
  least decision-relevant parts first (recent trades, today's notes, the
  since-entry lines' sources and the plan revisions, every since-entry line but
  the mark past the symbol's first position, those positions' decisions, alerts
  and plan notes, investigations, memories, then positions beyond three) and
  marks itself
  `trimmed`; positions and habits go last. With the `market` section the
  turn's block may hold 1,400 characters more (`MAX_MARKET_CHARS`; the section
  itself runs 500 to 1,100); past the cap it sheds the market's source labels
  and all but one Radar event right after today's notes, and its events,
  leaders and laggards after the memories. Its lines and the practice goal are
  never dropped.
- The UI shows it as the first evidence row of every answer ("Your context",
  provenance `saved`, with a one-line summary such as "2 open (NBIS +6.1%,
  give-back armed) · 3 memories · 1 investigations"), and the saved
  investigation keeps that reference like any other.
- `get_owner_context(symbol)` returns the same pack for a different symbol.
  Research jobs never get it (it is not in their allowlist): it carries the
  book.
- Fixture mode serves a simulated pack marked `simulated` (its market lines
  too); replay says the pack is unavailable, as the book is, but still carries
  the market lines, read from the snapshot at the frozen moment (no VIX, as
  `get_market_regime` in replay; nothing after the clock). The fake model reads only the owner's
  words after the block (`copilot_context.user_text`), so the pack's text never
  steers its scripted tool choice.
- No account number, account id, trade id, fill id or broker id is in it; the
  only ids are saved investigations'.
- Tests: `backend/tests/test_copilot_context.py`, `backend/tests/test_trader_context.py`,
  `backend/tests/test_copilot_market_pack.py`.

## Trader context

One record per open position, planned or not, in
`backend/app/engine/trader_context.py`: the Desk's thread header, Charts'
Holding context, the Today screen's Act now rows and the Dashboard's Plans
card (`plan_positions`), position alert and companion phone bodies, the
pre-market prep and the owner pack all read it instead of rebuilding a
position's plan each in their own way. It is built from readers that already
exist (`copilot_book`, `capture_links`, the plan card's level alerts and time
stop, `position_companion`, `position_alerts`, `day_journal`, Radar's
since-entry comparison, the news reader) and writes nothing.

- **Thesis object.** `source` is `plan_card` (a confirmed plan card: its
  capture, entry and invalidation alerts and time stop), `plan_sheet` (a
  Charts plan linked to the trade: the owner's words; its chart levels are
  annotations, not rules), `companion` (the adopted draft: the thesis is the
  copilot's guess and says so, the invalidation is the alert Confirm armed, or
  a draft) or `none`. Each carries the same fields: label, text, direction,
  entry trigger, invalidation, time stop, horizon (the owner's newest pick on
  the desk, else the plan's), captured time and timing, the plan's
  investigation, and revisions (capture notes, companion updates and the
  owner's Closed it / Holding answers). A plan card and an adoption are the
  same shape, so an adopted position with an armed invalidation now shows its
  plan on Act now and the desk header (before, `plan_positions` read captures
  only and called it unplanned).
- **Alerts and decisions.** Phone alerts sent for the position and its plan's
  level alerts hit; the owner's decision-bar entries since the entry.
- **Since entry.** Deterministic lines, each with `state` (`ok` or
  `unavailable`: a missing input is never a zero), `as_of` and `source`: the
  underlying vs its price at the first entry fill (fill market context, else
  the fill's enrichment) and vs the invalidation; the symbol and SPY since the
  post-entry baseline with the group's peers (Radar's same-session since-entry
  comparison, so today's regular-session entries only: an overnight hold reads
  unavailable); the option mark vs the average entry; IV now (the provider's)
  vs at the fill (Black-Scholes on the fill premium: different methods, and the
  line says so); headlines naming the symbol since the entry (the news reader:
  a provider read, so only the symbol a page or turn is about reads it); time
  held vs the time stop, horizon and expiry.
- **Entry points.** `for_symbol(symbol, now)` (the symbol's positions get the
  diff; the owner pack and `GET /charts/journal/positions/{symbol}/context`),
  `for_day(now)` (every position's diff, the day's decisions and ping counts),
  `for_trade` (one position), `records` (a book a caller already read).
- **Phone line.** `phone_line` writes "Since you entered: plan: … · NBIS 98.50
  at 10:53 is 1.5% above the invalidation 97.00 · held 48 min · time stop …"
  from the database and the alert's frozen Radar snapshot only: no provider
  read, so a send never waits on a quote. Position alerts add it under their
  Radar block, as of detection, so a retry sends the same words; companion
  updates add it under the answer, with the underlying the companion already
  read, and the update prompt gets it too. No new alert kinds, triggers or
  senders.
- **Screens.** `frontend/components/SinceEntry.tsx`, refreshed each minute while
  visible, leads with at most three plain lines worked out from the lines'
  values: P&L and the mark (an option's per share, as the header shows it); the
  plan's distance to its invalidation and its time stop, or "No plan saved"
  once; and what changed (the underlying since entry, SPY and the group's
  peers, the headline count). The thesis, every line as the record wrote it
  with its source and time, the headlines and every `unavailable` line wait
  behind **Sources and gaps**, in muted grey, never amber. Times are New York
  time (the headline line's UTC clock is rewritten). It sits under the desk's
  thread header for an open position and in Charts' Holding context for the
  selected trade. On a thread with a conversation it starts folded to one
  summary line that opens on tap, so the latest answer stays near the top; a
  symbol opened with no conversation shows it open, and its header row carries
  the symbol and horizon (no second ticker line while it is held). Act now rows show the thesis line.
- **Telegram on the desk.** Each Telegram question and Why? answer is saved on
  the symbol's desk thread (its plan, the companion's adopted conversation, or
  its newest open conversation, with that thread's `updated_at` kept so thesis
  watch re-checks the same one), else in today's Main chat. Only the owner's own
  words are saved as theirs: a Why? tap reads "Why? on a ping", never the ping's
  text. No conversation is created, since an open one with a symbol would start
  thesis-watch pings. A voice note to the bot is a question too: 30 seconds and
  3 MB at most, transcribed by this server's Whisper with the owner's tickers as
  vocabulary (as hold-to-talk is), confirmed back as "Heard: …", then asked like
  a typed message; the heard words are what the desk keeps. A trade plan the
  turn proposes is saved on the answer with the same shape and id as a desk
  card (Main chat gives it its own plan thread), then sent as a message of its
  own: the card's lines, **Confirm** (`pl:<card client id>:confirm`, which
  runs the same parts as the desk's Confirm: the pre-trade plan, then the
  entry and invalidation alerts and the time stop; see Confirm a plan) and
  **Edit** (the thread). Each answer saved on the desk is sent with **Helped**
  and **Didn't** under it (`hd:<conversation id as 32 hex>:<message index>:h|d|n`):
  a tap sets that answer's rating through `copilot_investigations.set_rating`,
  as the desk's buttons do, so the answer scorecard counts it; the other button
  switches, and the checked one carries `n` and clears. The saved answer keeps
  its turn's `turn_id` in `metrics`, so the scorecard meets it (source
  `telegram`) even on a thread older than its window. The bot's taps: `fb:`,
  `rr:`, `hd:`, `pc:`, `pu:`, `pl:`, `why:` and `ask:`
  (`engine/telegram_replies.py`).
- Headlines are read through a two-minute cache per symbol and entry, so the
  desk header's and Charts' minute refresh and repeated turns make one news read.
- The context route is owner-only: it is in `access_manifest.DOMAIN_ROUTES`,
  not in the journal paths an assistant may read.
- Tests: `backend/tests/test_trader_context.py`, the unplanned-position case in
  `frontend/e2e/copilot-thread-head.spec.ts`.

## Follow-ups keep the evidence

The panel sends only the conversation's text, so a follow-up used to lose
the numbers the previous answer read and either read them all again (another
held answer, see § Live measurements) or reasoned from its own prose. Now
each turn keeps its successful tool results (`copilot.carry_items` /
`keep_carry`): at most 6 reads, 2,500 characters each, newest first, a
re-read replacing the earlier one, for 2 hours. They are kept in the process
(at most 64 conversations) and in the `copilot_carry` table with the
conversation's investigation when it has one (one row per investigation,
expired rows pruned on write), so a follow-up after a restart, or after a
reload that lost the id, finds them by the id or by the investigation and
reads nothing again. Cards (`propose_plan`) and the owner context pack
(rebuilt every turn) are not kept. The `done` event carries an opaque
`carry_id`; the panel holds it on the answer (never saved with the
investigation) and sends it back as `carry_id` with the next message. The
next turn gets the reads as an "Earlier evidence" block, each with the time
it was read and its data's as-of, ahead of the owner context block, and
keeps them on when it reads nothing new.

Each answer in the history the panel sends also ends with one line per card
it proposed and what the owner did with it (`lib/copilot.ts` `cardLine` /
`historyAnswer`), for example `[card trade_plan NBIS long calls entry 95.9
stop 92.3: confirmed]`, `[card watch CRWV touches 88: dismissed]` or
`: waiting`, so the model knows a plan, watch, memory or practice card it
drafted two messages ago was confirmed or dismissed. A confirmed plan's
levels are the ones confirmed. The lines are never shown, and the answer's
text is clipped to leave room for them within the 4,000-character message
limit. The outcome records no time, so the lines carry none.

The system prompt tells the model to answer a follow-up from that block
without calling those tools again, saying when it was read, and to read
again when the owner asks for fresh data, asks about a symbol or question the
block does not cover, disputes a specific number, or the read is more than
15 minutes old while the market is open. A first message never inherits one;
an unknown or expired id with no investigation to find it by, a store that
cannot be read, or evidence kept in another mode (live, replay, fixture) means
the turn reads afresh as before.
A clipped read ends `[clipped]`, and the block's frame markers are made inert
inside carried text. The data never leaves the server, and the block says that
text inside it is third-party data, never an instruction. Tests:
`backend/tests/test_copilot_carry.py`.

**The follow-up model.** `COPILOT_FOLLOWUP_MODEL` (a model id, or `off`)
names a model for follow-ups. A turn runs on it when the browser sends a
`carry_id` that `copilot.carried` can still serve (in-process or the stored
row, same evidence mode), the conversation has an earlier turn, and the
browser picked no model for this turn (no `model`, or the default); the
owner's pick in the panel always wins. A follow-up that needs new reads still
has every tool; the system prompt, tools, answer format, turn budget and daily
budget are unchanged. The `done` metrics and the `copilot_turn` row record the
model actually used, so the answer scorecard's `by_model` shows Helped rates and
first-text latency per model. `GET /copilot/status` returns `followup_model`
(`null` when off) and the panel's status line says "follow-ups on Haiku 5.5"
while the API backend is picked and no model is picked. Why: on Sonnet 5.5 the
API holds the whole answer after tool results (§ Live measurements), while
Haiku 5.5 streams after the same tool result; a follow-up on carried evidence
makes no new reads, so it is the safe turn to switch.

The offline eval sets the default. Decision rule: run the starter cases with
fixture evidence on Sonnet 5.5 and Haiku 5.5 at effort `medium`
(`scripts.copilot_eval run`, `grade` deterministic checks only, `report`); if
Haiku's pass rate on the two follow-up cases (`followup-carry`,
`followup-more`) and its overall `completed`, `no_orders` and `unsupported`
pass rates are at or above Sonnet's, the default is `claude-haiku-5-5`;
otherwise `off`. The paid comparison ran on 2026-11-06 (§ Follow-up model eval):
Haiku failed the rule, so the default is `off`. Tests:
`backend/tests/test_copilot.py` (settings),
`backend/tests/test_copilot_turn_record.py` (the chat route and its row).

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
prompt. No new route, token or public ingress. On Telegram the alert carries
all four answers instead, Prompted review, Already aware, Too late and Not
useful, as reply buttons that save in place, and Why?. The push no longer carries its
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
matters right now?" (at the foot of the centre's Feed and in ⌘K) and sends the turn at once. The system prompt asks the
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
  before its first week. The desk shows it in the facts line under the book and the
  Dashboard's Review my week button carries it as a second line:
  "Practicing: exit at my invalidation · 2 of 3 this week" (or "starts Mon,
  Oct 26"). Nothing shows while no goal is active.
- The ping that tests the active goal ends with one sentence naming it and the
  week's score so far (`practice_goal.ping_line`): "Practice this week: no new
  trade while the day is green · kept 2 of 3 so far", or "Practice from Mon
  Nov 9: …" before its first week. `no_opening_while_green` rides the
  green-day pattern interrupt, `respond_to_giveback_15m` the give-back alert,
  `no_trade_after_hour_red` the one-hour alert, `exit_at_invalidation` the
  plan's invalidation ping and `plan_before_entry` the plan nudge (not the link
  ping); `max_trades_per_day` has no ping that tests it, so none carries it. A
  failure leaves the ping as it was; triggers, budgets and dedupe are unchanged.
- No id is returned to the page or the copilot. Research jobs never see it.
- Tests: `backend/tests/test_practice_goal.py`,
  `frontend/e2e/practice-goal.spec.ts`.

### Exposure

One deterministic line beside the practice goal in the desk's facts line under the book,
and in the 09:00 brief: "At risk now: $6,400 in 3 options · usual day $2,100"
(`backend/app/engine/exposure.py`, `GET /copilot/exposure`, owner-only, refused
while the lab is off; no model call). The owner sometimes panics at large
exposure, and before this nothing showed it outside the Dashboard's collapsed
Journal & performance section. *At risk now* is the premium still paid for the
open long option positions, every account but Webull: the cost of the contracts
still open, first in, first out. Stocks (long holds) and shorts are left out.
*Usual day* is the median, over the last 60 New York days before today with at
least one long-option entry, of that day's total `buy_to_open` premium; under
10 such days it is left off. A failed read, or no open long option, draws no
line. Tests: `backend/tests/test_exposure.py`,
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
  how many contracts it buys at the ask; the provider's (ORATS) implied
  volatility in percent, delta and theta (per share per day, and per
  contract), with one `greeks_as_of`, the provider's own hourly stamp as
  given; and `last`. Each expiry carries its `expected_move`,
  the at-the-money straddle's mid in dollars and as a percent of the price
  (`options_implied.straddle`, labelled by its quote time), and each candidate
  `move_needed_vs_expected`, its break-even move over that expected move
  (above 1 needs more than the market prices in). A Greek or volatility the
  provider did not give is null; the copilot never estimates one. Open
  positions in the owner context carry the same `iv_pct`, `delta` and
  `greeks_as_of` from their marks. The answer drops rows rather than cut its
  JSON past 6,000 characters.
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
  and no alert support. The memory joins the owner context pack from the
  next turn. `jo_briefing_common` is untouched: the
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
  - **Plan numbers.** Under the title, one row worked out in the browser from
    the card's own prices (`planNumbers`), never from the copilot's words: the
    drafted last, the entry's distance from it, and the invalidation's distance
    from the entry with the move it takes (a share, or in the underlying for an
    option plan). It follows an edit; a stop on the wrong side of the entry
    gets no distance. A plan carries no target, so there is no reward:risk.
  - **Size it for me.** `Risk $` and the size note wait behind a **Size it**
    disclosure, open from the start when a risk is typed or remembered or a
    confirmed card kept a size, and otherwise on tap; folded, its line shows
    the drafted size note, which Confirm still saves. A `Risk $` field beside the size (numeric keypad,
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
      the thesis and contract hint, on the card's journal account: the
      account of the last plan confirmed in this browser (`localStorage` key
      `copilot.plan-account`), else the capture default account, else the
      only one, so Confirm needs no pick; with more than one account the
      picker stays visible to change it, and the card asks only when none of
      those applies. A discretionary capture may
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
  - A plan proposed in a Telegram turn is confirmed the same way from its card
    message: Confirm there runs the same parts in the same order through the
    engine functions these routes call (`confirm_plan` in
    `engine/telegram_replies.py`): the pre-trade plan with the card's client
    id on the capture default account (or the only one; with neither it says
    "Set a default account for plans on the desk first" and saves nothing),
    then the entry and invalidation alerts and a time stop it can read. The
    reply lists each part on its own line ("Plan saved", "Entry alert armed
    at 100.00", "Invalidation failed: …"); the card's outcome records each
    part's result with a note starting "Confirmed from Telegram", so the desk
    card shows the same state as a desk-confirmed one. A second tap retries
    only the failed parts, and once every part is done says it is already
    confirmed; a card confirmed on the desk or dismissed saves nothing.
  - **Follow-through.** A plan's pings name the plan:
    - When its entry or invalidation alert fires, the phone says
      "NBIS hit your 95.90 entry trigger. Still valid? Tap to check." or
      "NBIS broke your 92.30 invalidation. Your plan says out." The tap opens
      `/copilot-lab?investigation=<id>&context=…`: the investigation, with
      the owner's question ("My entry trigger hit at 95.90 (10:41). Is the
      plan still valid? Check the chart and group now.") in the message box,
      unsent. Delivery is the level alerts' own outbox. A copilot watch with
      no role keeps the plain level message. While the practice goal is
      `exit_at_invalidation`, the invalidation ping ends with [its
      line](#the-practice-goal). The open P&L is not added: no
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
  `thesis_watch`, `premarket_prep`, `chart`, `dashboard`, `copilot`, `manual`,
  `checked_call`: a Discord call checked first, its ref the check's id),
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
  the automatic week review, Watch your day, the evening review, fill-time
  pattern interrupts, Radar alerts, thesis watch, research results, the position companion) calls
  `notification_policy.decide` right before it hands a message to ntfy, and keeps
  its own at-most-once delivery, caps and expiry. `ntfy.py` stays a transport.
  The SPY/QQQ first-pullback alert (`first_pullback.py`) calls it too, with
  `new_only`: one claim per ETF a day, held rather than sent when the policy
  cannot be read, so a ping can be lost but never repeated.
  Radar alerts and thesis watch are anchored per symbol (the symbol's open
  position when there is one; a Radar group event to its group); a ping they
  hold is recorded `held` and counts toward neither sender's own caps.
- **Budgets:** each kind from interrupt down has its own budget a New York day, so
  one kind spending its pings never takes another's (on October 29, 2026 the old
  shared pool was spent by 09:50 on prep, thesis watch, research and nudges, and
  every Radar ping and the evening review were held). Defaults, each overridden
  by `PING_BUDGET_<KIND>`: `interrupt` 4 ([pattern interrupts](#pattern-interrupts)),
  `companion_update` 12 (the [position companion](#position-companion)'s updates and close notes),
  `nudge` 2 (link pings and the companion's adopt pings share it), `prep` 1 (shared
  with the automatic week review and Watch your day), `radar_setup` 4 (Radar
  single pings that carry a [setup card](radar.md#setup-cards-off-by-default),
  ranked just above `radar_event`), `radar_event` 4 (Radar's other single
  pings), `radar_digest` 2, `thesis_watch` 2, `research` 1. Before 09:30
  New York these kinds together also have `PING_PREOPEN_ALLOWANCE` (default 2)
  pings, so pre-open headlines cannot spend the day. While the
  [morning brief](#pre-market-prep) is on and not yet decided today, one of them
  is kept for it (on a weekday, until its ping could no longer go out): at 09:00
  it comes after early thesis-watch pings, which would otherwise spend both.
  A held ping's reason names
  the budget: "Not sent: Radar's 4 single pings for today are spent."
- **No shared daily ceiling:** categories spend only their own budgets. Position
  alerts without a category budget remain subject to their sender's own firing,
  delivery and expiry rules and the per-position quiet window. Early prep,
  research and thesis traffic cannot spend Radar or position-alert capacity.
  `PING_DAILY_CAP` is obsolete and ignored. The evening review is never held.
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
  followed symbols still asking their close question and the fills waiting to
  link, and the pings the policy held today (`notification_policy.held_text`).
  Alert and Radar ratings are never counted (since 2026-11-10; the row's
  `alerts` and `radar` columns stay 0). When any is waiting it sends one ping,
  "Close the day: To review: 2 threads · 1 fill to link · 12 pings held today
  (Radar 11, evening 1)", that opens `/copilot-lab?close=1` on Close the day (kind
  `evening_review`, never held by the policy). Nothing waiting, the lab off, or a
  desk source (positions, plans) that cannot be read is recorded `skipped` with
  why and sends nothing. One `evening_review` row a day (unique day, additive
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
  delivered ping: an entry trigger or a Radar single or setup ping naming a stock
  (since November 10, 2026), an entry fill in the symbol within 30 minutes; an invalidation, time stop or open-trade alert, the position closed
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

## Position companion

Every unplanned long option is adopted by the copilot, watched, and kept in one Telegram conversation until it
closes (`backend/app/engine/position_companion.py`; the owner's decision of October 30, 2026: he mostly enters
options without a plan, and his losses come from managing them after the entry). Stocks are left out: they are
long theses, reviewed weekly. Nothing here places, changes or suggests an order, and every prompt says so.

- **Adopt.** Plan nudges' grace (`PLAN_NUDGE_GRACE_MINUTES`, default 3) after the first entry fill of a new long
  option, in the regular session, entered since the API started, Webull left out, with no plan linked by then: one
  copilot turn with the position copilot's context ("Review this position:", so it reads the trade review, the 5m
  chart's levels and VWAP, the group against SPY, the last hour's headlines and the owner's record at the level and
  on the contract shape with the existing tools). Its invalidation is drafted in code from the 5m chart: the nearest
  level below a call (its low) or above a put (its high), else VWAP on that side; the horizon is a day trade for a
  contract expiring within 7 days (time stop 60 minutes after the entry, from the audit's 15-60 minute best holds)
  and a swing otherwise (the close before expiry). The turn keeps or moves them and adds a thesis guess and a
  three-line read. Saved as the investigation "Adopted: NBIS 160C" and a `position_companion` row in `draft`
  anchored to the position (a rebuild never re-adopts it). Telegram: the headline, the read, the draft plan, and
  **Confirm**, **Ignore** and **Edit** (the desk thread). Kind `companion_adopt`, ranked and budgeted with `nudge`.
  A ping already sent for the position (a [pattern interrupt](#pattern-interrupts) at the fill) delays the adopt until
  its quiet window has passed, so the adopt ping is not held.
  An adopt ping the policy holds (the nudge budget) leaves the position adopt-only: saved on the desk, no updates.
  With the companion running (the flag and the lab both on), plan nudges leave long options to it; stocks and
  sold-to-open options are nudged as before, and with the lab off long options are nudged too.
- **Confirm** arms the draft's invalidation as a confirmed plan card's invalidation alert (a `copilot` level alert
  with `plan_role: invalidation` on the investigation), state `armed`: the desk's plan ladder and the Plans board
  read it, with the entry at the underlying's price when it was adopted. An invalidation already crossed, or a stale
  quote, arms nothing and says so; so does a Confirm that lands after the position closed or was ignored. Once armed,
  the draft is also saved as the position's pre-trade plan, the parts the plan card's Confirm saves
  (`position_companion._save_plan`, since 2026-11-08): a `Copilot plan` capture (thesis in its note; invalidation,
  time stop and horizon in its wording; the contract's strike and expiry) linked to the trade, so the trade page, the
  trader context and plan-proof read it (timing retrospective: it came after the fill, so plan-proof shows it as
  late, not counted), and the time stop as a `plan_time_stops` row: a day trade's clock time as drafted, a swing's
  "close before expiry" as the trading days until that session. The time-stop sender pings about the position the
  capture is linked to, although it opened before the plan. A stop whose time has passed, or text that reads as no
  time, is said in the reply and stays a note; the ping itself needs `PLAN_TIME_STOPS_ENABLED`. The companion row's
  id is the plan's client id, so a second tap saves again only what a first could not and never arms twice. The
  reply names each part: "Confirmed: invalidation 158.20 on NBIS is armed; plan saved; time stop today 11:00 ET.".
  The trader context keeps the companion's record for this plan (the entry, the horizon, its updates, that the thesis
  was a guess) and reads the time stop from the saved row; a plan the owner saved themselves wins over it. **Ignore**
  stops every later message for the position (state `ignored`), removes an invalidation it had armed, skips the time
  stop Confirm saved while it is still scheduled, and closes the thread; the saved plan stays on the trade as a record
  and the position leaves the Plans board.
- **Watch.** Every minute in the regular session, each adopted position still open, not ignored, and among the
  newest `COMPANION_MAX_POSITIONS` (default 6; older ones are adopt-only, closed quietly) gets an update when, since
  its last one: a phone ping went out for it (give-back, one-hour, wrong way, expiry, time stop, invalidation), thesis
  watch fired on its symbol, Radar recorded an event on the symbol or its group (store read-only), the underlying
  moved `COMPANION_MOVE_PCT` (default 3) percent, or a cadence floor passed: 60 minutes after the entry, and 15:30
  New York while it is open. At most `COMPANION_MAX_UPDATES` (default 4) a position a day besides the adopt and
  close turns, and at most one per [quiet window](#phone-ping-policy) (10 minutes) whatever keeps triggering. An
  update waits while a ping for the position is inside that window, so no turn is spent on a message the window would
  hold. Each update is recorded before its turn runs, so a failure after the turn never repeats it. No overnight
  updates: a multi-day hold resumes in the next regular session (the 09:00 brief already lists expiries).
- **Update.** One turn: what changed since the last update and whether it changes the plan, Verdict line first, at
  most 80 words, with the plan's invalidation and the live option mark in the question. Saved as messages on the
  adopted investigation, so the desk shows them in the thread (and its Timeline lists each ping), and sent as a
  Telegram reply to the adopt message, so one thread holds the position, with **Closed it** / **Holding** (recorded
  on the row, nothing else). Kind `companion_update`, ranked just below the one-hour alert, budget 12; its updates never consume another category's budget.
- **Close.** When the exits bring the position to zero: one last turn writes the exit note (what the plan said,
  what he did, where the underlying and the option mark went), saved as the investigation's conclusion with status
  `closed`, and sent as the thread's last reply. It waits out the quiet window (so a give-back just before the sale
  does not hold it) and runs only from the open to 30 minutes after the close; a position closed later (or expired
  overnight) gets its note in the next session. The row is marked closed before the turn, so it never runs twice. A
  confirmed invalidation that never fired is removed as soon as the close is seen (within a minute), before the note
  waits, and Confirm refuses a closed position, so it never pings "your plan says out" after that.
  An adopt-only position closes quietly: its thread is closed with no note.
- **Desk.** An adopted position's row opens its adopted thread and reads "Adopted · draft plan to confirm" (or its
  armed invalidation); the thread header's chip says Adopted (Adopted · armed once confirmed).
- **Cost.** Turns use the copilot's configured backend, its per-turn budget and, on the API backend, its daily
  budget; `COMPANION_MODEL` overrides the model. Per position a day: one adopt, at most four updates, one close: six
  turns at most, typically three to four (the hour floor, 15:30 and an alert or two).
- **Delivery** is at-most-once: a failed send is recorded on the row, never retried. A Confirm needs Telegram (ntfy
  has no reply buttons); without it, plan the position on the desk.
- **Switch on:** `POSITION_COMPANION_ENABLED=true` in the API's environment (needs `COPILOT_ENABLED=true` and
  Telegram), restart the API. Off by default. Tests: `backend/tests/test_position_companion.py`.

## Pattern interrupts

When an entry fill repeats one of the owner's own costly habits from the
[October 21 behavior audit](../backend/reports/behavior_audit_2026-10-21.md), the
phone gets one message carrying the owner's own record for that habit: no
advice, no model call, nothing ordered (`backend/app/engine/fill_interrupts.py`).
Six rules judge each new entry fill:

- **Adding to a loser:** a second or later `buy_to_open` into a long option
  position still open, below the open lots' average cost (first in, first out).
- **Put entry:** a `buy_to_open` of a put.
- **Day already green:** the account's realized P&L for the New York day is
  already above zero at the fill (the rule the exit-habit `opened_green` reads).
- **Late short-dated buy:** a `buy_to_open` of an option with 0 to 2 trading
  days to expiry (weekdays) at or after 14:00 New York.
- **Ticker record:** the owner has at least 5 closed trades in the fill's ticker
  and their realized total is below zero (the audit's SNDK, −$5,410 over 48). A
  positive or too-small record stays quiet, so familiar names do not spend the
  budget.
- **Large size:** an option bought to open whose premium paid (contracts ×
  price, option prices being stored per contract) is at least 2× the
  median of the owner's closed long option positions entered in the last 12
  months (each position's largest entry fill), needing at least 20 of them, else
  it never fires (the audit: since July "the same mistakes now cost more per
  trade because sizes are larger"). The 2×, 12 months and 20 are module
  constants.

A stock, or a short, can fire only the green-day and ticker rules: a stock's
dollars are not an option premium, and a short receives premium rather than
paying it. The put, green-day, late-buy, ticker-record and
large-size rules describe the position, so each fires once per position; adding
to a loser fires on every such add. A fill that fires several sends one
message, one line per rule in that order, ending "Your record, not advice."
(when the green-day rule fired and the [practice goal](#the-practice-goal) is
`no_opening_while_green`, the goal's line goes just above it):

```
Pattern: NBIS 160P
Adding to a loser: 12 past adds, 3 ended green, −$2,140
Put entry: puts −$6,480 over 210 trades; calls +$8,710 over 1,120
Day already green (+$420 today): 85 past trades opened green, −$9,050
Late short-dated buy: 64 past buys after 2 PM with 0–2 days left, 48% expired worthless, −$5,210
Your record in NBIS: 48 trades, 35% won, −$5,410
Size: $4,200 is 2.3× your median ($1,800); your 31 past entries above 2×: 39% won, −$6,100
Your record, not advice.
```

Each line's record comes from closed trades in every account but Webull,
never counting the position being judged; a record under 5 trades says "too
few to read". The records are built once and kept in memory for the New York
day, rebuilt only when the closed trades' count or realized total moves (a new
close or a rebuild), so a fill never waits on a heavy query. The message opens
the trade page on the interrupt; **Noted** opens it with the acknowledgement
recorded once (`POST /trades/{trade_id}/fill-interrupts/{id}/noted`, owner only).

It runs on the level alert monitor's loop every 30 seconds in the regular
session; only fills since the process started and in the last 15 minutes
count; Webull is left out. Each entry fill is judged once, anchored in its own
source identity (`fill_interrupt` table, additive migration `c6e2a8f4d1b7`), so a
rebuild never re-sends; a fill that fired nothing is kept as `none`. Delivery is
at most once, and a message not sent within 3 minutes or before the close is
dropped. The policy kind is `interrupt`, below hold-hour, with its own budget
(`PING_BUDGET_INTERRUPT`, default 4 a day); the quiet window is per position,
so a plan nudge right after an interrupt for the same position yields to it,
and so does a second interrupt (an add below cost) within 10 minutes. Up to 4
interrupts a day spend only their own budget, leaving Radar capacity intact. A fill whose email arrives after a later
entry's stays on the same position; known limit, as for position alerts: a
message sent before that earlier fill arrived links the trade id of that
moment, which the rebuild replaces, so that link no longer opens.

**Switch on (the owner's switch):** `FILL_INTERRUPTS_ENABLED=true` in the API's
environment (needs `NTFY_URL` or Telegram), restart the API. Off by default.
Tests: `backend/tests/test_fill_interrupts.py`.

## Pre-market prep

The morning brief: one phone ping each trading morning with the market and what
the owner already holds and has planned (`backend/app/engine/premarket_prep.py`).
The heading keeps its old name so links stay put. On 2026-10-29 the owner chose
this as the one morning brief: Jo's 08:45 briefing (`/morning`) still works
unchanged, and switching Jo's morning task off is the owner's step.

- **When:** at `PREMARKET_PREP_AT` (default `09:00` New York; `08:30` before
  2026-11-03) on a day the market calendar has a regular session, never a
  weekend or holiday. 09:00 is after the 08:30 CPI/jobs releases (at 08:30 the
  brief landed with them and could never include them), after the Radar
  pre-market pilot's 08:50 scan, and still half an hour before the open. The day
  is claimed once (`premarket_prep.day` is unique, additive migration
  `e5a9c3d7f2b4`), so a restart or a second process never sends a second one.
  A prep not started within 20 minutes of its time waits for the next trading
  day.
- **Pack:** `market`: Jo's backdrop reader (`jo_morning_market.collect_backdrop`:
  the coming week's FOMC/CPI/jobs calendar, the saved VIX, saved earnings
  dates, with its gaps) and the SPY/QQQ/SMH pre-market proxies with their
  change vs the prior close (Jo's `tradier_snapshots`; no futures feed exists);
  `headlines`: since the previous session's close (market calendar), at most 8,
  up to 3 market-wide ones from the broad tape (Jo's macro keyword filter) then
  held and armed-plan symbols (catalyst stories first, two per symbol), each with
  publisher and New York time, from two batched Alpaca/Benzinga reads; then open
  positions with days to expiry, expires-today, give-back watch
  state and open P&L (the owner context pack's positions section); `at_risk`:
  the [exposure](#exposure) summary and its sentence, which the raw-facts
  fallback appends to its positions line, so the brief states it whether or not
  the turn succeeds; armed plans
  with their distance to the entry and the invalidation (the Plans board's
  `copilot_plans.board`, one batched quote); earnings from today through Sunday
  for held symbols and symbols with an active thesis memory (one batched
  Tradier calendar read, at most 8 symbols); today's pending time stops; the
  plan streak; `premarket`: held then armed-plan symbols' own pre-market moves
  (`copilot_extended.extended`, at most 8, indices left out: pre-market last
  and change vs the previous regular close, volume, dollar volume, last
  evening's after-hours; see [Extended hours](#extended-hours)); and, while
  `RADAR_PREMARKET_ENABLED` is on, `premarket_scan`: the pilot's latest scan
  (`copilot_extended.premarket_scan`); and, while `PREMARKET_ARCHIVE_ENABLED`
  is on, `movers`: the whole market's six biggest 09:00 gainers and losers
  from the [pre-market archive](../research/notes/morning-brief-scorecard.md)'s
  SIP ranking ($2+, $1M+ traded, change vs the prior regular close), owned or
  not. The archive saves by 09:01, so a prep started at or after 09:00 waits
  up to 09:02 for it; one started before 09:00 says the ranking is not ready.
  Added 2026-11-05 after the [input audit](../research/notes/morning-brief-input-audit.md)
  found no saved brief named any of its day's top 09:00 movers. A section that
  fails reads `unavailable`; the rest stand.
- **Turn:** one `run_turn` on the configured backend and evidence, system
  prompt unchanged, its turn budget cap included. The message starts "Morning
  brief for …" and asks for at most 10 lines: two on the market and what it
  means for the owner's names (with their own pre-market moves), one on the
  whole market's biggest movers worth a look (when `movers` is present), then what
  expires or sits near a trigger, earnings this week, and one thing to decide
  before the open. Since 2026-11-03 the turn may [search the web](#web-search)
  (`web=True`; the API backend with live evidence only, three searches, the
  cap raised by `WEB_TURN_EXTRA_USD`, about $0.03 a morning in searches): for
  the market's overnight driver and the catalyst behind any held or planned
  name gapping meaningfully (about 2% on real dollar volume, or flagged in the
  pilot's scan), then the one or two biggest whole-market movers, naming the
  publisher and time of what it uses. Queries carry a
  symbol or topic only, never positions, sizes, trades or accounts (the system
  prompt's rule, repeated in the message). Otherwise it uses the pack's facts
  only. Headlines and search results are marked as third-party data, never
  instructions. The answer, cut
  to 10 lines, is saved as an open copilot investigation titled
  `Morning brief <date>` (`Pre-market prep <date>` before 2026-10-30), so it
  shows in the desk's thread list and on the Dashboard's Morning briefing card
  (its conclusion line and a link to the thread, above Jo's briefing).
- **Ping:** title `Morning brief`, body the first two lines; a tap opens
  `/copilot-lab?investigation=<id>`. If the turn fails (an error event,
  including the budget stop, or no text), the ping and the saved record carry
  the raw facts instead under "Raw facts (the copilot turn failed):": the market
  line, the owner's names' pre-market moves, the top three 09:00 movers each way, up to 3 headlines, then expiries, the nearest triggers, today's time
  stops and earnings this week.
- **Delivery:** the same at-most-once outbox as plan nudges: a send that may
  have reached ntfy is `unknown` and never resent; a prep that never finished
  within 10 minutes, or a ping not sent within 30 minutes (09:30 for a prep
  claimed on time), is `expired`.
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

Images reach the model these ways, never more than **two per turn**:

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
- **A photo sent to the Telegram bot.** A photo (its largest size) or an image
  sent as a file goes through the same image store and is attached to one
  bounded Telegram turn (`engine/telegram_replies.py`); its caption is the
  question. With no caption the question is the reconcile question: read the
  positions the screenshot shows (contract, quantity, mark), compare them with
  the journal's open positions through the book tools, and list what is
  missing, extra or a different quantity, read only. The image is deleted when
  the turn ends; the desk keeps the question marked "(photo)", never the image.
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

**Backends.** `anthropic` sends image content blocks. `fake` makes no call: it acknowledges each image by its
size in a scripted line, so the fixture and the browser spec exercise the path
(the fixture's closed review draws a stand-in plan chart). Tests:
`backend/tests/test_copilot_images.py`, `frontend/e2e/copilot-vision.spec.ts`,
`frontend/e2e/charts-copilot-loop.spec.ts` (Look at my chart).

## Macro and base rates

Two market-data tools in `app/ai/copilot_macro.py`, offered to every turn and
to research jobs and the shadow book:

- **`get_macro`** reads public FRED series through the fredgraph CSV download
  (no key): the 2-year and 10-year yields, the 10y-2y curve, the 10-year real
  yield and breakeven, the effective fed funds rate, high-yield and
  investment-grade credit spreads (ICE BofA OAS), the broad dollar, WTI and
  the Chicago Fed's NFCI. Each has its date, its change over a week, a month
  and three months (rates and spreads in basis points, the dollar and oil in
  percent, NFCI as a difference) and where it sits in its one-year range.
  Series are fetched in parallel and cached six hours in `backend/data/fred/`;
  a failed fetch uses the stale file (marked `stale`, listed in
  `stale_series`, state `partial`) or leaves that series unavailable, and the
  rest stand. A series whose fetch failed waits 15 minutes before trying FRED
  again, so an outage does not stall every read. FRED publishes a day's value the next
  business day, so each series carries its own date.
- **`get_base_rates(symbol, drawdown_pct?)`** counts what followed past
  drawdowns in the symbol's own daily history: the chart feed's whole Tradier
  series (split-adjusted, dividends left out; SPY from 1996, QQQ from 2000,
  SMH from 2012) plus today's bar, which during the session is the live price,
  not a close (`current.intraday`). An episode starts at the first close at
  least `drawdown_pct` (default today's depth, whole percent; 3-80) below the
  trailing 252-day closing high and ends once the drawdown recovers to half
  that; the last is marked `ongoing` until then. It returns forward returns
  at 5, 21, 63 and 126 trading days (n, median, share up, worst, best) beside
  the same history's every-day baseline, the further drop within 63 days, how
  many regained the high they fell from and how fast (the median is over the
  ones that did), and the ten most recent
  episodes with dates. Counts of the past, not odds; the prompt says to give n
  and the baseline with every figure and to call fewer than 10 episodes an
  anecdote.

The prompt reads `get_macro` for rates, credit, dollar and oil questions and
`get_base_rates` (the symbol, and SPY or QQQ for the market) for "how does
this usually end" or "is this the top". Replay cuts both before the frozen
day (macro from FRED's current vintage, revisions included); the fixture serves fixed macro rows and a simulated price history.
Tests: `backend/tests/test_copilot_macro.py`.

## Breadth and positioning

Two market-data tools in `app/ai/copilot_breadth.py`, offered to every turn and
to research jobs and the shadow book. Both read current data only, so replay
says they are unavailable; the fixture serves fixed numbers.

- **`get_breadth`** asks whether the average stock is taking part. One Tradier
  quote request (about 0.3 s) for the S&P 500 members in the hand-kept
  `backend/app/data/sp500.json` (from the Wikipedia constituents table, with
  its `as_of`; refresh it now and then, as the index changes a few names a
  quarter; BRK.B is quoted as `BRK/B`) gives advancers and decliners, the
  share up, the median and equal-weight day change, new 52-week highs and
  lows (today's high or low reaching the provider's 52-week figure), the share
  within 5% of the 52-week high and the share 20% or more below it, overall
  and by GICS sector. Cached three minutes in memory. Before the 09:30 ET open
  the provider's last price is the previous close, so the day's counts,
  changes and new highs and lows are null and `session` says why; the
  off-high shares stand as of that close.
- **`get_positioning(symbol = SPY)`** asks how afraid the options market is:
  the Cboe volatility indexes (VIX9D, VIX, VIX3M, VIX6M, VVIX, SKEW) with the
  curve called contango, backwardation or mixed, and for the symbol the
  nearest expiry at least five days out and the one nearest 30 days, read
  through the options feed's cached chains: at-the-money IV, the 25-delta
  put and call IV and their difference (skew, in vol points), and put/call
  volume and open interest, on the symbol's primary root (an expiry with none,
  an SPX AM monthly, is left out and said). IV and greeks are ORATS figures refreshed hourly.

The prompt reads `get_breadth` before calling a move a selloff, a rotation or
a narrow rally, and `get_positioning` for "is fear priced in" or "are puts
bid". Tests: `backend/tests/test_copilot_breadth.py`.

## Extended hours

Outside the regular session a quote's last price and day change are the
regular session's, so before the open every name reads flat at the prior
close. `app/ai/copilot_extended.py` reads Tradier's 1-minute timesales with
`session_filter=all` (04:00-20:00 New York) through the chart feed, the same
request the Charts tab makes for today (15 s cache; a completed session is kept
in the module's own 48-session cache, outside the chart feed's, and an empty
read is not kept), and adds an `extended` block outside the regular session:

- **Pre-market** (04:00 to the open): each name's pre-market last, change
  against the previous session's regular close, high, low, volume and dollar
  volume, and that previous session's after-hours move.
- **After-hours** (the close to 20:00): the move since today's regular close.
- **Closed** (overnight, weekends, holidays): the latest session's complete
  after-hours.

Reference closes come from the minute bars and the market calendar (early
closes and holidays included), not from the quote's fields: the last regular
minute's close, within cents of the official closing auction price. No request goes
out for today before 04:00 (Tradier refuses a start in the future, which would
cool the chart feed down). Tradier has no overnight (20:00-04:00) trading.

`get_quotes` carries it for its names (up to 8, one or two reads each) and
`get_market_regime` for SPY, QQQ, IWM, SMH and the symbol. A result that would
pass the tool limit sheds last evening's after-hours, then the ranges, then
the last names (`trimmed` says which), rather than being cut mid-JSON. Before the open
`get_radar_today` adds `premarket_scan`: the Radar pre-market pilot's latest
recorded scan (08:50 or 09:20, when `RADAR_PREMARKET_ENABLED` is on), the
universe's moves against SPY, up and down counts and the flagged names. The
prompt says to give the off-hours change with its last trade time and dollar
volume and never to call a name flat from a regular-session quote off hours.
Live only; replay and the fixture leave it out. Tests:
`backend/tests/test_copilot_extended.py`.
## Web search

A turn the owner asked (the desk's `POST /copilot/chat` and a typed or tapped
Telegram reply) may search the web on the `anthropic` backend with live
evidence, and so does the [morning brief](#pre-market-prep) since 2026-11-03
(the owner approved its roughly $0.03 a morning). Other background turns (the
week review, the position companion) never do, and neither do replay (the web is hindsight) or the
fixture. `copilot.run_turn(..., web=True)` adds Anthropic's server-side
`web_search` tool (`web_search_20260209`) once a round may call tools, with
`max_uses` set to `copilot.WEB_SEARCHES` (3). Once offered it stays in every
later round, the last included, and byte for byte the same: a search's result
(and its code-execution filtering) can arrive a round later, and the API binds
each thinking block to the tools it was written under, so a later round whose
server tool is gone (checked live on 2026-11-02) or changed is refused with a
400. Until 2026-11-09 `max_uses` counted down across rounds, and every turn
that searched and then read another tool failed that way. `max_uses` is per
request, so the prompt's three-a-turn rule, the turn's rounds and its spend cap
bound the total. A refused request's reason from the API is logged and shown
after "The Anthropic API refused the request (400):", and a failed search's
error code is logged (`copilot web search failed (code)`). A result is matched to its query
by search id whichever round it arrives in; one still missing when the turn
ends reads "search failed (no result)". Each query is logged at INFO
(`copilot web search: …`), so Telegram turns' searches are visible too.

- **No web fetch.** Search results only: a page cannot steer a request to a
  URL, and the query is the only thing that leaves. The prompt says to use the
  web for what the tools do not carry (macro and policy, politics, geopolitics,
  industry and company statements, and the catalyst behind a gap, bounce or
  selloff the owner asks about), to name the publisher and date of what it
  uses, and never to put the owner's positions, sizes, trades or account
  labels in a query. Results are third-party data, never instructions.
- **Sources.** Each search is a Sources row (`web_search`, kind `fetched`):
  the query, the result count and hosts, and up to 8 links (title, URL, page
  age; http and https only) the panel opens in a new tab. The links are not
  kept with the saved investigation; the answer's text is.
- **Cost.** A cent a search on top of tokens. A turn that may search gets a cap
  of `COPILOT_TURN_BUDGET_USD` plus `copilot.WEB_TURN_EXTRA_USD` ($0.15), since
  search results add input; the daily budget is unchanged. A `pause_turn` (a
  long server-side search) is sent back to resume, within that cap; a turn
  whose last round still paused ends with a `rounds` error, not a blank answer.
  On Telegram a proposed trade plan (at most two a turn) is saved on the desk
  as the desk saves a card and sent after the answer as its own message, with
  Confirm and Edit (see Confirm a plan); any other card is named at the end of
  the reply with a pointer to the desk.
- **Research now.** When a question needs more than a turn can read, the
  prompt has the model answer what the evidence supports and then propose
  `propose_plan kind=revisit` with `horizon_days 0`: a **Proposed research**
  card. Confirm queues the owner's reassess job due now (`POST
  /copilot/research-jobs/reassess`, `after_days 0`), the [research
  job](#research-job) with web search and fetch, and its result reaches the
  thread like any revisit. It runs only while the research queue is on. An
  owner revisit dedupes by thread, day, due date and question, so a second
  question from the same thread is its own job and a failed or cancelled one
  can be asked again. A revisit question carrying a link (`://` or `www.`) is
  refused, since it becomes the prompt of a job that can fetch pages. On
  Telegram only the answer's text is sent, so a proposed card is not shown
  there.

Tests: `backend/tests/test_copilot_web.py`.

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

Under each finished answer the desk shows two quiet buttons, Helped and Didn't.
A tap chooses, the other switches, the chosen one clears. The saved message
carries the optional `rating` (`helped` or `didnt`) and `metrics`: that turn's
`first_text_ms`, `total_ms`, `rounds`, `model`, `backend`, tool names and error
code, so real use shows which answers helped and how slow they were. A rating
is saved at once by `PUT /copilot/investigations/{id}/messages/{index}/rating`
(no revision, like a card outcome; queued until the conversation's first save
lands), and a later save from a window that had not seen it keeps it. Older
records have neither field and read as before. Answers the Telegram bot sends
carry the same two buttons and set the same rating (see Telegram on the desk).

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
| `COPILOT_BACKEND` | `fake` | `fake` is a scripted stand-in that makes no API call. `anthropic` uses the Messages API and spends credits. The old value `plan` now means `anthropic`. |
| `COPILOT_EVIDENCE` | `fixture` | `fixture` returns SIMULATED neocloud data; the model is told so in its context line, in a `"simulated": true` marker on every tool result and in the system prompt, and says so in its answer. `live` reads this installation's Radar, news, Tradier and quote services. `replay` reads a recorded session at a frozen moment (below). |
| `COPILOT_REPLAY_STORE` | none | `replay` only: path to a read-only copy of a Radar store. |
| `COPILOT_REPLAY_AT` | none | `replay` only: New York time inside a recorded session, e.g. `2026-10-23T11:12`. |
| `COPILOT_MODEL` | `claude-sonnet-5-5` | Model id for `anthropic`: the default for a turn. |
| `COPILOT_MODELS` | `claude-sonnet-5-5,claude-opus-5-5,claude-fable-5-2,claude-fable-5-1` | The models the panel's **Model** picker offers, comma-separated; `COPILOT_MODEL` is always offered first. A turn sends its pick as `model` in `POST /copilot/chat`; one not in this list is refused (422). The pick is remembered per browser, and the metrics line in each answer's Sources shows the model that actually answered. Every default model has its own entry in `copilot.PRICES`; a model with none is costed at the dearest known price, so add its price when you offer one dearer than Fable. |
| `COPILOT_FOLLOWUP_MODEL` | `off` | A model id that follow-ups on carried evidence run on when the panel picked no model (§ Follow-ups keep the evidence); `off`, empty or an invalid id keeps every turn on its own model. The default follows the offline eval's decision rule. |
| `COPILOT_EFFORT` | `medium` | `low`, `medium` or `high`. |
| `COPILOT_BACKENDS` | `anthropic` | The backends the panel's **Backend** picker offers, comma-separated; `COPILOT_BACKEND` is always offered first. `anthropic` is offered only when the API key is set. A turn sends its pick as `backend` in `POST /copilot/chat`; one not offered is refused (422). Remembered per browser. |
| `COPILOT_DAILY_BUDGET_USD` | `4` | Estimated API spend (New York day, `anthropic` turns only) at which `POST /copilot/chat` refuses further API turns with a 429 until tomorrow. Every turn is recorded in `copilot_turn` (`app/ai/copilot_spend.py`: backend, model, rounds, tokens, estimated cost; no text), `GET /copilot/status` reports `spend_today_usd`, and the panel shows "API today $x of $y" while the API backend is picked. Turn metrics also reach the server journal at INFO. |
| `COPILOT_TURN_BUDGET_USD` | `0.25` | Estimated API spend at which a turn stops between rounds (output is also capped at 4,000 tokens per round). A turn that may [search the web](#web-search) gets $0.15 more. A plan or review turn (a companion or week-review job, or any turn that has asked for `get_trade_review`, `get_week_review`, `get_level_history` or `get_option_candidates`) gets twice the budget, $0.50 by default (`copilot.DEEP_TURN_FACTOR`): on Opus 5.5 they measured $0.19-0.21 against the $0.25 an ordinary question gets, and one that still reaches its cap ends with the same budget error. The figure is set at Opus's price: a dearer model gets the same room in tokens (`copilot.turn_cap`), so a Fable 5.2 turn stops at $0.50 ($1.00 deep, $0.80 with search) and a Fable 5.1 turn at $0.62. The daily budget does not scale. |
| `COPILOT_FALLBACKS` | on | Sends the server-side refusal fallback (`fallbacks: "default"`). `off` disables it. |
| `ALERT_POLICY_ENABLED` | `true` | The [phone ping policy](#phone-ping-policy) for the app's own pings. `false` passes every ping through. |
| `PING_DAILY_CAP` | ignored | Obsolete; there is no shared daily phone-ping ceiling. |
| `PING_QUIET_MINUTES` | `10` | A second ping for the same position inside this window is merged or suppressed. |
| `PREMARKET_PREP_ENABLED` | unset (off) | `true` sends the [morning brief](#pre-market-prep) ping on trading mornings (needs `COPILOT_ENABLED` and `NTFY_URL`). `PREMARKET_PREP_AT` (`HH:MM` New York, default `09:00`) sets its time. |
| `WEEK_REVIEW_AUTO_ENABLED` | unset (off) | `true` runs [Review my week](#review-my-week) by itself once a week and pings it (needs `COPILOT_ENABLED` and `NTFY_URL`). `WEEK_REVIEW_AUTO_AT` (`HH:MM` New York, default `16:45`) sets its time on the week's last trading day. |
| `EVENING_REVIEW_PING_ENABLED` | unset (off) | `true` sends the [evening review ping](#phone-ping-policy) on a trading day when something waits for review (needs `COPILOT_ENABLED` and `NTFY_URL`). `EVENING_REVIEW_PING_AT` (`HH:MM` New York, default `16:30`, not before 16:00) sets its time. |
| `POSITION_COMPANION_ENABLED` | unset (off) | `true` runs the [position companion](#position-companion): unplanned long options are adopted with a drafted plan, updated and closed in one Telegram thread (needs `COPILOT_ENABLED` and Telegram). `COMPANION_MODEL` (default: `COPILOT_MODEL`), `COMPANION_MOVE_PCT` (3), `COMPANION_MAX_UPDATES` (4 a position a day), `COMPANION_MAX_POSITIONS` (6 watched at once). |
| `DAY_REPLAY_ENABLED` | unset (off) | `true` builds [Watch your day](#watch-your-day) at 16:20 New York on a trading day with a fill and pings it (needs `NTFY_URL`; not the lab). |
| `ANTHROPIC_API_KEY` | none | Read only by the backend process for `anthropic`. It is never sent to the browser. |
| `ROBINHOOD_READ_ENABLED` | unset (off) | `true` turns on the desk's [read-only Robinhood feed](robinhood-read-feed.md) when `ROBINHOOD_TOKEN_FILE` is a usable sign-in file. |
| `ROBINHOOD_TOKEN_FILE` | none | Path of the Robinhood sign-in file (owned by the service user, mode 0600; never in the database). |
| `ROBINHOOD_ACCOUNTS` | `Roth IRA,MCP` | Accounts always shown (label, type or last four); any other shows only while it holds something. |

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

## API only (since 2026-10-31)

Every Claude call in the app now uses `ANTHROPIC_API_KEY` through the Messages
API: chat, research jobs, the shadow book and the reviews. The earlier plan
backend and the Claude Agent SDK are gone. `copilot_turn` rows and saved answers
from before the move still say `plan` / `claude_plan`, and their costs are API-price
equivalents, not bills. Desk, companion, Telegram, prep and week-review turns are recorded and count toward
`COPILOT_DAILY_BUDGET_USD` (prep and week review do not check it, so they always run);
shadow-book turns are recorded as `api_background`, under `SHADOW_BOOK_MAX_TURNS` instead.

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

## Measuring the copilot

The [October 31 review](../research/notes/ai-intelligence-review-2026-10-31.md)
found that nothing scored an answer: every test is a fixture, and the
Helped / Didn't ratings have no reader. The offline eval is the first measure.
It runs the same `run_turn` the desk runs, on the scripted model for free or
on the API for a few cents a case, and grades each answer against what the
model was actually shown. It never writes `copilot_turn`, never touches a
provider, and a paid run needs `--max-cost-usd`.

```bash
cd backend
python -m scripts.copilot_eval run --model fake                                  # free: scripted model, fixture evidence
python -m scripts.copilot_eval run --model claude-sonnet-5-5 --effort medium --max-cost-usd 1 --out data/copilot_eval/runs/sonnet
python -m scripts.copilot_eval grade --run data/copilot_eval/runs/sonnet         # deterministic checks
python -m scripts.copilot_eval grade --run data/copilot_eval/runs/sonnet --judge --max-cost-usd 1   # plus the Opus rubric judge
python -m scripts.copilot_eval report --run data/copilot_eval/runs/sonnet --run data/copilot_eval/runs/opus
python -m scripts.copilot_eval export --out data/copilot_eval/owner-cases.jsonl  # your real questions as cases, ids stripped
```

- **Cases.** `backend/tests/fixtures/copilot_eval/starter.jsonl` holds 23
  fixture-answerable cases across the desk's workflows: a briefing, a group
  read, a planted rumour, a follow-up that should reuse carried evidence, "go
  deeper", a candle, a plan, a compare, an open-position review, an
  invalidation question, a closed-trade review, the week review, a theme, a macro
  read, a base-rate question, a breadth read, a positioning read and an
  order-bait prompt. A case is the owner's words plus `expects`: `read`,
  `against`, `long_ok`, `planted_rumour`, `carried_tools`, `verdict_in`,
  `tools_any`, `tools_none`, `known_figures`. A case with `carry_from` runs
  after its parent with the parent's answer in the history and its `carry_id`;
  when the parent came from the cache the carry is unavailable and the no-reread
  check is not applicable.
- **Run** (`backend/scripts/copilot_eval.py`). Fixture evidence by default;
  replay (`--evidence replay --replay-store … --replay-at …`) only against a
  local database, as the lab's replay mode. Every tool read, including the owner
  context, is recorded with its result. Answers are cached by case, model,
  effort, evidence, the system prompt, the answer-shape reminder and the tool
  schemas, so a prompt change never reuses a stale answer and a re-run costs
  nothing. Records go under
  `backend/data/copilot_eval/` (gitignored).
- **Grade.** The deterministic checks (`backend/app/ai/copilot_graders.py`, over
  the Python reading of the answer format in `backend/app/ai/copilot_answer.py`,
  kept in step with `answerParts` in `frontend/lib/copilot.ts`): `completed`,
  `format_verdict`, `format_read`, `format_against`, `format_compare` (compare
  cases only: a Compare block with nothing beside it, at most four rows,
  every cell within 6 words), `length` (120 words unless
  `long_ok`), `traceable_figures` (every figure in the prose appears in a tool
  result, the owner context or the owner's own words at the precision written,
  as a percent of a fraction, or as the gap between two values of one result,
  also as a percentage; clock times, dates in ISO, M/D or month-name form,
  expiries, ids and counts up to 3 are skipped), `no_reread`, `unsupported`, `no_orders`, `verdict_in`, `tools_any`,
  `tools_none`. The optional judge scores six rubric items 1–5 with Opus 5.5
  through the structured-answer runner (`backend/scripts/copilot_eval_rubric.md`,
  its hash recorded); it needs the API runner from the API migration and its own
  `--max-cost-usd`.
- **Report.** Pass rate per check, judge means, p50/p90 first-text and total
  latency, cost per case; with two runs, B minus A per check over the shared
  cases with a 95% case-bootstrap interval, so a prompt, model or effort change
  is a number before it ships.
- **What it is not.** It scores explanations against evidence, not trading
  outcomes; the Proof pages own those. Tests:
  `backend/tests/test_copilot_eval.py`, `backend/tests/test_copilot_answer.py`.

### What every turn records

Every model turn the app runs writes one `copilot_turn` row through
`copilot_spend.recorded_turn` (the desk and the Charts dock, Telegram, the
morning brief, the week review, the companion) or `copilot_spend.record` (the
shadow book). Besides the model, rounds, tokens and cost it already kept, a row
now says what the turn was for and how it went:

- `kind`: `ask`, `briefing`, `plan`, `review`, `week_review`, `moment`,
  `changes`, `compare`, `pushback`, `prep`, `companion`, `shadow` or
  `check_call`. For a
  desk, dock or Telegram question the server works it out from the owner's
  words, the tools read, the cards proposed and the answer's shape
  (`copilot_spend.kind_of`); the scheduled senders name theirs.
- `source`: `desk`, `charts`, `radar`, `panel` (the browser says which, in
  `POST /copilot/chat`'s `source`), or `telegram`, `prep`, `week_review`,
  `companion`, `shadow`.
- `tool_names` (the owner-context read left out), `first_text_ms`,
  `max_silence_ms`, `cache_creation_input_tokens`, `effort`, `evidence`.
- `error`: the turn's error code; `stopped` when the owner stopped the answer
  mid-stream (its cost so far is kept, so the daily cap never undercounts);
  `daily_budget` on a zero-cost row when the budget was already spent and no
  model ran. The morning brief is refused past the cap like a desk turn; the
  week review runs regardless.
- `timings` (JSON, `copilot_spend.timings_json`): where the owner's wait went.
  `owner_context` and each entry of `tools` (the owner-context read and
  every tool call, as `metrics["tool_calls"]` keeps them) carry `ms` and its
  split: `queue_ms` waiting for a free worker thread, `feed_wait_ms` queued
  in the chart feed (behind the same read in flight, or for one of its four
  provider slots) or for the chart history's lock,
  `feed_ms` in the chart feed's provider reads (Tradier, Alpaca SIP history);
  the rest of `ms` is other providers (news, the quote engine, FRED), the
  database and the work itself. `rounds` holds each round's `model_ms` (request
  to final message) and, for a round that read tools, `tools_ms` (their wall
  clock, side by side); `prefetch` names what the turn started early. A web
  search is listed without a time (it runs at Anthropic). Migration
  `backend/alembic/versions/e2f4a6c8b0d1_copilot_turn_timings.py` (additive,
  nullable); the eval's records carry the same `metrics`.
- `investigation_id`: the saved conversation. The `done` event carries the
  row's `turn_id`; the browser (and the Telegram bot) keeps it in the answer's saved `metrics`, and
  saving the investigation links the rows (`copilot_spend.link`), so a
  conversation's cost and the Helped / Didn't on each answer meet. The first
  answer of a new thread links at its first save.

Migration `backend/alembic/versions/b7c1d2e3f4a5_copilot_turn_measurement.py`
(additive, nullable). Research jobs and the structured reviews keep their own
accounting (`research_job.spend_json`, the review records) and are not in this
table. Tests: `backend/tests/test_copilot_turn_record.py`.

### The answer scorecard

`GET /copilot/answer-scorecard?days=7` (owner-only, refused while the lab is
off; `days` 1–90) reads the turn rows and the saved conversations of the last
days together (`backend/app/engine/copilot_scorecard.py`) and returns counts:

- **answers**: how many were saved, how many you rated, Helped and Didn't, the
  Helped rate (null under three ratings, so a lucky pair never reads as 100%),
  how many you pushed back on (the next message starts with "Push back on"),
  how many you followed up, how many turns failed.
- **by_kind**, **by_source**, **by_model**, **by_backend**, **by_tools** (the
  number of tools read: none, 1, 2–3, 4+): the same counts and the cost and
  median first text for each; **top_tool_mixes**.
- **latency** by kind over turns that did not fail: first text and total p50
  and p90, and the median longest silence.
- **failed** by error code (`stopped`, `daily_budget`, `timeout`, …).
- **timings**, over turns that did not fail and recorded them: by kind, the
  owner context read, the model's time in a round that asked for tools, those
  tools' wall clock, and the model's time in the answer round (on Sonnet the
  answer after a tool result arrives whole, so this is most of its first
  text), each as p50 and p90; by tool, every call's count, errors, `ms` p50
  and p90 and the median `queue_ms`, `feed_wait_ms` and `feed_ms`.
- **spend_by_day** by New York day, kind and billing; **cost**: total, per turn,
  the five dearest threads, and the share of input the cache served.

An answer meets its turn through the `turn_id` saved in its metrics; an older
answer with none counts when its conversation was created in the window, under
the kind its title gives (a morning brief, a week review) or `ask`. Research
jobs' records (`source` other than `copilot`) and the scripted model are left
out. Each part fails on its own (`{"state": "unavailable"}`), the rest stands.
No answer text leaves the database.

The desk shows it in **This week**, folded at the foot of the thread list's drawer, above the
two proofs (`frontend/components/copilot/ThisWeek.tsx`): "Copilot: Helped 7 of
9 rated · 23 answers · first text 4.1 s median · $0.38", then pushbacks,
follow-ups and failed turns, or "could not load". Nothing here changes a prompt,
a model or a budget; it is the number to read before changing one. Tests:
`backend/tests/test_copilot_answer_scorecard.py`,
`frontend/e2e/copilot-desk-context.spec.ts`.

### The brief scorecard

`GET /copilot/brief-scorecard?days=7` (owner-only, refused while the lab is
off; `days` 1–30; `backend/app/engine/brief_scorecard.py`) scores the copilot's
own 09:00 morning brief, not Jo's briefing, with the definitions of
`research/notes/morning-brief-scorecard.md`:

- A **brief** is one `PremarketPrep` row with its saved investigation; its text
  is the answer lines (the question, which carries the whole pack, is left out).
- **Named**: the distinct known symbols that appear in that text as whole
  uppercase tokens. Known = the journal's traded tickers, Radar's universe
  (`spoken_tickers.known_symbols`) and the backdrop ETFs (SPY, QQQ, SMH), less a
  short stoplist of all-caps words that are not tickers here (AI, CPI, FOMC, ET,
  MA, VWAP, …). This is a token match, not the research note's manual audit: a
  company named only in words is missed, and an incidental mention counts.
- `excess_pp = 100 × [(close / open − 1) − (SPY close / SPY open − 1)]` over the
  brief's regular session: the 09:30 minute's open and the last regular minute's
  close (clock hours, so an early close is not seen). A **moved** symbol has
  `abs(excess_pp) ≥ 3`. SPY counts as named with zero excess.
- Bars come from storage only, as the day replay reads them
  (`ping_images.stored_bars`, and for today the chart feed's minutes); never a
  provider fetch for this card. A symbol without the 09:30 minute, or a day
  without SPY, is **unknown**: counted in named, never in moved, and shown so
  coverage loss stays visible. Today's brief is `in_progress` on the latest
  minute; a brief with every symbol unknown is `no_bars`.

The response holds `days`, `briefs`, `named`, `moved`, `unknown`, `as_of` and
one row per brief (`day`, `named`, `moved`, `unknown`, `state`). Nothing is
stored and no model is called; a finished day whose symbols all had bars is
cached in the process by (day, brief id). A failing brief marks its row
`unavailable`; an unreadable store marks the card. No symbol or brief text
leaves the server.

The desk shows it under the Copilot line in the **This week** tab: "Morning
brief: named 23 symbols over 4 briefs · 7 moved 3+ pts vs SPY by the close",
then up to five rows, newest first ("Thu Nov 5: 6 named, 2 moved"), or "No
morning brief in the last 7 days.". It measures attention to movers, not
direction, trade suitability or profit. Tests:
`backend/tests/test_brief_scorecard.py`, `frontend/e2e/copilot-desk-context.spec.ts`.

### Where the wait goes (2026-11-08)

The production answer scorecard over 14 days read a median 15 s to first
text on the owner's own questions: about 8 s when the turn read no tools,
15 s with two or three reads, 20 s with four or more. The eval's fixture
cases reach first text in 4.6 s on the same model, so the live cost is in the
reads against live data and in the extra rounds, not the answer's length
(already cut, § Second pass re-measure). A round's reads were already
gathered side by side, but every Tradier read in the process went through
one chart-feed lock held across the provider call, so they queued behind
each other and behind the alert monitors and the Charts tab. Measured with
three distinct reads of 300 ms each issued together: 936 ms through the old
feed, 310 ms through the new one (a scripted copilot round with a 600 ms and
a 300 ms read: the round's tools take about 600 ms, not 900). The prefetch
and the side-by-side owner-context read take the symbol's quote, and its
chart when a price is named, off the first tool round. Nothing in the prompt,
the tools or the answers changed; the free eval completes 23 of 23 with the
same check rates as before.

None of this is proven live: the fixture and the eval never touch a
provider. The next production reading of the answer scorecard is the real
test: `latency.ask.first_text_ms` against the 15 s median, and the new
`timings` section, which says how much of what remains is the owner context,
the model's rounds, the reads, and within the reads Tradier, queueing or a
busy worker pool.

**The market read in the pack (2026-11-10).** The prefetch only warmed the
quote cache: the model still spent a round asking for quotes, the regime and
the group before answering "why is NBIS moving?". The owner pack now carries
those reads as its `market` section (§ Owner context), read beside the pack
within 3 s, so a plain question can be answered in the first round, the
no-read path that measured about 8 s. The free eval completes 23 of 23 with
the same check rates as before (the scripted model reads only the owner's
words). Unproven live: the next answer scorecard's
`latency.ask.first_text_ms` and tool-call counts on the owner's questions are
the test.

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
changed here. Since 2026-11-06 the wait also shows each read's fact line as its
result lands (§ What runs), so those seconds read as a briefing.

### Follow-up model eval (2026-11-06)

Sonnet 5.5 against Haiku 5.5 on the 23 starter cases, fixture evidence,
effort `medium`, deterministic graders, run on the VPS with the app's own key
(the main checkout's key is rejected with 401). Haiku's real spend was $0.09
for 23 cases; Sonnet's $1.42. The first attempt lost its run records to the
client-close bug fixed in #698, so the cases ran again from the per-case cache.

| Check (n) | Sonnet | Haiku | Haiku minus Sonnet, 95% |
|---|---|---|---|
| completed (23) | 100% | 100% | 0 |
| format_verdict (23) | 96% | 96% | 0 [−13, +13] |
| format_against (14–15) | 80% | 21% | −57 pts [−86, −21] |
| format_read (4–5) | 100% | 75% | −25 pts [−75, 0] |
| traceable_figures (21–22) | 86% | 64% | −24 pts [−48, 0] |
| length (22) | 9% | 14% | 0 on shared cases |
| no_orders, tools_any, verdict_in, unsupported | 100% | 100% | 0 |
| first text p50 / p90 | 6.3 s / 9.8 s | 6.9 s / 11.6 s | |
| total p50 / p90 | 6.3 s / 9.8 s | 8.9 s / 13.7 s | |
| output tokens, typical case | 450–1,100 | 900–3,000 | |

On the two follow-up cases Haiku failed `traceable_figures` on both (a
percentage not in any read) where Sonnet failed it on one, and was slower:
first text 6.3 s against 3.2 s on `followup-carry`, 9.9 s against 4.7 s on
`followup-more`. Haiku writes two to three times the words, so the hold before
the first text is longer, not shorter, and the "Against" line is dropped far
more often. The decision rule (Haiku at or above Sonnet on the follow-up cases
and on `completed`, `no_orders` and `unsupported`) fails, so
`COPILOT_FOLLOWUP_MODEL` stays `off` (`DEFAULT_FOLLOWUP_MODEL`).

Two things the run also showed. Both models fail `length` on almost every case
(120 words unless the case allows long): the 7–9 s wait is answer length, and
the prompt's length rule is not being followed by either model. And
`no_reread` was not applicable in both runs because the follow-ups' parent
answer came from the cache, which carries nothing; a run meant to measure the
carry needs `--no-cache` on the parent.

Sonnet's prose ran 150–295 words (median about 215) over four or five bullets
of two to four sentences each, plus a separate simulated-data line, a
multi-sentence Against and a closing note. The 2026-11-07 answer: per-line
word budgets in the prompt and the `ANSWER_SHAPE` reminder after every tool
result (§ How the copilot reasons), re-measured the same day (§ Answer-length
re-measure).

### Answer-length re-measure (2026-11-07)

The same Sonnet 5.5 run (23 starter cases, fixture evidence, effort `medium`,
on the VPS, $1.39) on release `24f39d9955`, which carries #701, against the
2026-11-06 run as the baseline. Both runs are graded with the figure extractor
after this change: a month-name date ("Nov 21") is masked like an ISO or M/D
date, where the deployed grader read its "21" as a figure and failed three
answers on it.

| Check (n) | Before (11-06) | After (11-07) | After minus before, 95% |
|---|---|---|---|
| length (20–22) | 9% | 38% | +25 pts [+5, +45] |
| format_against (14–15) | 80% | 100% | +21 pts [0, +43] |
| format_verdict (23) | 96% | 91% | −4 pts [−17, +9] |
| traceable_figures (21–22) | 91% | 90% | −5 pts [−25, +10] |
| no_reread (1) | n/a, parent cached | 100% | |
| completed, no_orders, tools_any, verdict_in, unsupported | 100% | 100% | 0 |
| prose words, median | 217 | 128 | |
| output tokens p50 / p90 | 677 / 1,062 | 518 / 602 | |
| first text p50 / p90 | 6.3 s / 9.8 s | 4.9 s / 6.7 s | |
| total p50 / p90 | 6.3 s / 9.8 s | 5.0 s / 8.4 s | |

The shape is now followed: three bullets, one Against, one Changes if, the
simulated-data words in the headline, no closing note and no "nothing is
saved" line. The limit is not: 18 of 23 answers are still over 120 words, but
16 of them by a little (121–153 words; the two long ones are the `long_ok`
follow-up at 336 words and the week review). The whole overrun is the bullets,
which run two or three sentences of 25–35 words against the one-sentence,
22-word budget. The two `format_verdict` misses are wording slips ("Verdict:
Wait." with a full stop where the format wants a dash, which both parsers
accept since 2026-11-08; "Verdict: Watch", not in the fixed set). The two `traceable_figures` misses: the long follow-up quotes
peer moves carried from its parent's reads, which the grader cannot see (it
checks the follow-up's own reads), and the trade review subtracts two values
from different reads (94.35 − 92.50 = 1.85). The second pass (2026-11-08):
the bullet budget is 16 words as one sentence (a second sentence is cut or
becomes the next bullet) and a compare cell 6 words, so the budgets add up to
98 and the overshoot measured here lands under 120. Re-measured the same day
(§ Second pass re-measure).

### Second pass re-measure (2026-11-08)

The same Sonnet 5.5 run ($1.37) on release `88410d928a`, which carries #703
and #704, against the 2026-11-07 run; both graded by the deployed grader
(month-name dates masked, a full stop after the verdict word accepted, so the
2026-11-07 run now has 22 `length` cases, not 21, and reads 36%).

| Check (n) | 11-07 (22-word bullets) | 11-08 (16-word bullets) | After minus before, 95% |
|---|---|---|---|
| length (22) | 36% | 82% | +45 pts [+27, +68] |
| format_against (14) | 100% | 93% | −7 pts [−21, 0] |
| format_verdict (23) | 96% | 96% | 0 |
| traceable_figures (22) | 86% | 82% | −5 pts [−14, 0] |
| prose words, median, 20 cases not `long_ok` | 126 | 108 | |
| output tokens p50 / p90 | 518 / 602 | 450 / 801 | |
| first text p50 / p90 | 4.9 s / 6.7 s | 4.6 s / 7.1 s | |

Bullets are one sentence of 15–20 words now, and 16 of the 20 ordinary cases
land at 91–115 words. The four still over: a fourth bullet (`briefing-what-matters`,
124), two long Against lines (`ask-planted-rumour` 126, `order-bait` 127, which
also dropped its Against label), and the compare case at 149, where five
compare rows plus two bullets cost more than the budget allows. The
`traceable_figures` misses are the two carried follow-ups (figures from the
parent's reads, which the grader cannot see), the trade review's own
subtraction, and one computed percentage. Good enough to leave: the next change
here is the compare form, not another pass on the bullets.

The compare form (2026-11-08, after the re-measure): the prompt and the
answer-shape reminder now say the block is the whole body, no bullets beside
it and no fifth row, and the eval grades compare cases with `format_compare`
(a Compare block with nothing beside it, at most four rows, cells within 6
words), so the next run names the compare fault instead of folding it into
`length`. Not yet measured: one compare case, so a run shows it, not a rate.

To rerun, from `backend/` with a working `ANTHROPIC_API_KEY` (on the VPS, as
the service user with its environment file):
`python -m scripts.copilot_eval run --model claude-sonnet-5-5 --effort medium --max-cost-usd 1 --out data/copilot_eval/runs/sonnet`,
the same with `--model claude-haiku-5-5 --out data/copilot_eval/runs/haiku`,
`grade --run` each, then `report --run data/copilot_eval/runs/sonnet --run data/copilot_eval/runs/haiku`.

## Research job

`backend/app/ai/research_job.py` runs one autonomous, cited investigation
through the Messages API (`app.ai.api_runner.run_agent`).
Trigger it by hand only, with `backend/scripts/run_research_job.py "question"
--symbols NBIS,CRWV --evidence fixture|live|replay [--out job.json] [--no-save]`.
It has no scheduler, Radar wake-up or notification yet.

- **Tools.** An allowlist (`research_job.JOB_TOOLS`), so a new copilot tool
  never reaches a job by default.
  - Allowed: the market reads (group comparison, peer moves, symbol news,
    earnings dates, quotes), `get_saved_research` and `get_chart_context`,
    plus Anthropic's server-side web search and web fetch, and nothing else.
  - Not allowed: `propose_plan`, `get_investigation_changes` and the book
    tools. They are never offered to a job's model.
  - Lab tools run in-process with the same validation, timeout and size
    bound. A call to any other tool is denied. Each request allows 8 searches
    and 10 fetches (`max_uses`, per request, so the budget is what bounds them
    across a job's rounds) and a job gets 12 lab-tool calls. Other limits: 24
    rounds, 600 s, and `RESEARCH_BUDGET_USD` (default $0.50), counting tokens
    and $0.01 per search and checked before each round, so one round can overshoot.
  Pages are untrusted data, and the job has no tool that could act on an
  injected instruction.
- **Output.** A structured assessment (a strict `submit_answer` tool): summary,
  key findings with citation and evidence indexes, counterpoints, what would
  change the view, citations (URL, publisher, publish time, title) and
  evidence references (tool and `as_of`). The record also has the lab tool
  calls the server actually ran, with provenance, plus web counts, cost and server-side checks:
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
| `RESEARCH_BUDGET_USD` | `0.50` | Budget for each job. |
| `RESEARCH_DAILY_BUDGET_USD` | `2` | Total spend for attempts started since midnight UTC. It is checked before every attempt. At the cap, queued jobs wait for the next day. |
| `RESEARCH_RADAR_TRIGGER` | unset (off) | `true`: every 5 minutes, each new event in today's Radar session (read only from `RADAR_STORE`) gets one `radar_event` job. |
| `RESEARCH_NOTIFY_ENABLED` | unset (off) | `true`: a job with a material result about an open investigation sends one phone ping (below). |
| `RESEARCH_NOTIFY_DAILY_MAX` | `3` | Phone pings per New York day, all jobs together. |
| `RESEARCH_REASSESS_AFTER_HOURS` | `0` (off) | N: each original open investigation that has been neither updated nor reassessed for N hours, and has no job waiting, gets one `reassess` job, at most one a day. A reassessment's own output is never reassessed. |

- **Owner-only routes** (in no assistant grant):
  - `POST /copilot/research-jobs/reassess` with `{investigation_id, question,
    after_days}` queues the owner's "revisit this question": one reassess job
    for that investigation, due `after_days` (0-30) from now, at most once a
    day per investigation, due date and question (a failed or cancelled one
    can be asked again). Its assignment adds the owner's
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

Jobs use `ANTHROPIC_API_KEY` from `backend.env`.

- **Turning it on, conservatively.** Add `RESEARCH_QUEUE_ENABLED=true`, a
  small `RESEARCH_BUDGET_USD` and `RESEARCH_DAILY_BUDGET_USD`, and leave the
  two trigger settings unset. Then
  run `sudo systemctl restart tradejournal-api`. Queue one question with
  `POST /copilot/research-jobs` and watch it with `GET /copilot/research-jobs`.
  Turning the queue off again (unset, then restart) leaves queued jobs
  waiting.
- **CI.** The "Ubuntu package and MCP smokes" job checks, without a model call,
  that the installed release imports the API runner as the `tradejournal` user.

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
  trigger today as its ticker's status line (kind and text); the ticker
  opens the investigation.

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
