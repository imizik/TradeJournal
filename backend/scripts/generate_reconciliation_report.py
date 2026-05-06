from __future__ import annotations

import argparse
import csv
import re
import sqlite3
import sys
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Iterable


BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
DB_PATH = BACKEND_ROOT / "data" / "trade_journal.db"
DEFAULT_INDIVIDUAL_CSV_PATH = BACKEND_ROOT / "Robinhood" / "Jul2023 to April2026.csv"
DEFAULT_ROTH_CSV_PATH = BACKEND_ROOT / "Robinhood" / "ROTH jul2023 to april 2026.csv"
DEFAULT_OUTPUT_DIR = BACKEND_ROOT / "reports"
DEFAULT_OUTPUT_PATH = DEFAULT_OUTPUT_DIR / f"reconciliation_report_{date.today().isoformat()}.md"

EXECUTABLE_TRADE_CODES = {"BTO", "STC", "Buy", "Sell"}
KNOWN_NON_TRADE_CODES = {"SLIP", "ACATI", "CDIV", "MTCH", "CFIR", "OEXP", "ACH"}
SYMBOL_REMAPS = {
    "FMET": "FMST",
    "FMST": "FMET",
    "SPLG": "SPYM",
    "SPYM": "SPLG",
}
BUCKET_ORDER = [
    "symbol drift / ticker remap",
    "date/key drift",
    "quantity mismatch / over-close",
    "penny rounding differences",
    "material stock notional differences",
    "material option notional differences",
    "missing side / key",
]

sys.path.insert(0, str(BACKEND_ROOT))

from app.engine.reconstructor import FillInput, reconstruct  # noqa: E402

TradeKey = tuple[str, str, str, str, str, str, str]


@dataclass
class AccountInfo:
    id_raw: str
    id_uuid: uuid.UUID
    name: str
    type: str
    last4: str

    @property
    def label(self) -> str:
        return f"{self.name} {self.last4}".strip()


@dataclass
class ComparisonMismatch:
    key: TradeKey
    csv_qty: Decimal
    db_qty: Decimal
    csv_notional: Decimal
    db_notional: Decimal
    bucket: str
    note: str


@dataclass
class CsvComparisonSummary:
    title: str
    scope_label: str
    path: str
    account_labels: list[str]
    min_date: str
    max_date: str
    dated_rows: int
    executable_rows: int
    ignored_code_counts: Counter[str]
    db_fill_rows: int
    csv_key_count: int
    db_key_count: int
    exact_match_count: int
    mismatch_count: int
    mismatches: list[ComparisonMismatch]
    overlap_closed_pnl: Decimal
    after_overlap_trade_count: int
    after_overlap_closed_pnl: Decimal


def money(value: Decimal | float | int | None) -> str:
    if value is None:
        return "-"
    quantized = Decimal(str(value)).quantize(Decimal("0.01"))
    return f"${quantized:,.2f}"


def fmt_decimal(value: Decimal | float | int | None, places: str = "0.00") -> str:
    if value is None:
        return "-"
    return str(Decimal(str(value)).quantize(Decimal(places)))


def fmt_compact_decimal(value: Decimal | float | int | None) -> str:
    if value is None:
        return "-"
    normalized = Decimal(str(value)).quantize(Decimal("0.000001"))
    text = format(normalized, "f").rstrip("0").rstrip(".")
    return text or "0"


def md_table(headers: list[str], rows: Iterable[Iterable[object]]) -> str:
    materialized = [[str(cell) for cell in row] for row in rows]
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in materialized:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def normalize_price(value: str) -> Decimal:
    cleaned = value.replace("$", "").replace(",", "").replace("(", "-").replace(")", "").strip()
    return Decimal(cleaned or "0")


def load_accounts(con: sqlite3.Connection) -> dict[str, AccountInfo]:
    rows = con.execute(
        """
        SELECT id, name, type, last4
        FROM account
        ORDER BY type, last4, name
        """
    ).fetchall()
    return {
        row["id"]: AccountInfo(
            id_raw=row["id"],
            id_uuid=uuid.UUID(row["id"]),
            name=row["name"],
            type=row["type"],
            last4=row["last4"],
        )
        for row in rows
    }


def get_account_by_last4(accounts: dict[str, AccountInfo], last4: str) -> AccountInfo | None:
    for account in accounts.values():
        if account.last4 == last4:
            return account
    return None


def get_accounts_by_type(accounts: dict[str, AccountInfo], account_type: str) -> list[AccountInfo]:
    return [account for account in accounts.values() if account.type == account_type]


def get_dashboard_metrics(con: sqlite3.Connection) -> dict[str, Decimal]:
    row = con.execute(
        """
        SELECT
            COALESCE(SUM(CASE WHEN status IN ('closed', 'expired') THEN realized_pnl END), 0) AS dashboard_total,
            COALESCE(SUM(realized_pnl), 0) AS realized_any_status,
            COALESCE(SUM(CASE WHEN status = 'open' THEN realized_pnl END), 0) AS open_realized,
            COALESCE(SUM(CASE WHEN status = 'open' THEN total_premium_paid END), 0) AS open_trade_basis
        FROM trade
        """
    ).fetchone()
    return {
        "dashboard_total": Decimal(str(row["dashboard_total"])),
        "realized_any_status": Decimal(str(row["realized_any_status"])),
        "open_realized": Decimal(str(row["open_realized"])),
        "open_trade_basis": Decimal(str(row["open_trade_basis"])),
    }


def get_account_coverage(con: sqlite3.Connection) -> list[sqlite3.Row]:
    return con.execute(
        """
        WITH fill_summary AS (
            SELECT
                account_id,
                MIN(CASE WHEN raw_email_id NOT LIKE 'manual:%' THEN executed_at END) AS first_non_manual_fill,
                MAX(CASE WHEN raw_email_id NOT LIKE 'manual:%' THEN executed_at END) AS last_non_manual_fill,
                COUNT(CASE WHEN raw_email_id NOT LIKE 'manual:%' THEN 1 END) AS non_manual_fill_count,
                COUNT(CASE WHEN raw_email_id LIKE 'manual:%' THEN 1 END) AS manual_fill_count
            FROM fill
            GROUP BY account_id
        ),
        trade_summary AS (
            SELECT
                account_id,
                COALESCE(SUM(CASE WHEN status IN ('closed', 'expired') THEN realized_pnl END), 0) AS closed_expired_pnl,
                COALESCE(SUM(realized_pnl), 0) AS realized_any_status,
                COALESCE(SUM(CASE WHEN status = 'open' THEN realized_pnl END), 0) AS open_realized_component,
                COUNT(CASE WHEN status = 'open' THEN 1 END) AS open_trade_count,
                COALESCE(SUM(CASE WHEN status = 'open' THEN total_premium_paid END), 0) AS open_trade_basis
            FROM trade
            GROUP BY account_id
        )
        SELECT
            a.id,
            a.name,
            a.type,
            a.last4,
            fs.first_non_manual_fill,
            fs.last_non_manual_fill,
            COALESCE(fs.non_manual_fill_count, 0) AS non_manual_fill_count,
            COALESCE(fs.manual_fill_count, 0) AS manual_fill_count,
            COALESCE(ts.closed_expired_pnl, 0) AS closed_expired_pnl,
            COALESCE(ts.realized_any_status, 0) AS realized_any_status,
            COALESCE(ts.open_realized_component, 0) AS open_realized_component,
            COALESCE(ts.open_trade_count, 0) AS open_trade_count,
            COALESCE(ts.open_trade_basis, 0) AS open_trade_basis
        FROM account a
        LEFT JOIN fill_summary fs ON fs.account_id = a.id
        LEFT JOIN trade_summary ts ON ts.account_id = a.id
        ORDER BY a.type, a.last4, a.name
        """
    ).fetchall()


def get_monthly_closed_pnl(con: sqlite3.Connection) -> dict[str, dict[str, Decimal]]:
    rows = con.execute(
        """
        SELECT
            strftime('%Y-%m', t.closed_at) AS ym,
            a.last4,
            COALESCE(SUM(t.realized_pnl), 0) AS pnl
        FROM trade t
        JOIN account a ON a.id = t.account_id
        WHERE t.status IN ('closed', 'expired') AND t.closed_at IS NOT NULL
        GROUP BY ym, a.last4
        ORDER BY ym, a.last4
        """
    ).fetchall()
    data: dict[str, dict[str, Decimal]] = defaultdict(dict)
    for row in rows:
        data[row["ym"]][row["last4"]] = Decimal(str(row["pnl"]))
    return data


def get_monthly_cashflow(con: sqlite3.Connection) -> dict[str, dict[str, Decimal]]:
    rows = con.execute(
        """
        SELECT
            strftime('%Y-%m', executed_at) AS ym,
            a.last4,
            COALESCE(SUM(
                CASE WHEN side IN ('sell_to_close', 'sell')
                THEN contracts * price
                ELSE -contracts * price
                END
            ), 0) AS net_trade_cashflow
        FROM fill f
        JOIN account a ON a.id = f.account_id
        GROUP BY ym, a.last4
        ORDER BY ym, a.last4
        """
    ).fetchall()
    data: dict[str, dict[str, Decimal]] = defaultdict(dict)
    for row in rows:
        data[row["ym"]][row["last4"]] = Decimal(str(row["net_trade_cashflow"]))
    return data


def get_largest_contributors(con: sqlite3.Connection, ascending: bool, limit: int = 10) -> list[sqlite3.Row]:
    direction = "ASC" if ascending else "DESC"
    return con.execute(
        f"""
        SELECT
            a.name,
            a.last4,
            t.ticker,
            t.instrument_type,
            COALESCE(SUM(t.realized_pnl), 0) AS pnl,
            COUNT(*) AS trades
        FROM trade t
        JOIN account a ON a.id = t.account_id
        WHERE t.status IN ('closed', 'expired')
        GROUP BY a.id, a.name, a.last4, t.ticker, t.instrument_type
        ORDER BY pnl {direction}
        LIMIT ?
        """,
        (limit,),
    ).fetchall()


def load_fill_inputs(con: sqlite3.Connection) -> list[FillInput]:
    rows = con.execute(
        """
        SELECT
            id,
            account_id,
            ticker,
            instrument_type,
            side,
            contracts,
            price,
            executed_at,
            option_type,
            strike,
            expiration
        FROM fill
        ORDER BY executed_at
        """
    ).fetchall()
    fills: list[FillInput] = []
    for row in rows:
        fills.append(
            FillInput(
                id=uuid.UUID(row["id"]),
                account_id=uuid.UUID(row["account_id"]),
                ticker=row["ticker"],
                instrument_type=row["instrument_type"],
                side=row["side"],
                contracts=Decimal(str(row["contracts"])),
                price=Decimal(str(row["price"])),
                executed_at=datetime.fromisoformat(row["executed_at"]),
                option_type=row["option_type"],
                strike=Decimal(str(row["strike"])) if row["strike"] is not None else None,
                expiration=date.fromisoformat(row["expiration"]) if row["expiration"] else None,
            )
        )
    return fills


def get_anomaly_details(con: sqlite3.Connection, accounts: dict[str, AccountInfo]) -> dict[str, object]:
    fill_rows = con.execute(
        """
        SELECT
            id,
            account_id,
            ticker,
            instrument_type,
            side,
            contracts,
            price,
            executed_at,
            option_type,
            strike,
            expiration,
            raw_email_id
        FROM fill
        ORDER BY executed_at
        """
    ).fetchall()
    fill_inputs = load_fill_inputs(con)
    result = reconstruct(fill_inputs)

    fill_map = {str(uuid.UUID(row["id"])): row for row in fill_rows}
    summary: dict[tuple[str, str, str], dict[str, object]] = defaultdict(
        lambda: {"count": 0, "notional": Decimal("0")}
    )
    stock_rows: list[dict[str, object]] = []
    option_rows: list[dict[str, object]] = []

    for message in result.anomalies:
        match = re.search(r"fill ([0-9a-f-]{36})", message)
        if not match:
            continue
        fill_id = match.group(1)
        row = fill_map[fill_id]
        account = accounts[row["account_id"]]
        notional = Decimal(str(row["contracts"])) * Decimal(str(row["price"]))
        kind = "orphaned" if message.startswith("Orphaned") else "over_close"
        key = (row["instrument_type"], row["side"], kind)
        summary[key]["count"] = int(summary[key]["count"]) + 1
        summary[key]["notional"] = Decimal(str(summary[key]["notional"])) + notional

        detail = {
            "executed_at": row["executed_at"],
            "account": account.label,
            "ticker": row["ticker"],
            "side": row["side"],
            "contracts": Decimal(str(row["contracts"])),
            "price": Decimal(str(row["price"])),
            "notional": notional,
            "message": message,
            "issue": "Orphaned close" if kind == "orphaned" else "Over-close",
        }
        if row["instrument_type"] == "stock":
            stock_rows.append(detail)
        else:
            detail["option_type"] = row["option_type"]
            detail["strike"] = Decimal(str(row["strike"])) if row["strike"] is not None else None
            detail["expiration"] = row["expiration"]
            option_rows.append(detail)

    stock_rows.sort(key=lambda row: row["executed_at"])
    option_rows.sort(key=lambda row: row["executed_at"])

    return {
        "count": len(result.anomalies),
        "summary": summary,
        "stock_rows": stock_rows,
        "option_rows": option_rows,
    }


def parse_csv_activity(csv_path: Path) -> tuple[list[dict[str, str]], list[dict[str, str]], Counter[str], date, date]:
    with csv_path.open(newline="", encoding="utf-8-sig") as handle:
        rows = [row for row in csv.DictReader(handle) if (row.get("Activity Date") or "").strip()]

    if not rows:
        raise ValueError(f"No dated rows found in {csv_path}")

    dates = [datetime.strptime(row["Activity Date"], "%m/%d/%Y").date() for row in rows]
    executable_rows = [row for row in rows if row["Trans Code"] in EXECUTABLE_TRADE_CODES]
    ignored_code_counts = Counter(
        row["Trans Code"]
        for row in rows
        if row["Trans Code"] not in EXECUTABLE_TRADE_CODES
    )
    return rows, executable_rows, ignored_code_counts, min(dates), max(dates)


def aggregate_csv_rows(executable_rows: list[dict[str, str]]) -> dict[TradeKey, dict[str, Decimal]]:
    csv_agg: dict[TradeKey, dict[str, Decimal]] = defaultdict(
        lambda: {"qty": Decimal("0"), "notional": Decimal("0")}
    )

    for row in executable_rows:
        activity_date = datetime.strptime(row["Activity Date"], "%m/%d/%Y").date().isoformat()
        code = row["Trans Code"]
        description = (row["Description"] or "").replace("\n", " ").strip()
        quantity = normalize_price(row["Quantity"])
        instrument = (row["Instrument"] or "").strip().upper()

        if code in {"BTO", "STC"}:
            ticker, expiration_raw, option_type, strike_raw = description.split(" ", 3)
            expiration = datetime.strptime(expiration_raw, "%m/%d/%Y").date().isoformat()
            option_type = option_type.lower()
            strike = fmt_decimal(
                normalize_price(
                    strike_raw.replace("Put", "").replace("Call", "").replace("$", "")
                ),
                "0.00",
            )
            side = "buy_to_open" if code == "BTO" else "sell_to_close"
            price = normalize_price(row["Price"]) * Decimal("100")
            key: TradeKey = (activity_date, ticker, "option", side, option_type, strike, expiration)
        else:
            side = code.lower()
            price = normalize_price(row["Price"])
            key = (activity_date, instrument, "stock", side, "", "", "")

        csv_agg[key]["qty"] += quantity
        csv_agg[key]["notional"] += quantity * price

    return csv_agg


def aggregate_db_fills(
    con: sqlite3.Connection,
    account_ids: list[str],
    min_date: str,
    max_date: str,
) -> tuple[list[sqlite3.Row], dict[TradeKey, dict[str, Decimal]]]:
    placeholders = ",".join("?" for _ in account_ids)
    rows = con.execute(
        f"""
        SELECT
            date(executed_at) AS activity_date,
            ticker,
            instrument_type,
            side,
            contracts,
            price,
            COALESCE(option_type, '') AS option_type,
            COALESCE(strike, '') AS strike,
            COALESCE(expiration, '') AS expiration
        FROM fill
        WHERE account_id IN ({placeholders})
          AND date(executed_at) BETWEEN ? AND ?
        ORDER BY executed_at
        """,
        (*account_ids, min_date, max_date),
    ).fetchall()

    db_agg: dict[TradeKey, dict[str, Decimal]] = defaultdict(
        lambda: {"qty": Decimal("0"), "notional": Decimal("0")}
    )
    for row in rows:
        strike = fmt_decimal(row["strike"], "0.00") if row["strike"] != "" else ""
        key: TradeKey = (
            row["activity_date"],
            row["ticker"],
            row["instrument_type"],
            row["side"],
            row["option_type"],
            strike,
            row["expiration"],
        )
        quantity = Decimal(str(row["contracts"]))
        price = Decimal(str(row["price"]))
        db_agg[key]["qty"] += quantity
        db_agg[key]["notional"] += quantity * price

    return rows, db_agg


def shift_key_date(key: TradeKey, delta_days: int) -> TradeKey:
    shifted = date.fromisoformat(key[0]) + timedelta(days=delta_days)
    return (shifted.isoformat(), key[1], key[2], key[3], key[4], key[5], key[6])


def format_trade_key(key: TradeKey) -> str:
    activity_date, ticker, instrument_type, side, option_type, strike, expiration = key
    if instrument_type == "option":
        contract = f"{option_type} {strike} exp {expiration}"
    else:
        contract = "stock"
    return f"{activity_date} {ticker} {instrument_type} {side} {contract}"


def format_mismatch(mismatch: ComparisonMismatch) -> str:
    return (
        f"{format_trade_key(mismatch.key)} | {mismatch.bucket} | "
        f"csv qty={fmt_compact_decimal(mismatch.csv_qty)} db qty={fmt_compact_decimal(mismatch.db_qty)} "
        f"csv notional={fmt_compact_decimal(mismatch.csv_notional)} "
        f"db notional={fmt_compact_decimal(mismatch.db_notional)}"
    )


def classify_mismatch(
    key: TradeKey,
    csv_qty: Decimal,
    db_qty: Decimal,
    csv_notional: Decimal,
    db_notional: Decimal,
    csv_agg: dict[TradeKey, dict[str, Decimal]],
    db_agg: dict[TradeKey, dict[str, Decimal]],
) -> tuple[str, str]:
    activity_date, ticker, instrument_type, side, option_type, strike, expiration = key
    diff = abs(csv_notional - db_notional)

    if csv_qty and db_qty and csv_qty != db_qty:
        return "quantity mismatch / over-close", "Same normalized key exists in both sources, but the filled quantity differs."

    if (csv_qty == 0) != (db_qty == 0):
        remapped_ticker = SYMBOL_REMAPS.get(ticker)
        other_agg = csv_agg if csv_qty == 0 else db_agg
        if remapped_ticker is not None:
            remapped_key = (activity_date, remapped_ticker, instrument_type, side, option_type, strike, expiration)
            if remapped_key in other_agg:
                return "symbol drift / ticker remap", f"{ticker} lines up with {remapped_ticker} under the same economic key."

        for delta_days in (-1, 1):
            shifted_key = shift_key_date(key, delta_days)
            if shifted_key in other_agg:
                shifted_date = date.fromisoformat(activity_date) + timedelta(days=delta_days)
                return "date/key drift", f"{ticker} lines up on {shifted_date.isoformat()} instead of {activity_date}."

        return "missing side / key", "The normalized key appears in only one source."

    if diff <= Decimal("0.02"):
        return "penny rounding differences", "Quantities match; only a penny-scale notional delta remains."

    if instrument_type == "stock":
        return "material stock notional differences", "Stock quantities match, but the notional differs by more than two cents."

    return "material option notional differences", "Option quantities match, but the notional differs by more than two cents."


def summarize_csv_against_accounts(
    csv_path: Path,
    con: sqlite3.Connection,
    title: str,
    scope_label: str,
    account_ids: list[str],
    account_labels: list[str],
) -> CsvComparisonSummary | None:
    if not account_ids or not csv_path.exists():
        return None

    rows, executable_rows, ignored_code_counts, min_date, max_date = parse_csv_activity(csv_path)
    csv_agg = aggregate_csv_rows(executable_rows)
    db_rows, db_agg = aggregate_db_fills(con, account_ids, min_date.isoformat(), max_date.isoformat())

    union_keys = sorted(set(csv_agg) | set(db_agg))
    mismatches: list[ComparisonMismatch] = []
    exact_match_count = 0
    for key in union_keys:
        csv_qty = csv_agg.get(key, {}).get("qty", Decimal("0"))
        db_qty = db_agg.get(key, {}).get("qty", Decimal("0"))
        csv_notional = csv_agg.get(key, {}).get("notional", Decimal("0"))
        db_notional = db_agg.get(key, {}).get("notional", Decimal("0"))
        if csv_qty == db_qty and csv_notional == db_notional:
            exact_match_count += 1
            continue

        bucket, note = classify_mismatch(
            key,
            csv_qty,
            db_qty,
            csv_notional,
            db_notional,
            csv_agg,
            db_agg,
        )
        mismatches.append(
            ComparisonMismatch(
                key=key,
                csv_qty=csv_qty,
                db_qty=db_qty,
                csv_notional=csv_notional,
                db_notional=db_notional,
                bucket=bucket,
                note=note,
            )
        )

    placeholders = ",".join("?" for _ in account_ids)
    overlap_closed_pnl = con.execute(
        f"""
        SELECT COALESCE(SUM(realized_pnl), 0)
        FROM trade
        WHERE account_id IN ({placeholders})
          AND status IN ('closed', 'expired')
          AND date(closed_at) <= ?
        """,
        (*account_ids, max_date.isoformat()),
    ).fetchone()[0]
    after_overlap = con.execute(
        f"""
        SELECT COUNT(*), COALESCE(SUM(realized_pnl), 0)
        FROM trade
        WHERE account_id IN ({placeholders})
          AND status IN ('closed', 'expired')
          AND date(closed_at) > ?
        """,
        (*account_ids, max_date.isoformat()),
    ).fetchone()

    return CsvComparisonSummary(
        title=title,
        scope_label=scope_label,
        path=str(csv_path.relative_to(REPO_ROOT)),
        account_labels=account_labels,
        min_date=min_date.isoformat(),
        max_date=max_date.isoformat(),
        dated_rows=len(rows),
        executable_rows=len(executable_rows),
        ignored_code_counts=ignored_code_counts,
        db_fill_rows=len(db_rows),
        csv_key_count=len(csv_agg),
        db_key_count=len(db_agg),
        exact_match_count=exact_match_count,
        mismatch_count=len(mismatches),
        mismatches=mismatches,
        overlap_closed_pnl=Decimal(str(overlap_closed_pnl)),
        after_overlap_trade_count=int(after_overlap[0]),
        after_overlap_closed_pnl=Decimal(str(after_overlap[1])),
    )


def format_ignored_codes(ignored_code_counts: Counter[str]) -> str:
    if not ignored_code_counts:
        return "-"
    return ", ".join(f"{code}: {ignored_code_counts[code]}" for code in sorted(ignored_code_counts))


def build_bucket_rows(summary: CsvComparisonSummary) -> list[tuple[str, int, str]]:
    counts = Counter(mismatch.bucket for mismatch in summary.mismatches)
    sample_by_bucket: dict[str, str] = {}
    for mismatch in summary.mismatches:
        sample_by_bucket.setdefault(mismatch.bucket, format_trade_key(mismatch.key))

    rows: list[tuple[str, int, str]] = []
    for bucket in BUCKET_ORDER:
        if bucket in counts:
            rows.append((bucket, counts[bucket], sample_by_bucket[bucket]))
    for bucket in sorted(counts):
        if bucket not in BUCKET_ORDER:
            rows.append((bucket, counts[bucket], sample_by_bucket[bucket]))
    return rows


def build_csv_comparison_section(summary: CsvComparisonSummary) -> list[str]:
    verdict = (
        "Exact match across the overlap window."
        if summary.mismatch_count == 0
        else "Near match. Most keys line up, but residual discrepancies remain and are bucketed below."
    )

    lines = [
        f"## {summary.title}",
        "",
        md_table(
            ["Field", "Value"],
            [
                ("Path", summary.path),
                ("Account scope", summary.scope_label),
                ("DB accounts combined", ", ".join(summary.account_labels) or "-"),
                ("CSV date range", f"{summary.min_date} to {summary.max_date}"),
                ("Rows with dates", summary.dated_rows),
                ("Executable trade rows", summary.executable_rows),
                ("Ignored non-trade rows", format_ignored_codes(summary.ignored_code_counts)),
                ("DB fill rows in overlap", summary.db_fill_rows),
                ("CSV normalized fill keys", summary.csv_key_count),
                ("DB normalized fill keys", summary.db_key_count),
                ("Exact-match keys", summary.exact_match_count),
                ("Mismatch keys", summary.mismatch_count),
                ("Closed/expired P&L through CSV max date", money(summary.overlap_closed_pnl)),
                (
                    "Closed/expired trades after CSV max date",
                    f"{summary.after_overlap_trade_count} trade(s), {money(summary.after_overlap_closed_pnl)}",
                ),
                ("Verdict", verdict),
            ],
        ),
        "",
    ]

    if summary.mismatches:
        lines.extend(
            [
                "### Mismatch Buckets",
                "",
                md_table(
                    ["Bucket", "Count", "Example key"],
                    build_bucket_rows(summary),
                ),
                "",
                "### Mismatch Examples",
                "",
                *[f"- `{format_mismatch(mismatch)}`" for mismatch in summary.mismatches[:10]],
                "",
            ]
        )

    return lines


def build_default_csv_summaries(
    con: sqlite3.Connection,
    accounts: dict[str, AccountInfo],
) -> list[CsvComparisonSummary]:
    summaries: list[CsvComparisonSummary] = []

    individual_account = get_account_by_last4(accounts, "1113")
    if individual_account is not None:
        summary = summarize_csv_against_accounts(
            DEFAULT_INDIVIDUAL_CSV_PATH,
            con,
            title="Current Robinhood CSV",
            scope_label="Individual 1113",
            account_ids=[individual_account.id_raw],
            account_labels=[individual_account.label],
        )
        if summary is not None:
            summaries.append(summary)

    roth_accounts = get_accounts_by_type(accounts, "roth_ira")
    roth_summary = summarize_csv_against_accounts(
        DEFAULT_ROTH_CSV_PATH,
        con,
        title="Roth Robinhood CSV",
        scope_label="Combined Roth IRA",
        account_ids=[account.id_raw for account in roth_accounts],
        account_labels=[account.label for account in roth_accounts],
    )
    if roth_summary is not None:
        summaries.append(roth_summary)

    return summaries


def resolve_requested_summaries(
    con: sqlite3.Connection,
    accounts: dict[str, AccountInfo],
    csv_path: Path | None,
    account_scope: str | None,
) -> list[CsvComparisonSummary]:
    if account_scope is None:
        return build_default_csv_summaries(con, accounts)

    if account_scope == "individual":
        individual_account = get_account_by_last4(accounts, "1113")
        if individual_account is None:
            return []
        path = csv_path or DEFAULT_INDIVIDUAL_CSV_PATH
        summary = summarize_csv_against_accounts(
            path,
            con,
            title="Requested Robinhood CSV Comparison",
            scope_label="Individual 1113",
            account_ids=[individual_account.id_raw],
            account_labels=[individual_account.label],
        )
        return [summary] if summary is not None else []

    roth_accounts = get_accounts_by_type(accounts, "roth_ira")
    path = csv_path or DEFAULT_ROTH_CSV_PATH
    summary = summarize_csv_against_accounts(
        path,
        con,
        title="Requested Robinhood CSV Comparison",
        scope_label="Combined Roth IRA",
        account_ids=[account.id_raw for account in roth_accounts],
        account_labels=[account.label for account in roth_accounts],
    )
    return [summary] if summary is not None else []


def build_report(csv_summaries: list[CsvComparisonSummary]) -> str:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    accounts = load_accounts(con)
    metrics = get_dashboard_metrics(con)
    account_rows = get_account_coverage(con)
    monthly_pnl = get_monthly_closed_pnl(con)
    monthly_cashflow = get_monthly_cashflow(con)
    anomalies = get_anomaly_details(con, accounts)
    winners = get_largest_contributors(con, ascending=False, limit=10)
    losers = get_largest_contributors(con, ascending=True, limit=10)

    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    months = sorted(
        ym for ym in set(monthly_pnl) | set(monthly_cashflow)
        if ym >= "2025-07"
    )

    lines: list[str] = [
        "# Reconciliation Report",
        "",
        f"Generated: `{generated_at}`",
        f"Database: `{DB_PATH.relative_to(REPO_ROOT)}`",
        "",
        "## Headline",
        "",
        md_table(
            ["Metric", "Amount", "Notes"],
            [
                ("Dashboard total_pnl", money(metrics["dashboard_total"]), "Closed + expired realized P&L only, matching /stats"),
                ("All realized P&L including open trades", money(metrics["realized_any_status"]), "Adds realized P&L already locked in on still-open positions"),
                ("Realized P&L hidden inside open trades", money(metrics["open_realized"]), "Currently excluded from dashboard because those trades are still open"),
                ("Open trade basis", money(metrics["open_trade_basis"]), "Current open positions are all stocks; mark-to-market is not in the DB"),
            ],
        ),
        "",
        "## Coverage By Account",
        "",
        md_table(
            ["Account", "Non-manual fills", "Non-manual range", "Manual fills", "Closed/expired P&L", "All realized", "Open realized", "Open trades", "Open basis"],
            [
                (
                    f"{row['name']} {row['last4']}".strip(),
                    row["non_manual_fill_count"],
                    f"{row['first_non_manual_fill'][:10]} to {row['last_non_manual_fill'][:10]}" if row["first_non_manual_fill"] and row["last_non_manual_fill"] else "-",
                    row["manual_fill_count"],
                    money(row["closed_expired_pnl"]),
                    money(row["realized_any_status"]),
                    money(row["open_realized_component"]),
                    row["open_trade_count"],
                    money(row["open_trade_basis"]),
                )
                for row in account_rows
            ],
        ),
        "",
    ]

    for csv_summary in csv_summaries:
        lines.extend(build_csv_comparison_section(csv_summary))

    anomaly_summary_rows = []
    for key in sorted(anomalies["summary"]):
        instrument_type, side, kind = key
        detail = anomalies["summary"][key]
        anomaly_summary_rows.append((instrument_type, side, kind, detail["count"], money(detail["notional"])))

    lines.extend(
        [
            "## Discrepancy Buckets",
            "",
            md_table(
                ["Bucket", "Count", "Amount", "Why it matters"],
                [
                    ("Orphaned or over-closed stock sells", sum(int(detail["count"]) for key, detail in anomalies["summary"].items() if key[0] == "stock"), money(sum(Decimal(str(detail["notional"])) for key, detail in anomalies["summary"].items() if key[0] == "stock")), "These sales have no matching opening buy in the DB, so their true realized P&L cannot be computed"),
                    ("Option close anomalies", sum(int(detail["count"]) for key, detail in anomalies["summary"].items() if key[0] == "option"), money(sum(Decimal(str(detail["notional"])) for key, detail in anomalies["summary"].items() if key[0] == "option")), "These option closes are orphaned or over-sized, so the realized P&L is only partially represented"),
                    ("Total anomalies", anomalies["count"], "-", "Any anomaly weakens broker-vs-app reconciliation until the missing source fills are backfilled"),
                ],
            ),
            "",
            "### Anomaly Breakdown",
            "",
            md_table(["Instrument", "Side", "Kind", "Count", "Gross notional"], anomaly_summary_rows),
            "",
            "### Unmatched Stock Sales",
            "",
            md_table(
                ["Date", "Account", "Ticker", "Shares", "Price", "Gross proceeds"],
                [(str(row["executed_at"])[:10], row["account"], row["ticker"], fmt_decimal(row["contracts"], "0.000000"), money(row["price"]), money(row["notional"])) for row in anomalies["stock_rows"]],
            ),
            "",
            "### Option Close Anomalies",
            "",
            md_table(
                ["Date", "Account", "Ticker", "Contracts", "Price", "Contract", "Issue"],
                [(str(row["executed_at"])[:10], row["account"], row["ticker"], fmt_decimal(row["contracts"], "0.000000"), money(row["price"]), f"{row['option_type']} {fmt_decimal(row['strike'], '0.00')} exp {row['expiration']}", row["issue"]) for row in anomalies["option_rows"]],
            ),
            "",
            "## Monthly Closed/Expired Realized P&L",
            "",
            md_table(
                ["Month", "Individual 1113", "Roth IRA 8267", "Total"],
                [(ym, money(monthly_pnl.get(ym, {}).get("1113", Decimal("0"))), money(monthly_pnl.get(ym, {}).get("8267", Decimal("0"))), money(monthly_pnl.get(ym, {}).get("1113", Decimal("0")) + monthly_pnl.get(ym, {}).get("8267", Decimal("0")))) for ym in months],
            ),
            "",
            "## Monthly Net Trade Cash Flow",
            "",
            md_table(
                ["Month", "Individual 1113", "Roth IRA 8267", "Total"],
                [(ym, money(monthly_cashflow.get(ym, {}).get("1113", Decimal("0"))), money(monthly_cashflow.get(ym, {}).get("8267", Decimal("0"))), money(monthly_cashflow.get(ym, {}).get("1113", Decimal("0")) + monthly_cashflow.get(ym, {}).get("8267", Decimal("0")))) for ym in months],
            ),
            "",
            "Net trade cash flow is not the same thing as realized P&L. It is useful here because it shows months with large cash exits or entries even when the reconstructor cannot fully match basis.",
            "",
            "## Largest Contributors",
            "",
            "### Biggest Winners",
            "",
            md_table(["Account", "Ticker", "Type", "Closed/expired P&L", "Trades"], [(f"{row['name']} {row['last4']}".strip(), row["ticker"], row["instrument_type"], money(row["pnl"]), row["trades"]) for row in winners]),
            "",
            "### Biggest Losers",
            "",
            md_table(["Account", "Ticker", "Type", "Closed/expired P&L", "Trades"], [(f"{row['name']} {row['last4']}".strip(), row["ticker"], row["instrument_type"], money(row["pnl"]), row["trades"]) for row in losers]),
            "",
            "## Takeaways",
            "",
            "- The dashboard number is not a broker-equity number. It is realized P&L on trades that the reconstructor considers closed or expired.",
            "- Unrealized stock P&L is definitely missing, but the larger reconciliation blocker is missing basis on orphaned stock sells.",
            "- The Roth CSV compares materially better when both `roth_ira` accounts are treated as one logical account.",
            "- Combined Roth still has residual discrepancy buckets: quantity mismatches, symbol drift, date drift, and small rounding deltas.",
            "",
            "## Suggested Next Steps",
            "",
            "1. Backfill or normalize the remaining Roth mismatch families before treating the CSV as a broker-perfect reconciliation source.",
            "2. Decide whether the blank-last4 Roth account should be merged or relabeled now that the Roth CSV clearly spans both DB accounts.",
            "3. Keep using the fill-level comparison rather than dashboard P&L when validating broker CSV imports.",
            "",
        ]
    )

    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a reconciliation report from the local trade journal DB.")
    parser.add_argument("--csv", type=Path, default=None, help="Optional CSV path for a targeted comparison run.")
    parser.add_argument("--account-scope", choices=["individual", "roth"], default=None, help="Optional account scope for a targeted comparison run.")
    parser.add_argument("--output", type=Path, default=None, help="Optional output path. Defaults to backend/reports with a scope-specific filename.")
    return parser.parse_args()


def default_output_path(account_scope: str | None) -> Path:
    if account_scope == "roth":
        return DEFAULT_OUTPUT_DIR / f"reconciliation_report_roth_{date.today().isoformat()}.md"
    if account_scope == "individual":
        return DEFAULT_OUTPUT_DIR / f"reconciliation_report_individual_{date.today().isoformat()}.md"
    return DEFAULT_OUTPUT_PATH


def main() -> None:
    args = parse_args()
    DEFAULT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    accounts = load_accounts(con)
    csv_summaries = resolve_requested_summaries(con, accounts, args.csv, args.account_scope)
    report = build_report(csv_summaries)

    output_path = args.output or default_output_path(args.account_scope)
    output_path.write_text(report, encoding="utf-8")
    print(output_path)


if __name__ == "__main__":
    main()
