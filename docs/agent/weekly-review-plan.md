# Weekly review: one exit behavior per week — plan

**Status:** Isaac approved building it on October 21, 2026. The open questions
below were not answered, so the slice uses the defaults: a +10% winner line, a
1-hour hold line, and a review page that works any day. First slice built in
`backend/app/engine/weekly_review.py` and `/daily/week`, not yet deployed or
used on real weeks. Implements the
roadmap's [J2](../product-roadmap.md#j2--turn-weekly-review-into-one-action)
in its smallest form, shaped by the October 21 behavior audit
([the committed D0 report](../../backend/reports/behavior_audit_2026-10-21.md)) and the
July [edge audit](../../backend/reports/edge_audit_2026-07-07.md).

## Why this, and why exits

Across 1,528 closed option trades Isaac is roughly breakeven (+$2.6k without
the five best winners). The losses come from **exits**, and the evidence holds
in both halves of the data:

- Since July 7, trades that were up ≥ $50 and then closed red cost −$10.4k
  (15 trades). Of 146 losers held 1 h → close, 53 had been up ≥ 10% in their
  first hour.
- Holds of 1 hour to the same-day close: −9.5% mean return, −$17.6k all time.
- Options that expired worthless since July 7: 11 trades, −$7.5k.

The entry flags the AI reviews coach on (chase/extension, trend and day-move
alignment) did **not** separate his winners from his losers. The July rules
already existed in a report and changed nothing. The weekly review is the
"choose one thing and check it" half of the product goal; the in-trade nudge is
the open-trade alerts built in #372 (off by default; activation is separate).

## What the weekly screen shows

One page, `/daily/week/[monday]`, beside the existing month page
(`frontend/app/daily/month/[month]/page.tsx`), linked from the Review Calendar.
Owner only, same access check. Phone-first; readable in under two minutes.

1. **Last week's rule, checked** (only if one was chosen). The rule in plain
   words, then the evidence from trades **entered after it was chosen** and
   closed by now:
   *"Don't let a +10% winner close red — 5 trades reached +10%: 4 closed green,
   1 closed red (SNDK, −$420)."* Each number opens its trades. A suggested
   result — **kept / partly / broken / not enough trades** (fewer than 3
   trades tested it and none broke it; a single break is never "not
   enough") — that Isaac confirms or changes with one tap. Positions still
   open are listed as "not judged yet".
   If open-trade alerts exist, one extra line: *"2 give-back alerts; after 1
   you closed within 15 minutes; after the other you held and closed −$180."*
2. **The week in one line:** trades closed, realized P&L, win rate — linking to
   the trades list filtered to the week.
3. **This week's exit leaks** — always the same three rows, so weeks compare:

   | Leak | Counted as (trades closed or expired this week) |
   |---|---|
   | Winner ridden to red | option peak ≥ +10% of premium paid, closed below entry |
   | Held an hour, closed red | open ≥ 60 minutes, closed below entry |
   | Died on its last day | status `expired` at a loss, or closed on its expiry day at ≥ 90% loss |

   Each row: count, dollars, and the trades. Trades without path metrics are
   counted under "not measured", never as zero.
4. **Pick one for next week.** The three leaks as ready-made rules, ordered by
   this week's dollar cost, plus "keep last week's rule" and "skip this week".
   One tap saves. An optional one-line note; nothing is required to type.
5. **Coverage footer:** trades in the week, how many had path metrics, which
   accounts were included (Roth + Individual; Webull excluded).

Not shown: grades, chase/trend flags, an AI essay, "what you would have made"
(the audit simulated no exits, and hindsight peaks were not necessarily
fillable).

## Where the commitment lives and how it comes back

One new additive table, `weekly_review`, in the `MonthlyReviewRecord` style:

- `week_start` (New York Monday, unique), `rule_key` (one of the three, or
  null for skip), `rule_params_json` (the threshold frozen at choice time,
  e.g. `{"peak_pct": 10}`), optional `note`, `chosen_at` (UTC).
- Last week's check: `result` (kept / partly / broken / not_enough; a
  skipped week is a row with no rule), `result_source` (suggested vs changed by Isaac), and
  `evidence_json` — the counts as shown plus each trade's **source anchor**
  (account + first entry fill `raw_email_id`, the `CaptureLink`/`CheckLink`
  pattern), so the frozen evidence survives `rebuild-all`.

Next week the page recomputes the check from current trades for trades entered
between `chosen_at` and the moment he confirms the result (at the latest, the
end of the practice week). Confirming closes the check and freezes the
snapshot; trades entered afterwards count toward the next rule, and the page
says so beside the result buttons.
History of rules and results is a simple list at the bottom of the page —
"3 of the last 4 weeks kept" is the progress signal, not P&L.

Week boundaries: Monday 00:00 → the next Monday 00:00, New York. The leak rows use the
analytics rule (trades **closed** in the week); the rule check uses trades
**entered** after the rule was chosen. Both are stated on the page.

## Jo or deterministic? Deterministic first

- J2 requires that completing a review needs no AI call.
- The three leaks are counts over existing fields (`Trade`,
  `TradePathMetrics.option_mfe_pct`, `option_peak_unrealized_pnl`, status,
  hold time). A model adds risk of narrating chase/trend again, which the audit
  says does not predict his results.
- Jo has no weekly-review tool on the Check connection; adding one means a new
  tool, grant and receipt flow — exactly the "new auth" this plan avoids.

Jo comes in **after** the screen is used, through what already exists:

- **Slice 2 (optional):** a "Remind Jo" toggle that saves the chosen rule as an
  owner-accepted Jo memory (`JoMemoryRevision`, already owner-managed), so the
  morning briefing can cite it daily. No new grants; memory is copied only on
  Isaac's tap.
- **Slice 3 (after the owner activates saved-advice links #363/#364):** list
  the week's trades that have a linked check, display only. No grading of
  "followed vs overrode".

A Jo-written weekly draft is reconsidered only if Isaac finds the fixed menu
missing the real lesson after a few weeks.

## Open-trade alerts (built elsewhere)

This plan only **reads** them. What the review needs from that work: each sent
alert persisted with its kind (give-back / last-day expiry), sent time,
delivery status, and the trade's source anchor (account + entry fill
`raw_email_id`). The review then shows, per alert, whether the position was
closed within 15 minutes and how it finished. If alerts are not persisted that
way, the line reads "alerts not recorded" and nothing else changes.

## Smallest first slice

Backend: one table + migration, one engine module computing the three leaks
and the rule check, `GET/PUT /weekly-review/{monday}` mirroring `monthly_review.py`.
Frontend: the week page and a link from the Review Calendar. No AI, no alerts
line (until that work lands), no Jo memory toggle.

**Acceptance (built):**

- Fixture weeks: each leak count and dollar total matches its definition; every
  number opens exactly its trades; missing path metrics show as "not measured".
- Choose a rule → reload → still there; run `rebuild-all` → the rule, its
  result and its evidence trades still resolve (or show unresolved, never a
  different trade).
- Next week shows the prior rule with evidence only from trades entered after
  `chosen_at`; "not enough trades" under 3; still-open positions listed apart.
- Confirm, change, skip and "keep last week's rule" all save and reload.
- NY week boundaries including a holiday week and Friday expiries.
- Works with Check, Jo and the Claude plan all unavailable.
- Phone and desktop browser acceptance remains unverified by a committed weekly-review browser test.

**Acceptance (in use) — separate, Isaac's call:** he completes three
consecutive weekly reviews in under ~2 minutes each and can say which rule he
practised and whether he kept it. If the page goes unread, shorten it before
adding anything. Whether give-backs and expiries actually fall is tracked over
the next ~30 trades and reported as an observation, not proof of an edge.

**Review tier:** the migration makes this consequential (tier 2) under
[review policy](pr-review.md); who merges follows its user-gated list.

## Out of scope

- Building the open-trade alerts, or any notification/reminder for the review.
- New Jo tools, grants, Check changes, or a Jo/Claude-written weekly draft.
- Changing the daily or monthly AI reviewers (their own "one commitment" stays
  as is; whether the monthly one should defer to the weekly rule is a later
  question).
- J1 reflection forms, required notes, psychology labels or trade grades.
- J5 experiment framework, counterfactual exit simulation, threshold tuning.
- Entry rules (including "stop after you're green on the day", which held up in
  the audit but is an entry behavior) — candidates for a later menu item only
  if the exit rules are kept for several weeks.
- Stock trades, Webull, open-position P&L, trading automation.

## Questions for Isaac

1. Winner threshold: **+10% of premium** (fits all sizes) or **+$50**?
2. When to review: Friday after the close, or the weekend?
3. Is "1 hour" the right line for the hold rule, or would you rather practise
   "close or re-decide at 45 minutes"?
