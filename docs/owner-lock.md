# Owner lock (sign-in for the private app)

The private app on the server has always trusted anything that could reach it over Tailscale: open the address and
every page and every button works, with no sign-in. The owner lock adds one sign-in, a passphrase only Isaac has, in
front of the private app. It is **off** until Isaac switches it on, and switched off it changes nothing.

It was built because the server now holds a Robinhood sign-in for the [read-only feed](robinhood-read-feed.md). That
feed can never place an order, but anything that can use the app's routes can ask the server to do things, and a
later stage (an order proposal Isaac approves in the Robinhood app) must not exist until the private app has a real
lock. This is that lock. It sends nothing and does not touch the Robinhood guard.

## What it protects, and what it does not

**Protects.** Every page and every request from a browser needs Isaac's signed-in session: reading the journal, the
desk, the book, account numbers, and every button that changes something (sync, rebuild, imports, plans, alerts, the
Robinhood refresh). Another device on the tailnet, a device someone else shares into it, or a web page trying to
reach the app through Isaac's own browser gets the sign-in page and nothing else. Liveness (`ok`) and the release
number stay open; they say nothing about the journal or the database.

**Does not protect against:**

- **Anything already running on the server.** Timers, workers, the Telegram bot, scripts and the operator's own
  shell keep working without a session, by design (see [who calls the app](#who-calls-the-app)). Someone with a shell
  on the server can already read the database and the Robinhood sign-in file; the lock is the door from the network,
  not a wall inside the server. An SSH port-forward to the API counts as "on the server" for the same reason.
- **A signed-in device in someone else's hands.** A signed-in phone stays signed in for up to 30 days. If a device is
  lost, use [sign out everywhere](#signing-out).
- **The passphrase being shared.** It is the whole lock. Keep it in a password manager, nowhere else.
- **Publishing the app.** It does not make exposing the API (8080/8000) or the frontend to the internet acceptable;
  the hard constraint in `CLAUDE.md` still holds.
- **Old releases.** Rolling back to a release from before this change removes the lock silently (old code ignores the
  switch). Switching it back on needs this release or a newer one.

## Turning it on (once, about ten minutes)

On the server (`ssh ubuntu@` the server's Tailscale address), with the release's own Python:

```bash
sudo /opt/tradejournal/current/backend/.venv/bin/python /opt/tradejournal/current/deploy/owner_lock_config.py passphrase
```

It prints a new passphrase once, like `abcde-fghjk-mnpqr-stuvw-xyz23-45678`. Save it in your password manager right
away (iCloud Keychain or similar, under "Trade Journal owner"); it is not stored anywhere, only a one-way hash of it.

**Day 1, report only.** Nothing is refused yet; the app logs what it would have refused:

```bash
sudo /opt/tradejournal/current/backend/.venv/bin/python /opt/tradejournal/current/deploy/owner_lock_config.py mode report
```

That restarts the app (a few seconds). Then sign in on every device you use: each page shows a **Sign in** button
while that device is not signed in, or open `/sign-in` on the app's address (for example
`https://YOUR-SERVER.YOUR-TAILNET.ts.net/sign-in`):

- **Mac:** in each browser you use for the journal. Let the browser save the passphrase.
- **iPhone home-screen app:** open it; while the lock is report-only, a device that is not signed in shows
  **This device is not signed in yet** with a **Sign in** button at the top of each page. The home-screen app keeps
  its own sign-in, separate from Safari's, and it survives closing the app and restarting the phone.
- **iPhone Safari:** links from Telegram and phone pings open in Safari (or in Telegram's own browser), not in the
  home-screen app, so sign in once in Safari too. If Telegram opens links inside its own browser and asks every
  time, switch Telegram to open links in Safari in its settings.

**Day 2, check the log.** On the server:

```bash
sudo journalctl -u tradejournal-api -u tradejournal-frontend --since "24 hours ago" | grep owner-lock
```

Each line is something that would have been refused, for example
`owner-lock report-only: would refuse GET /api/backend/copilot/desk/feed (no owner session)`. Lines from your own
devices mean a device or browser you have not signed in yet: sign it in. Lines you cannot explain are exactly what the
lock is for. Nothing is logged for a signed-in device or for the server's own processes. Wrong passphrases are logged
as `owner-lock: sign-in refused (wrong passphrase) from <tailnet address>`.

**Then enforce:**

```bash
sudo /opt/tradejournal/current/backend/.venv/bin/python /opt/tradejournal/current/deploy/owner_lock_config.py mode on
```

`... owner_lock_config.py status` shows the current setting at any time.

## Day to day

- Each device signs in once and stays signed in for **30 days**, or until it goes **7 days unused**. Then the next
  page you open shows the sign-in page in place; sign in and the same page reloads. The browser fills in the
  passphrase from its password manager.
- Restarting the app, a deploy or a server reboot does not sign anyone out.
- Up to ten devices or browsers stay signed in at once; an eleventh signs out the oldest.
- Ten wrong passphrases in 15 minutes pause new sign-ins for 15 minutes. Devices already signed in are not affected.
- If a page's data stops loading with "Sign in required" after a long time open, reload: it was the 30-day or 7-day
  limit.
- Sharing a screenshot into the app from another app's share sheet (Android only; iPhone does not offer it) is
  refused while the lock is on unless the phone sends it as coming from the app itself; attach it in the Copilot
  Lab instead.

## Signing out

- **This device:** open `/sign-in` and tap **Sign out on this device**.
- **Every device** (a lost phone, a passphrase you think leaked): open `/sign-in` and tap **Sign out everywhere**, or
  from a shell on the server:

  ```bash
  curl -s -X POST http://127.0.0.1:8080/lock/sign-out-everywhere
  ```

  Every browser needs the passphrase again (open pages within about ten seconds; every data request immediately).
- **A new passphrase** (`owner_lock_config.py passphrase`) also signs every device out, as soon as the app restarts
  (the script restarts it when the lock is on).

## Break-glass: can't get in

Only someone with a shell on the server can do these, which is the point.

1. **Turn the lock off.** The app is back to exactly how it was before the lock:

   ```bash
   sudo /opt/tradejournal/current/backend/.venv/bin/python /opt/tradejournal/current/deploy/owner_lock_config.py mode off
   ```

   If that script itself fails, edit the file by hand and restart:

   ```bash
   sudo sed -i 's/^TJ_OWNER_LOCK=.*/TJ_OWNER_LOCK=off/' /etc/tradejournal/owner-lock.env
   sudo systemctl restart tradejournal-api tradejournal-frontend
   ```

   Deleting `/etc/tradejournal/owner-lock.env` and restarting does the same.
2. **Forgot the passphrase:** make a new one with `owner_lock_config.py passphrase` (it ends every old session).
3. **"Too many attempts":** wait 15 minutes. If it keeps happening, something on the tailnet is guessing on purpose
   and can keep new sign-ins paused (devices already signed in keep working). Find its address in the
   `sign-in refused ... from` lines above and remove that device from the tailnet in the Tailscale admin console;
   `mode off` also lets you in but drops the lock.
4. **Lock seems to do nothing:** `owner_lock_config.py status` shows the setting each running service started with.
   If the API and the web page disagree (someone restarted only one), restart both.

## Who calls the app

The lock treats three kinds of caller differently.

| Caller | How it reaches the app | Kind | With the lock on |
|---|---|---|---|
| Isaac's Mac and iPhone browsers | Tailscale Serve → frontend (3000) → its proxy → API (8080) | Isaac in a browser | Needs the session |
| iPhone home-screen app | Same, in its own cookie store | Isaac in a browser | Needs the session (signs in once) |
| Links in Telegram and phone pings | Opened in Safari or Telegram's browser → same path | Isaac in a browser | Needs the session in that browser |
| Server-rendered pages | The frontend's own server code → API on loopback | Local process (only runs after the page passed the gate) | Unchanged |
| Telegram bot, position alerts, Radar, Robinhood feed, schedulers in the API process | Inside the API process; Telegram is polled outward, nothing comes in | Local process | Unchanged |
| Workers (`tradejournal-worker@…`) and timers (alerts, sync pipeline, Gmail import, backups, plan reviews, research, shortlist) | Their own processes; those that call the app use `http://127.0.0.1:8080` | Local process | Unchanged |
| Autodeploy and `tradejournal-deploy` | `127.0.0.1:8080/health`, `/sync/summary` directly; `127.0.0.1:3000/deployment.json`, `/api/backend/health` and `/api/backend/sync/summary` through the frontend | Local process | API calls unchanged; the frontend calls carry the server's local key from `owner-lock.env` |
| Operator shell (`curl` on the server, `alerts.py test`, recovery commands) | `127.0.0.1:8080` | Local process | Unchanged |
| Check / journal MCP servers for ChatGPT and Claude | Their own HTTPS entrance and Unix sockets with Auth0 sign-in; sandboxed away from 8080 | Something else | Unaffected |
| Gmail listener | Pulls from Google's Pub/Sub; nothing comes in | Local process | Unchanged |
| TradingView webhook | Its own receiver; not through the private frontend | Something else | Unaffected |
| The local `trade-journal` MCP on the Mac (`backend/mcp_server.py`) | The Mac's own dev backend by default | Something else | Unaffected; if ever pointed at the server's private address it would be refused (report-only shows it) |
| CI, the local sandbox, browser tests | Their own backends with no lock file | Something else | Lock off unless a test turns it on |

**The rule for "local process".** A request to the API is a process on the server only if all of these hold: it
arrives from the loopback address; it does not carry the frontend's browser mark (`x-tj-lock-browser`), which the
frontend adds to every request it forwards for a browser; and it carries none of the headers a reverse proxy adds
(`X-Forwarded-For`, `X-Forwarded-Host`, `X-Forwarded-Proto`, `Forwarded`, `X-Real-IP`, `Tailscale-User-*`). So the
frontend proxy, which also arrives from loopback, is never "local", and neither is a proxy mistakenly pointed straight
at the API. The frontend itself is the only network entrance, and its gate needs the session for every path except
the sign-in page, its two sign-in/out calls and inert files (icons, the web-app manifest, `deployment.json`). The
deploy check is the one local caller that goes through the frontend; it shows the server's local key, a random value
in the root-only `owner-lock.env`, and the frontend passes that on so the API treats it as local too. Every inbound
`x-tj-*` header from a browser is removed before any of this runs, so none of it can be claimed from outside.

## Why this lock

Three ways were compared:

| | Tailscale identity headers | **Passphrase + server session (chosen)** | Auth0 owner login |
|---|---|---|---|
| What proves it is Isaac | Tailscale Serve says which tailnet user sent it | Something only Isaac knows, kept in his password manager | Isaac's Auth0 account |
| Phone friction | None | Once per device per 30 days, filled in by the password manager | Redirects out of the home-screen app to a browser and back; often signs in again |
| Lockout risk | High and invisible: if Serve stops sending the header, or Isaac uses a tagged device, nothing gets in | Low: switch, local break-glass, report-only first, no outside service | Auth0 down, a changed callback URL or an expired client secret locks him out |
| What background callers need | Nothing | Nothing (loopback rule) | Nothing (loopback rule) |
| New secret material on the server | None | A hash of the passphrase and one random local key | An Auth0 client secret plus callback configuration |
| Strength | Only as strong as Serve's configuration; every device logged in as Isaac (including the server itself) is "Isaac", and a local process can forge the header | Real: an attacker needs the passphrase | Strong, but depends on a third party for the private app |

The passphrase lock is the smallest one that is real: it adds one secret Isaac controls, no dependency outside the
server, and the way back in needs only a shell on the server. A passkey (Face ID) would be nicer on the phone but
needs a new dependency and an enrollment step; it can replace the passphrase later without changing the gate.

## How it works (for developers)

- **Switch:** `TJ_OWNER_LOCK` = `off` (default, also when unset), `report`, or `on`; any other value counts as `on`.
  Read by both the API and the frontend from `/etc/tradejournal/owner-lock.env` (root, 0600), which both units load
  last (`EnvironmentFile=-…`, so a missing file is `off`). When `TJ_ACCESS_ENABLED=true` (the assistant access mode)
  that mode authenticates everything itself and the lock stays out of the way.
- **Secrets:** `TJ_OWNER_LOCK_PASSPHRASE_HASH` (the Argon2id hash, base64 so env-file parsers leave its `$` alone) and
  `TJ_OWNER_LOCK_LOCAL_KEY` (32 random bytes), both written only by `deploy/owner_lock_config.py`. Backups include the
  file.
- **Sessions:** random 32-byte tokens; only their SHA-256 digest is stored, in `access_session` with audience
  `owner-lock` (no migration). 30 days absolute, 7 days idle, at most ten; each is tied to the passphrase it was
  issued under. The cookie is `__Host-tj_owner_lock` (HttpOnly, Secure, SameSite=Lax, 30-day Max-Age) on the https
  address, `tj_owner_lock` without Secure only on a plain-http `localhost` development origin.
- **Requests that change something** must also come from the app's own pages (`Origin` matches the host); a cross-site
  page cannot use the session even before SameSite.
- **Code:** API `backend/app/engine/owner_lock.py`, `backend/app/routers/owner_lock.py` (`/lock/*`, 404 while off) and
  the gate in `backend/app/access_middleware.py`; frontend `frontend/lib/ownerLock.ts` (called from `proxy.ts`),
  `frontend/app/sign-in`, `frontend/app/api/lock/[action]`; the deploy check in `deploy/control.py`.
- **Route classification:** every API route must be in the reviewed inventory (`backend/app/access_manifest.py`, plus
  `owner_lock.LOCK_PATHS`); `test_route_inventory_is_exhaustive` fails when a route is added without it, and with the
  lock on a browser request to anything outside the inventory is refused. All inventoried routes need the session
  except the session check, sign-in and sign-out, and `GET /health`, which answers a bare `{"status": "ok"}`.
- **Long streams:** the chart stream re-checks the session every 15 seconds and closes after sign-out. Other open
  streams end at their next reconnect.
- **Tests:** `backend/tests/test_owner_lock.py` (every route refused without a session and unchanged when off, local
  callers, header spoofing, expiry, sign-out, rate limit, report-only, logging) and `test_owner_lock_deploy.py` (the
  script, the units, the deploy check); `deploy/smoke.py` switches it on with real systemd units in CI.

## Known until the real server

These can only be confirmed on the VPS, which is why report-only comes first: that the Mac and iPhone (home-screen
app, Safari, Telegram's browser) keep the cookie as described; what address Tailscale Serve reports in the
sign-in log; that no caller missing from the table above shows up in the report.
