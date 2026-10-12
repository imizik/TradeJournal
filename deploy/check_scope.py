"""Prepare the narrow pre-trade feature view; never execute database DDL.

The view exposes one row per closed trade outside dormant brokers: close/open
time, cohort dimensions and outcome measures only. No account IDs, trade IDs,
order IDs or raw fill keys (the entry fill key is replaced by its SHA-256).
"""
import argparse

VIEW = "pretrade_feature_source"
POSITION_VIEW = "pretrade_position_source"
CAPTURE_VIEW = "pretrade_capture_source"
CAPTURE_LIMIT = 200
ROLE = "tj_check_features"
EXCLUDED_BROKERS = ("webull",)  # Matches app.engine.pretrade_check.EXCLUDED_BROKERS.
POSTGRES_FILL_KEY = "encode(sha256(convert_to(f.raw_email_id, 'UTF8')), 'hex')"

# A correlated subquery (not LATERAL) keeps one definition testable on SQLite.
SELECT = """SELECT t.closed_at, t.opened_at, t.ticker, t.instrument_type, t.option_type,
       t.entry_time_bucket AS trade_time_bucket, t.realized_pnl, t.pnl_pct,
       {fill_key} AS source_fill_key,
       (c.fill_id IS NOT NULL) AS has_context, c.entry_time_bucket AS context_time_bucket,
       c.entry_vs_vwap_pct, c.is_trend_aligned, c.is_chase_entry, c.is_late_move,
       c.rvol_time_adjusted, c.dte_bucket,
       (p.trade_id IS NOT NULL) AS has_path, p.underlying_mfe_pct, p.underlying_mae_pct,
       p.underlying_giveback_pct
FROM trade t
JOIN account a ON a.id = t.account_id
JOIN fill f ON f.id = (
    SELECT f2.id FROM tradefill tf JOIN fill f2 ON f2.id = tf.fill_id
    WHERE tf.trade_id = t.id AND tf.role = 'entry'
    ORDER BY f2.executed_at, f2.raw_email_id LIMIT 1)
LEFT JOIN fill_market_context c ON c.fill_id = f.id
LEFT JOIN trade_path_metrics p ON p.trade_id = t.id
WHERE t.status IN ('closed', 'expired') AND t.closed_at IS NOT NULL
  AND lower(coalesce(a.broker, '')) NOT IN ({excluded})"""


def select_sql(fill_key: str = POSTGRES_FILL_KEY) -> str:
    excluded = ", ".join(f"'{name}'" for name in EXCLUDED_BROKERS)
    return SELECT.format(fill_key=fill_key, excluded=excluded)


# Owner decision (October 12, 2026): Jo may see all of Isaac's trade data. Still no
# account numbers, IDs, fill keys, raw emails, images, audio or credentials.
POSITIONS = """SELECT t.ticker, t.instrument_type, t.option_type, t.strike, t.expiration, t.contracts,
       t.avg_entry_premium, t.total_premium_paid, t.opened_at, t.entry_time_bucket,
       a.name AS account_name, a.type AS account_type
FROM trade t
JOIN account a ON a.id = t.account_id
WHERE t.status = 'open' AND lower(coalesce(a.broker, '')) NOT IN ({excluded})"""

CAPTURES = """SELECT c.received_at, c.underlying, c.side, c.instrument, c.mode, c.setup_label, c.wording, c.note,
       c.strike, c.expiration, c.quantity, c.transcript_text, c.not_taken_at, c.account_label,
       (SELECT n.text FROM trade_capture_note n WHERE n.capture_id = c.id
        ORDER BY n.created_at DESC LIMIT 1) AS latest_note,
       EXISTS (SELECT 1 FROM capture_link l WHERE l.capture_id = c.id AND l.unlinked_at IS NULL) AS linked
FROM trade_capture c
ORDER BY c.received_at DESC
LIMIT {limit}"""


def position_sql() -> str:
    return POSITIONS.format(excluded=", ".join(f"'{name}'" for name in EXCLUDED_BROKERS))


def capture_sql() -> str:
    return CAPTURES.format(limit=CAPTURE_LIMIT)


def context_view_sql() -> str:
    """Open positions and recent captures for the same read-only role; no-clobber views."""
    return f"""BEGIN;
CREATE VIEW public.{POSITION_VIEW} WITH (security_barrier=true) AS
{position_sql()};
CREATE VIEW public.{CAPTURE_VIEW} WITH (security_barrier=true) AS
{capture_sql()};
GRANT SELECT ON public.{POSITION_VIEW}, public.{CAPTURE_VIEW} TO {ROLE};
COMMIT;
"""


def view_sql() -> str:
    """No-clobber view plus a select grant to the existing dedicated read-only role."""
    # Only constants enter SQL. The role is created (LOGIN, no other grants) at
    # activation; this narrows it to the view in the same transaction.
    return f"""BEGIN;
CREATE VIEW public.{VIEW} WITH (security_barrier=true) AS
{select_sql()};
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {ROLE};
GRANT SELECT ON public.{VIEW} TO {ROLE};
COMMIT;
"""


if __name__ == "__main__":
    argparse.ArgumentParser(description=__doc__).parse_args()
    print(view_sql(), end="")
