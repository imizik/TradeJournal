# Claude Duet trial: the bracket around the trading day

Claude Duet (Anthropic's proactive agent, research preview since October 21,
2026) uses the connectors already on the owner's Claude account, checks them
every few hours, sends a morning brief and asks before it sends, pays, signs
or deletes. It cannot trade. Its slowness rules out intraday alerts, which the
app's own two-minute monitors keep. The trial points it at the two slow jobs
the app does worst: a researched brief before the open and a debrief after
the close that follows up.

No new server is built. Duet reaches the existing VPS Check and journal-coach
MCP servers as Claude custom connectors, under its own ledger actor. Merging
this document activates nothing; every step below is the owner's.

## 1. Auth0: one public client for Claude

In the existing tenant create an application **Claude Duet** (Native, public,
no client secret) with exactly one callback:

```
https://claude.ai/api/mcp/auth_callback
```

Grants: authorization code and refresh token, PKCE S256, refresh-token
rotation (Claude registers as a public client and expects rotation). Authorize
it for the Check API and the journal-coach API, the same scopes the ChatGPT
client has (`check:read check:run check:note offline_access` and
`d0:profile journal:read offline_access`); leave `shadow:decide` and the
`market-watch:*` scopes off this client. Note the client ID.

Claude reads the server's protected-resource metadata, requests the scopes it
advertises and appends `offline_access`, so no issuer or Caddy change is
needed. Anthropic calls from `160.79.104.0/21`; the Check entrance has no IP
allowlist.

## 2. VPS: a second profile bound to that client

Order matters: this edit needs the merged code on both runtimes first. The
Check runtime is upgraded with `deploy/check_control.py upgrade` from a build
of this change. The live journal coach is the manually installed
`tradejournal-journal-real` service (runtime under
`/opt/tradejournal-journal-real/runtime/backend/`, config in
`/etc/tradejournal-journal-real/`; the `tradejournal-journal-coach` unit from
`deploy/journal_coach_stage.py` is the fixture-only gateway and is not it). It
is refreshed by hand: copy the merged `cloud_mcp_d0.py` and
`cloud_mcp_journal.py` over the runtime copies (root-owned, mode 0644) and
restart the service. The app's automatic deployment touches neither runtime.
An older runtime rejects the unknown `client_id` field and refuses every token
until the file is reverted.

Profiles carry an optional `client_id`. A profile with one is matched only by
tokens from that client, so the same Auth0 subject through Claude becomes a
separate actor: its pre-trade checks, verdicts, day reviews, grades, notes,
shadow decisions and plans are keyed by its own profile ID, and it can neither
list nor annotate Jo's. Jo's existing rows keep their key, and the owner's
`/advisor-review` list and grades keep showing hosted Jo only, so Duet's
checks never count as Jo's; Duet's own `review_checks` and `grade_checks`
are where its record lives. The first profile
stays Jo's and uses the top-level client (the owner briefing and follow-up
paths read it); a second profile may not name the top-level client.

In `/etc/tradejournal-check/config.json` append, as the second profile:

```json
{"subject": "<the same Auth0 subject as profile 0>", "id": "check_<new uuid4>",
 "enabled": true, "client_id": "<Claude Duet client ID>"}
```

Do the same in `/etc/tradejournal-journal-real/config.json` with a
`d0_<new uuid4>` ID. A new profile is a grant change: from the moment the file
changes until `tradejournal-check.service` and
`tradejournal-journal-real.service` are restarted, every token on that server is refused, Jo's included, so edit and
restart in one step, outside Jo's scheduled reads. Later flipping `enabled`
on the Check profile applies on the next call; on the journal coach any
profile change, `enabled` included, refuses every token until its restart.
Revoking Duet is `enabled: false` on its profiles, the journal restart, and
disconnecting the connector in Claude.

## 3. Claude: add both servers as custom connectors

In claude.ai, Customize > Connectors > Add custom connector, twice:

| Field | Check | Journal coach |
|---|---|---|
| Name | TradeJournal Check | TradeJournal Journal |
| MCP server URL | the exact `resource_url` of the Check config | the exact `resource_url` of the journal config |
| Authentication | Sign in now | Sign in now |
| OAuth client | Use your own OAuth client, the Claude Duet client ID, secret blank | same |

After signing in, open each connector and set these Check tools to
**Blocked**: `shadow_setup`, `shadow_decide`, `market_watch_snapshot`,
`market_watch_submit`, `stock_alert`, `stock_alert_submit`, every
`followup_*`, `conditional_plan_*` and `jo_*` tool, and `grade_checks`.
This is the Claude-side half; the server's half is the scopes the Auth0
client holds (keep `shadow:decide`, `market-watch:*`, `jo:read` and
`jo:submit` off it, since Claude requests every scope the server advertises)
and the actor separation above. Nothing Duet does can reach Jo's records
either way. Allowed: `position_check`, `preopen_watchlist`, `get_notes`,
`candles`, `pre_trade_check`, `attach_model_verdict`, `review_checks`, and
both journal tools. Duet inherits the connectors from the account; nothing is
configured inside Duet.

## 4. Duet: the two standing instructions

Send each as one message. Duet keeps them as standing work.

**Morning brief.** Every trading morning by 8:15 America/New_York: call
`position_check` and `preopen_watchlist` on TradeJournal Check and
`get_journal_summary` on TradeJournal Journal. Then read, with your browser,
overnight index futures, today's scheduled macro events, and news on each
held or watched symbol, including earnings within two trading days. Send me at
most six lines: the macro backdrop in one, then one line per position or
watched name that has something new, each with a number and the source. Say
"nothing new" for the rest. Never suggest an order size or a trade; the app
decides exits. If a tool refuses or is stale, say so instead of guessing.

**Evening debrief.** Every trading day at 16:30 America/New_York: call
`get_notes` and `position_check` on TradeJournal Check and
`list_journal_trades` on TradeJournal Journal; `review_checks` shows only the
checks you ran yourself. Ask me one question about the day: the exit I
overrode, the plan I skipped, or the position I added to without a plan. Wait for my answer, then draft a three-line journal note in my words
and show it to me; I paste it into the journal myself. If I do not answer,
ask again the next evening with what changed since.

## 5. Judge by use, not by setup

Rate each brief 1 to 5 the way Jo's mornings are rated, for five mornings,
beside Jo's briefing for the same days; weak content (no macro context) was
the complaint about Jo's October 21 brief. Count how many debriefs ended in a
saved journal note. No tuning of the instructions before five sessions. The
decision is keep, swap one job to Duet, or turn it off; none of it implies a
trading edge, and nothing here changes Jo, Shadow or the app's alerts.
