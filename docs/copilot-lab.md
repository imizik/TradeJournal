# Copilot Lab

An owner-only experiment: does a Claude conversation embedded in TradeJournal
help the owner's research workflow more than hosted Trader Jo? It is a
read-only sparring partner. It does not monitor, alert, trade, or save plans.
Trader Jo, follow-ups, price watches, Shadow and MCP work are separate and
untouched.

## What runs

- `GET /copilot/status` and `POST /copilot/chat` (Server-Sent Events) in
  `backend/app/routers/copilot.py`. The frontend page is `/copilot-lab`
  (`frontend/components/copilot/CopilotLab.tsx`). It is in the nav ("Copilot") only for the owner while the lab is on.
- One conversation component, `frontend/components/copilot/CopilotPanel.tsx`.
  It is the full page (`variant="page"`, `CopilotLab.tsx`: Recent, symbol,
  history, deep links) and the panel beside other pages (`variant="panel"`).
  Both share investigations, proposals, Research deeper, What changed? and
  linked activity. A panel renders nothing for the assistant profile or while
  the lab is off.
  - The nav, every panel and every Ask copilot button share one
    `/copilot/status` read per page load (`lib/copilot.ts` `copilotStatus`,
    `useCopilotOn`).
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
    - Charts' Symbol info Overview tab also keeps its "Ask copilot" link into
      the lab.
  - **Radar:** "Ask copilot" in an event's detail opens the same panel in
    place, as a right-hand drawer (full screen on a phone), on the event
    symbol, with its one-line summary as the context. Escape or the backdrop
    closes it, and focus returns to the button.
  - **Deep link:** `/copilot-lab?symbol=X&context=<short text>` opens a new
    investigation with the symbol set and `Context: <text>` (at most 300
    characters) in the message box.
  - **Trade page:** a closed trade offers "Review with copilot" next to
    "Open on chart", which deep-links with `Review this trade: <trade id>` as
    the context; an open one offers "Ask copilot about this position" with
    `Review this position: <trade id>` (Review a trade or position, below).
  - **Position alerts:** with the lab on, each position alert push carries an
    "Ask copilot" action beside "Open app" that deep-links with the alert's
    context (Review a trade or position, below).
  - **Phone:** the off-by-default unplanned-entry nudge deep-links here with
    `Plan this position: …` when a new position has no plan (see the
    [feature map](agent/feature-map.md), "Unplanned-entry plan nudge").
  - Browser proof: `frontend/e2e/copilot-entry.spec.ts` (including a 375 px
    phone check), `frontend/e2e/copilot-panel.spec.ts` and
    `frontend/e2e/copilot-review.spec.ts`.
- **Open threads**, the lab page's home. While the lab is on, no
  investigation is open and nothing has been sent, the page (not the panel
  beside Charts or Radar) shows what is live above the conversation:
  - positions: symbol, instrument, unrealized %, give-back state, and days to
    expiry (options) or time held (stocks);
  - armed alerts: symbol, condition, price, label;
  - open investigations: title and conclusion, each a link that opens it in
    place;
  - waiting research jobs.

  It reads `GET /copilot/threads`, which returns `{positions, investigations,
  watches, as_of}` from the no-symbol owner context pack (Owner context,
  below). A position is cut to the fields above: no account, entry, mark or
  captured plan. Memories and habits are never returned, and the only ids are
  investigations'. It is a page read, not a turn, so the pack's size cap does
  not apply (`owner_context(None, bounded=False)`); each section keeps its row
  caps. A section the server could not read says so. Fixture mode serves the
  simulated pack. Replay says it is unavailable.

  Opening reads, never sends: a turn costs money, as with What changed?. One
  button, **What matters right now?**, starts a new conversation with no
  symbol and sends one fixed prompt (`lib/copilot.ts` `WHAT_MATTERS_PROMPT`):
  "What matters right now across my open positions, armed watches and open
  investigations? Lead with anything that needs a decision today; say plainly
  if nothing does." Browser proof: `frontend/e2e/copilot-home.spec.ts`
  (including a 375 px phone check).
- `GET`/`POST /copilot/investigations` and `GET`/`PUT /copilot/investigations/{id}`
  hold saved investigations (below).
- All these routes are owner-only: they are in no assistant grant
  (`backend/app/access_manifest.py`), and `frontend/lib/backendProxy.ts`
  refuses `copilot` for the assistant profile.
- One turn (`backend/app/ai/copilot.py`) streams the answer and lets the model
  call thirteen read-only tools (`backend/app/ai/copilot_tools.py`): Radar group
  comparison, peer moves, symbol news, earnings dates, quotes, saved research,
  investigation changes (below), the chart and book tools below (including the
  closed-trade review), and the owner context pack for another symbol (Owner
  context, below). It can
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
  - Research jobs never get `get_positions`, `get_trades`, `get_memories` or
    `get_trade_review`: a job reads untrusted pages and can fetch URLs, which
    could carry the book out. Those four aren't even registered for a job;
    `get_chart_context` is allowed.
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
  names, tokens and estimated cost. The UI shows the same metrics under each
  answer.

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
  instrument fit (expiry, strike and premium against the horizon; marks only,
  no implied volatility or Greeks, so it says so rather than estimates), and
  the decision now (what changed for the thesis versus only for the
  position). "Nothing here changes the plan" and "not worth a trade" are
  complete answers.
- The evidence, time-labelling, pushback and untrusted-text rules; the owner
  context block (below); memory proposals (Confirm a plan); trade and
  position reviews (Review a trade or position); plans, and pressure-testing a trade the
  owner wants to take before one plan card (Confirm a plan); SIMULATED;
  no orders; brevity that leads with what matters for the decision.

Tests pin the sentences other guards depend on (`tests/test_copilot_book.py`
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
- **No symbol** (a turn with an empty symbol box, and Open threads): there is
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

## What changed?

A reopened investigation, from Recent or from an alert's
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
otherwise. The position alert push itself carries an **Ask copilot** ntfy
action next to Open app (both need `ALERT_APP_URL`; this one also
`COPILOT_ENABLED=true`), whose context adds what the alert saw, e.g.
`Review this position: <id>. Give-back alert at 11:02 AM: was +$124, now +$20.`
(at most 300 characters, `position_alerts.ask_copilot_path`). The message box
holds the context, unsent; the owner sends it, adding a question if they like.
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
    setup, side, mode, wording, note, planned size, time) and its timing
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
  says so), minutes held, days to expiry and expires-today, the give-back
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

## Confirm a plan

When asked for a plan, the model may call `propose_plan` (at most two per
answer; one for a memory and one for a trade plan). The tool validates the proposal and writes nothing. The lab streams
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
  - The card (`frontend/components/copilot/TradePlanCard.tsx`) shows the
    thesis, entry and invalidation prices, time stop and size as editable
    fields with phone-sized tap targets. Confirm runs three parts, each with
    its own result; a failed part says why and offers a retry of that part
    only:
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
      "NBIS entry: …" and "NBIS invalidation: …". They run only once the plan
      is saved, and an invalidation the fresh price has already crossed is
      refused rather than armed on the wrong side. Without alert support the
      card says so and Confirm saves only the plan.
  - Fixture demo: "plan a trade" in the owner's words makes the fake model
    read the quote and the 5m chart and propose a long-calls plan (entry on a
    5m close above the nearest level overhead, invalidation through the
    nearest one below).
  - Browser proof: `frontend/e2e/copilot-trade-plan.spec.ts`.
- **Linked activity:** under an open investigation, the lab lists its level
  alerts (`source_kind == "copilot"`, `source_id ==` its id) with their state
  (armed, or fired with a time and price), and its revisit jobs. Both come
  from their own routes; there is no new store.
- Proposal cards live in the conversation on screen, not in the saved
  transcript. A confirmed step remains as linked activity.
- `/copilot-lab?investigation=<id>` opens that saved investigation.
- Conditional plans and follow-ups (Jo) are not touched.
- Browser proof: `frontend/e2e/copilot-plan.spec.ts`.

## Saved investigations

After each turn the page saves the conversation as a `copilot_investigation`
row (`backend/app/models.py`, additive migration `a7c1e3f5b9d2`), so it can be
resumed from any browser. The lab lists the 8 most recent; clicking one
resumes it. A row holds a title (the first question), symbol, open/closed
status, an optional one-line conclusion, the text-only transcript, and evidence
references: tool name, `as_of`, provenance kind and which answer used it, never
the data. Each save carries the revision it was read at, and a stale save from
another window is refused (409). The browser remembers only which
investigation was open. No follow-up, plan, decision, memory or monitoring is
created or linked.

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
| `COPILOT_ENABLED` | unset (off) | `true` turns the routes on. Leave it unset in production. |
| `COPILOT_BACKEND` | `fake` | `fake` is a scripted stand-in that makes no API call. `anthropic` uses the Messages API and spends credits. `plan` runs on the owner's Claude plan through the Agent SDK and spends no API credits (below). |
| `COPILOT_EVIDENCE` | `fixture` | `fixture` returns SIMULATED neocloud data; the model is told so in its context line, in a `"simulated": true` marker on every tool result and in the system prompt, and says so in its answer. `live` reads this installation's Radar, news, Tradier and quote services. `replay` reads a recorded session at a frozen moment (below). |
| `COPILOT_REPLAY_STORE` | none | `replay` only: path to a read-only copy of a Radar store. |
| `COPILOT_REPLAY_AT` | none | `replay` only: New York time inside a recorded session, e.g. `2026-10-23T11:12`. |
| `COPILOT_MODEL` | `claude-sonnet-5-5` | Model id for `anthropic` and `plan`. |
| `COPILOT_EFFORT` | `medium` | `low`, `medium` or `high`. |
| `COPILOT_TURN_BUDGET_USD` | `0.25` | Estimated API spend at which a turn stops between rounds (output is also capped at 4,000 tokens per round). For `plan` it is Claude Code's API-equivalent estimate (`max_budget_usd`); nothing is billed. |
| `COPILOT_FALLBACKS` | on | Sends the server-side refusal fallback (`fallbacks: "default"`). `off` disables it. |
| `ANTHROPIC_API_KEY` | none | Read only by the backend process for `anthropic`. It is never sent to the browser, and `plan` never passes it to Claude Code. |
| `CLAUDE_CODE_OAUTH_TOKEN` | none | `plan` only: the plan token from `claude setup-token`. |
| `TJ_CLAUDE_CONFIG_DIR` | a private temp directory | `plan` only: Claude Code's state directory, never the owner's `~/.claude` (shared with `backend/app/ai/plan_runner.py`). `TJ_CLAUDE_BIN` picks the Claude Code binary the same way. |

A model id the price table doesn't know (a dated id, or a fallback model the API reports) is priced at its
known base model, otherwise at the dearest known price, so the per-turn cap always applies.
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
  - A finished job's result appears under Recent, with "Open result" and
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

## Before a live API test

1. The owner approves the spend. A billing refusal is reported as "API credits
   are not available on this account yet."
2. Set `ANTHROPIC_API_KEY`, `COPILOT_BACKEND=anthropic` and `COPILOT_ENABLED=true`
   on a local backend only, and unset `ANTHROPIC_BASE_URL`. The client pins
   `https://api.anthropic.com` regardless.
3. Keep synthetic runs (`fixture` evidence) and live-evidence runs separate
   when comparing against Jo. Record latency and cost from the metrics line.
