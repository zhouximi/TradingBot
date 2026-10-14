#!/usr/bin/env python3
"""Incrementally sync Massive US stock daily bars into PostgreSQL.

The job is designed for launchd/cron and is safe to run repeatedly.  It uses
Massive's grouped daily endpoint (one HTTP request per date), maps only simple
Stooq symbols such as ``AAPL.US`` to ``AAPL``, and upserts bars under a separate
``massive`` provider.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import socket
import sys
import time
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

try:
    import psycopg
except ImportError:  # pragma: no cover - useful command-line error
    sys.exit("Missing dependency: install with 'python3 -m pip install psycopg[binary]'.")


DEFAULT_ENV_FILE = Path.home() / ".config" / "tradingbot" / "env"
API_BASE_URL = "https://api.massive.com"
SIMPLE_STOOQ_SYMBOL = re.compile(r"^([A-Z0-9]+)\.US$")
LOCK_NAME = "tradingbot.massive.daily_bar_sync"

SCHEMA_SQL = """
INSERT INTO provider (code, name)
VALUES ('massive', 'Massive')
ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name;

CREATE TABLE IF NOT EXISTS massive_daily_sync (
    trade_date       DATE PRIMARY KEY,
    downloaded_rows INTEGER NOT NULL CHECK (downloaded_rows >= 0),
    imported_rows   INTEGER NOT NULL CHECK (imported_rows >= 0),
    unmapped_rows   INTEGER NOT NULL CHECK (unmapped_rows >= 0),
    synced_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

UPSERT_SQL = """
INSERT INTO daily_bar (
    listing_id, provider_id, trade_date, period, source_time,
    open, high, low, close, volume, open_interest
)
SELECT
    ps.listing_id, %(provider_id)s, %(trade_date)s, 'D', NULL,
    b.open, b.high, b.low, b.close, b.volume, NULL
FROM massive_bar_batch b
JOIN provider_symbol ps
  ON ps.provider_id = %(provider_id)s
 AND ps.symbol = b.symbol
 AND (ps.valid_from IS NULL OR ps.valid_from <= %(trade_date)s)
 AND (ps.valid_to IS NULL OR ps.valid_to >= %(trade_date)s)
ON CONFLICT (listing_id, provider_id, trade_date, period) DO UPDATE SET
    source_time = EXCLUDED.source_time,
    open = EXCLUDED.open,
    high = EXCLUDED.high,
    low = EXCLUDED.low,
    close = EXCLUDED.close,
    volume = EXCLUDED.volume,
    open_interest = EXCLUDED.open_interest,
    updated_at = now()
"""


class SyncError(RuntimeError):
    """An expected error that should make the scheduled job retry later."""


def log(message: str) -> None:
    print(f"{datetime.now().astimezone().isoformat(timespec='seconds')} {message}", flush=True)


def load_env_file(path: Path) -> None:
    """Load a small shell-style KEY=VALUE file without executing it."""
    if not path.exists():
        return
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            raise SyncError(f"{path}:{line_number}: expected KEY=VALUE")
        key, value = line.split("=", 1)
        key = key.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            raise SyncError(f"{path}:{line_number}: invalid environment variable name")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ.setdefault(key, value)


def parse_iso_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected a date in YYYY-MM-DD format") from exc


def new_york_today() -> date:
    """Return New York's date using the system tz database (Python 3.8 compatible)."""
    previous_tz = os.environ.get("TZ")
    try:
        os.environ["TZ"] = "America/New_York"
        time.tzset()
        return date.fromtimestamp(time.time())
    finally:
        if previous_tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = previous_tz
        time.tzset()


def date_range(start: date, end: date) -> Iterable[date]:
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def retry_delay(error: HTTPError, attempt: int) -> float:
    retry_after = error.headers.get("Retry-After")
    if retry_after:
        try:
            return max(1.0, float(retry_after))
        except ValueError:
            pass
    return min(60.0, 2.0 ** attempt)


def fetch_grouped_daily(
    api_key: str,
    trade_date: date,
    *,
    include_otc: bool,
    timeout: float,
    retries: int,
) -> list[dict[str, Any]]:
    path = f"/v2/aggs/grouped/locale/us/market/stocks/{quote(trade_date.isoformat())}"
    query = urlencode({
        "adjusted": "true",
        "include_otc": str(include_otc).lower(),
        "apiKey": api_key,
    })
    # Never log this URL: the query string contains the API key.
    request = Request(
        f"{API_BASE_URL}{path}?{query}",
        headers={"Accept": "application/json", "User-Agent": "TradingBot/1.0"},
    )

    for attempt in range(retries + 1):
        try:
            with urlopen(request, timeout=timeout) as response:
                payload = json.load(response)
            if payload.get("status") not in {"OK", "DELAYED"}:
                raise SyncError(
                    f"Massive returned status {payload.get('status')!r} for {trade_date}"
                )
            results = payload.get("results", [])
            if not isinstance(results, list):
                raise SyncError(f"Massive returned invalid results for {trade_date}")
            return results
        except HTTPError as exc:
            retryable = exc.code == 429 or 500 <= exc.code < 600
            if retryable and attempt < retries:
                delay = retry_delay(exc, attempt)
                log(f"HTTP {exc.code} for {trade_date}; retrying in {delay:g}s")
                time.sleep(delay)
                continue
            raise SyncError(f"Massive HTTP {exc.code} for {trade_date}") from exc
        except (URLError, TimeoutError, socket.timeout, json.JSONDecodeError) as exc:
            if attempt < retries:
                delay = min(60.0, 2.0 ** attempt)
                log(f"network error for {trade_date}; retrying in {delay:g}s: {exc}")
                time.sleep(delay)
                continue
            raise SyncError(f"network error for {trade_date}: {exc}") from exc

    raise AssertionError("unreachable")


def decimal_field(row: dict[str, Any], key: str, symbol: str) -> Decimal:
    try:
        value = Decimal(str(row[key]))
    except (KeyError, InvalidOperation, ValueError) as exc:
        raise ValueError(f"{symbol}: invalid {key}") from exc
    if not value.is_finite():
        raise ValueError(f"{symbol}: non-finite {key}")
    return value


def parse_bar(row: dict[str, Any]) -> tuple[str, Decimal, Decimal, Decimal, Decimal, Decimal]:
    symbol = str(row.get("T", "")).strip().upper()
    if not symbol:
        raise ValueError("bar has no ticker")
    open_price = decimal_field(row, "o", symbol)
    high = decimal_field(row, "h", symbol)
    low = decimal_field(row, "l", symbol)
    close = decimal_field(row, "c", symbol)
    volume = decimal_field(row, "v", symbol)
    if min(open_price, high, low, close, volume) < 0:
        raise ValueError(f"{symbol}: negative OHLCV value")
    if high < max(open_price, low, close) or low > min(open_price, high, close):
        raise ValueError(f"{symbol}: inconsistent OHLC range")
    return symbol, open_price, high, low, close, volume


def ensure_schema(connection: psycopg.Connection) -> int:
    with connection.transaction():
        connection.execute(SCHEMA_SQL)
        provider_id = connection.execute(
            "SELECT id FROM provider WHERE code = 'massive'"
        ).fetchone()[0]
    return provider_id


def create_simple_symbol_mappings(connection: psycopg.Connection, provider_id: int) -> int:
    """Map only unambiguous CODE.US Stooq symbols to Massive CODE symbols."""
    stooq_rows = connection.execute(
        """SELECT ps.listing_id, ps.symbol
           FROM provider_symbol ps
           JOIN provider p ON p.id = ps.provider_id
           WHERE p.code = 'stooq'"""
    ).fetchall()
    candidates = []
    for listing_id, stooq_symbol in stooq_rows:
        match = SIMPLE_STOOQ_SYMBOL.fullmatch(stooq_symbol.upper())
        if match:
            candidates.append((provider_id, listing_id, match.group(1)))
    if not candidates:
        return 0
    before = connection.execute(
        "SELECT count(*) FROM provider_symbol WHERE provider_id = %s", (provider_id,)
    ).fetchone()[0]
    with connection.transaction():
        with connection.cursor() as cursor:
            cursor.executemany(
                """INSERT INTO provider_symbol (provider_id, listing_id, symbol)
                   VALUES (%s, %s, %s)
                   ON CONFLICT (provider_id, symbol) DO NOTHING""",
                candidates,
            )
    after = connection.execute(
        "SELECT count(*) FROM provider_symbol WHERE provider_id = %s", (provider_id,)
    ).fetchone()[0]
    return after - before


def import_date(
    connection: psycopg.Connection,
    provider_id: int,
    trade_date: date,
    raw_rows: list[dict[str, Any]],
) -> tuple[int, int, int]:
    parsed_by_symbol = {}
    ambiguous_symbols = set()
    skipped = 0
    for row in raw_rows:
        try:
            bar = parse_bar(row)
        except ValueError as exc:
            skipped += 1
            print(f"warning: {trade_date}: {exc}", file=sys.stderr, flush=True)
            continue

        symbol = bar[0]
        if symbol in ambiguous_symbols:
            skipped += 1
            continue
        previous = parsed_by_symbol.get(symbol)
        if previous is None:
            parsed_by_symbol[symbol] = bar
        elif previous == bar:
            # A byte-for-byte duplicate is harmless; import it once.
            skipped += 1
        else:
            # A ticker alone cannot distinguish these records.  Importing
            # either one could attach another security's prices to a listing.
            del parsed_by_symbol[symbol]
            ambiguous_symbols.add(symbol)
            skipped += 2
            print(
                f"warning: {trade_date}: conflicting duplicate ticker {symbol}; "
                "all rows for this ticker were skipped",
                file=sys.stderr,
                flush=True,
            )

    parsed = list(parsed_by_symbol.values())

    with connection.transaction():
        connection.execute("""
            CREATE TEMP TABLE IF NOT EXISTS massive_bar_batch (
                symbol TEXT PRIMARY KEY,
                open NUMERIC NOT NULL,
                high NUMERIC NOT NULL,
                low NUMERIC NOT NULL,
                close NUMERIC NOT NULL,
                volume NUMERIC NOT NULL
            ) ON COMMIT PRESERVE ROWS
        """)
        connection.execute("TRUNCATE massive_bar_batch")
        if parsed:
            with connection.cursor().copy(
                "COPY massive_bar_batch (symbol, open, high, low, close, volume) FROM STDIN"
            ) as copy:
                for row in parsed:
                    copy.write_row(row)

        mapped = connection.execute(
            """SELECT count(*)
               FROM massive_bar_batch b
               JOIN provider_symbol ps
                 ON ps.provider_id = %s AND ps.symbol = b.symbol
                AND (ps.valid_from IS NULL OR ps.valid_from <= %s)
                AND (ps.valid_to IS NULL OR ps.valid_to >= %s)""",
            (provider_id, trade_date, trade_date),
        ).fetchone()[0]
        connection.execute(UPSERT_SQL, {"provider_id": provider_id, "trade_date": trade_date})
        unmapped = len(parsed) - mapped
        connection.execute(
            """INSERT INTO massive_daily_sync
                   (trade_date, downloaded_rows, imported_rows, unmapped_rows, synced_at)
               VALUES (%s, %s, %s, %s, now())
               ON CONFLICT (trade_date) DO UPDATE SET
                   downloaded_rows = EXCLUDED.downloaded_rows,
                   imported_rows = EXCLUDED.imported_rows,
                   unmapped_rows = EXCLUDED.unmapped_rows,
                   synced_at = now()""",
            (trade_date, len(raw_rows), mapped, unmapped),
        )
    return mapped, unmapped, skipped


def default_start_date(connection: psycopg.Connection, target: date, lookback_days: int) -> date:
    latest = connection.execute("SELECT max(trade_date) FROM massive_daily_sync").fetchone()[0]
    overlap_start = target - timedelta(days=lookback_days - 1)
    if latest is None:
        return overlap_start
    return min(latest + timedelta(days=1), overlap_start)


def completed_dates(
    connection: psycopg.Connection,
    provider_id: int,
    start: date,
    end: date,
) -> set[date]:
    """Return dates whose sync marker agrees with the stored bar count."""
    rows = connection.execute(
        """SELECT s.trade_date
           FROM massive_daily_sync s
           WHERE s.trade_date BETWEEN %s AND %s
             AND s.imported_rows = (
                 SELECT count(*)
                 FROM daily_bar b
                 WHERE b.provider_id = %s
                   AND b.trade_date = s.trade_date
                   AND b.period = 'D'
             )""",
        (start, end, provider_id),
    ).fetchall()
    return {row[0] for row in rows}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Update PostgreSQL daily bars from Massive's grouped US stocks API"
    )
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument("--database-url", help="defaults to DATABASE_URL or local dbname=tradingbot")
    parser.add_argument("--from-date", type=parse_iso_date, help="first date to sync (YYYY-MM-DD)")
    parser.add_argument("--to-date", type=parse_iso_date, help="last date; defaults to yesterday in New York")
    parser.add_argument("--lookback-days", type=int, default=7, help="days rechecked each run (default: 7)")
    parser.add_argument("--include-otc", action="store_true")
    parser.add_argument(
        "--skip-synced",
        action="store_true",
        help="do not call Massive for dates already committed with the expected bar count",
    )
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--retries", type=int, default=4)
    parser.add_argument(
        "--request-interval",
        type=float,
        default=13.0,
        help="minimum seconds between dates; 13s is safe for the free 5 requests/minute plan",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.lookback_days < 1:
        parser.error("--lookback-days must be at least 1")
    if args.timeout <= 0 or args.retries < 0 or args.request_interval < 0:
        parser.error("timeout and request interval must be positive; retries cannot be negative")

    try:
        load_env_file(args.env_file.expanduser())
        api_key = os.getenv("MASSIVE_API_KEY")
        if not api_key:
            raise SyncError(f"MASSIVE_API_KEY is missing from {args.env_file.expanduser()}")
        database_url = args.database_url or os.getenv("DATABASE_URL") or "dbname=tradingbot"
        target = args.to_date or (new_york_today() - timedelta(days=1))

        with psycopg.connect(database_url, autocommit=True, connect_timeout=10) as connection:
            locked = connection.execute(
                "SELECT pg_try_advisory_lock(hashtext(%s))", (LOCK_NAME,)
            ).fetchone()[0]
            if not locked:
                log("another Massive daily sync is already running; exiting")
                return 0

            provider_id = ensure_schema(connection)
            new_mappings = create_simple_symbol_mappings(connection, provider_id)
            if new_mappings:
                log(f"created {new_mappings} simple Stooq-to-Massive symbol mappings")

            start = args.from_date or default_start_date(
                connection, target, args.lookback_days
            )
            if start > target:
                log(f"nothing to sync: start {start} is after target {target}")
                return 0

            dates = list(date_range(start, target))
            if args.skip_synced:
                completed = completed_dates(connection, provider_id, start, target)
                dates = [trade_date for trade_date in dates if trade_date not in completed]
                if not dates:
                    log(f"all dates from {start} through {target} are already synced; exiting")
                    return 0
            log(f"syncing {len(dates)} date(s), {start} through {target}")
            for index, trade_date in enumerate(dates):
                raw_rows = fetch_grouped_daily(
                    api_key,
                    trade_date,
                    include_otc=args.include_otc,
                    timeout=args.timeout,
                    retries=args.retries,
                )
                mapped, unmapped, skipped = import_date(
                    connection, provider_id, trade_date, raw_rows
                )
                log(
                    f"{trade_date}: downloaded={len(raw_rows)}, imported={mapped}, "
                    f"unmapped={unmapped}, skipped={skipped}"
                )
                if index + 1 < len(dates) and args.request_interval:
                    time.sleep(args.request_interval)
        return 0
    except (OSError, psycopg.Error, SyncError) as exc:
        print(f"Massive daily sync failed: {exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
