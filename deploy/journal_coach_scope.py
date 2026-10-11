"""Prepare the account/date/column-bound export view; never execute database DDL."""

from uuid import UUID


def scoped_view_sql(account_id: str, rolling_days: int = 30) -> str:
    """Generate a no-clobber view and narrow the existing dedicated export role."""
    if str(UUID(account_id)) != account_id:
        raise ValueError("Require one canonical approved account UUID")
    if type(rolling_days) is not int or not 1 <= rolling_days <= 31:
        raise ValueError("Share at most 31 inclusive Eastern days")
    # Only validated UUID/integer literals enter SQL. No names, account text,
    # database credentials or caller-selected relation identifiers are accepted.
    return f"""BEGIN;
CREATE VIEW public.journal_coach_export_trade WITH (security_barrier=true) AS
SELECT id, account_id, ticker, instrument_type, contracts, realized_pnl,
       status, opened_at, closed_at
FROM public.trade
WHERE account_id = '{account_id}'::uuid
  AND status IN ('closed', 'expired')
  AND closed_at >= ((CURRENT_TIMESTAMP AT TIME ZONE 'America/New_York')::date - {rolling_days - 1})
  AND closed_at < ((CURRENT_TIMESTAMP AT TIME ZONE 'America/New_York')::date + 1);
REVOKE SELECT ON public.trade FROM tj_journal_export;
REVOKE SELECT (id, account_id, ticker, instrument_type, contracts, realized_pnl,
  status, opened_at, closed_at) ON public.trade FROM tj_journal_export;
GRANT SELECT ON public.journal_coach_export_trade TO tj_journal_export;
COMMIT;
"""
