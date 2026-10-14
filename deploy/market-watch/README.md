# Optional market-watch publisher units

These units are reviewed templates for an explicitly activated publisher. The
ordinary installer and release controller do not install, enable, start, or
restart them. No ChatGPT task, Jo wake, notification transport, or read
submission is configured here.

The timer refreshes the existing immutable snapshot at two-minute intervals
from 09:49 through 15:59 America/New_York. The four packets immediately before
Jo's planned 09:50, 11:00, 12:30, and 14:00 tasks are labeled
`planned_jo_wake_packet`; all other publications are labeled
`background_refresh`. This service neither creates nor verifies Jo wakes. It
has no persistent catch-up behavior and refuses starts more than 90 seconds
late. The existing exchange calendar gates each publication, including
holidays and early closes; after a half-day close, later intervals are skipped.
An unknown calendar records a typed failure. Valid partial or stale-source
packets are published unchanged with explicit quality flags so Jo can abstain
on that exact packet; structurally invalid or late packets are refused. Each
attempt has a content-hashed, append-only receipt under the date and slot.
A typed failed attempt can be retried only with the explicit
`--retry-failed` flag, while it is still inside that slot's 90-second
invocation window. The runner never performs a late catch-up. If it finds a
`started` receipt without a terminal receipt, it leaves that attempt unknown
and refuses recollection: a public snapshot alone cannot prove that this
invocation published it. Preserve the receipt and public files, compare their
hashes and timestamps during owner reconciliation, and resolve the
uncertainty before any separately authorized manual retry. Do not delete the
`started` receipt or force a late retry; the next normal slot proceeds
independently. An error after the publisher is entered also leaves the attempt
as `started`: publication may already be visible even if a later fsync or
receipt write failed, so `--retry-failed` cannot recollect or duplicate it.

The publisher uses the existing MW-1 build_snapshot and publish_snapshot
functions. Its collection child receives only DATABASE_URL, ALPACA_API_KEY,
ALPACA_API_SECRET, TRADIER_API_KEY, optional TRADIER_BASE_URL, and
ALPACA_DATA_FEED from a systemd credential copy of
/etc/tradejournal/backend.env. Dotenv parsing disables interpolation to avoid
cross-key secret expansion; the child explicitly sets ALPACA_DATA_FEED=iex for
this invocation only. PGOPTIONS makes Postgres transactions read-only, and
the child confirms SHOW transaction_read_only before collection. It does not
receive migration credentials or model keys. Its only writable paths are the public snapshot directory and the
private market-watch state directory, which holds receipts and the existing
exchange-calendar cache. The check service's snapshot directory and read-only
boundary do not change.

After separate activation authorization and deployment review, provision the
public directory with the existing owner/group model. The service's `0027`
umask lets the check group traverse new public directories and read the
published protocol and snapshots; private receipt files and directories are
created with explicit `0600` and `0700` modes:

    sudo install -d -o tradejournal -g tj-check -m 2750 /var/lib/tradejournal-market-watch-public
    sudo install -d -o tradejournal -g tradejournal -m 0700 /var/lib/tradejournal/market-watch
    sudo install -d -o tradejournal -g tradejournal -m 0700 /var/lib/tradejournal/market-watch/schedule-receipts
    sudo install -d -o tradejournal -g tradejournal -m 0700 /var/lib/tradejournal/market-watch/chart-calendar-cache

The service template is installed disabled. Only the timer is enabled after
review:

    sudo install -o root -g root -m 0644 /opt/tradejournal/current/deploy/market-watch/tradejournal-market-watch-publisher.service /etc/systemd/system/
    sudo install -o root -g root -m 0644 /opt/tradejournal/current/deploy/market-watch/tradejournal-market-watch-publisher.timer /etc/systemd/system/
    sudo systemctl daemon-reload
    sudo systemctl enable --now tradejournal-market-watch-publisher.timer

This activates snapshot publication only. It does not prove that a Jo task
actually woke, read, or submitted anything; inspect the scheduler's own
receipts and the publisher's per-slot receipts separately.
