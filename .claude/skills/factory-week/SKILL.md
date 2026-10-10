---
name: factory-week
description: Run the strategy factory's weekly idea loop now, by hand, with this session as the idea model instead of the scheduled run's `claude -p` (both on the user's Claude plan). Use when the user asks to run the factory, do a factory run now, or get new strategy ideas judged.
---

# A factory week, with you as the idea model

The strategy factory (`docs/strategy-factory.md`) runs by itself every Sunday
and has `claude -p` answer its brief on the Claude plan. This is the same run
started by hand, and you answer instead: the factory writes the brief, you
write the ideas, and the factory judges them exactly as it judges the
scheduled run's, records them, pushes the results and sends the phone its summary.

It all happens in the factory checkout, `/Users/user/TradeJournal-factory`
(branch `factory/ledger`, which holds the live ledger), never in this
session's own checkout. The script there refuses to run with uncommitted
files, merges `main` first, and fetches the week's bars itself.

## The one rule that matters

**Propose from the brief alone.** Before your answer is judged, do not read
the ledger, the reports, the specs or the trade files, and do not run the
factory's other commands to see results. The brief is deliberately what the
idea model may see: exam results reach it only as passed or failed, and
anything more would let the locked holdout shape the ideas. If this session
has already seen results beyond a brief (it worked on the factory, or read a
report or the ledger), say so and suggest running this in a fresh session.

## Steps

1. **Write the brief** into your scratchpad directory (or `/tmp` if you have
   none), using an absolute path:

   ```bash
   bash /Users/user/TradeJournal-factory/scripts/factory_week.sh --brief <scratchpad>/factory-brief.md
   ```

   It takes a minute or two. Exit status 3 means this week's three
   candidates are already used (the week runs Sunday to Saturday). Tell the
   user, and ask whether to run more anyway; if they say yes, repeat with
   `--budget N` (N as they choose, 3 by default) on this command and on
   step 4's.

2. **Read the brief in full.** It is long: the rules (the idea model's
   system prompt), the spec format, the catalog of families and features, every
   idea so far with its results, discovery evidence, and earlier lessons.

3. **Answer it as the idea model**, following its rules and its JSON format
   exactly, with no more ideas than it asks for. Write the answer to
   `<scratchpad>/factory-answer.json`:

   ```json
   {
     "ideas": [
       {
         "title": "...",
         "hypothesis": "...",
         "builds_on": "an id from the ledger, or empty",
         "change": "the one thing changed",
         "from_evidence": false,
         "spec_json": "{\"family\": \"recovery_swing\", \"exits\": {\"breakeven_r\": 1.0}}"
       }
     ],
     "lessons": "three to six plain sentences on what the ledger says now",
     "wanted": ["building blocks that would let better ideas be tested"]
   }
   ```

   `spec_json` is the spec as a JSON string, not an object. Those keys and
   no others: the factory refuses an answer that does not fit, and its review
   refuses any single idea that breaks the brief's rules, with the reason.

4. **Judge and record:**

   ```bash
   bash /Users/user/TradeJournal-factory/scripts/factory_week.sh --answer <scratchpad>/factory-answer.json --answer-by "<your model's name> in a Claude Code session"
   ```

   Every idea is backtested, which takes from a few minutes to most of an
   hour (the one-minute families are slow), so run it in the background and
   wait for it to finish. It commits the specs, the ledger lines and the
   report to `factory/ledger`, pushes, and sends the summary to the phone.
   If it fails, it says why, and the phone hears about it too.

5. **Report back.** Now the results are yours to read: the newest report in
   `/Users/user/TradeJournal-factory/research/reports/`. Tell the user in
   plain words: the headline, each idea's verdict in a line (and for a failure,
   the check that failed), and what the ideas want built next. Do not propose
   more ideas in this session after reading results; the next run starts
   fresh.
