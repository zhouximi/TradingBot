#!/usr/bin/env python3
"""Import Stooq CSV daily bars into PostgreSQL.

The import is transactional per batch and idempotent: an existing bar with the
same listing, provider, date and period is updated instead of duplicated.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import os
import sys
from contextlib import contextmanager
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterator, TextIO

try:
    import psycopg
except ImportError:  # pragma: no cover - produces a useful CLI error
    sys.exit("Missing dependency: install it with 'python3 -m pip install psycopg[binary]'.")


SCRIPT_DIR = Path(__file__).resolve().parent
SCHEMA_FILE = SCRIPT_DIR / "stooq_schema.sql"
DEFAULT_INPUTS = [SCRIPT_DIR / name for name in ("nasdaq stocks", "nyse stocks", "nysemkt stocks")]
REQUIRED_COLUMNS = {
    "TICKER", "PER", "DATE", "TIME", "OPEN", "HIGH", "LOW", "CLOSE", "VOL", "OPENINT"
}

BAR_COLUMNS = ("listing_id", "provider_id", "trade_date", "period", "source_time",
               "open", "high", "low", "close", "volume", "open_interest")


def write_batch(connection, pending):
    with connection.transaction():
        with connection.cursor() as cursor:
            provider_id = cursor.execute("SELECT id FROM provider WHERE code = 'stooq'").fetchone()[0]
            listings = {}
            for row in pending:
                ticker = row["ticker"]
                if ticker in listings:
                    continue
                existing = cursor.execute(
                    "SELECT listing_id FROM provider_symbol WHERE provider_id = %s AND symbol = %s",
                    (provider_id, ticker),
                ).fetchone()
                if existing:
                    listings[ticker] = existing[0]
                else:
                    listing_id = cursor.execute(
                        "INSERT INTO listing (market_code) VALUES (%s) RETURNING id",
                        (row["market_code"],),
                    ).fetchone()[0]
                    cursor.execute(
                        "INSERT INTO provider_symbol (provider_id, listing_id, symbol) VALUES (%s, %s, %s)",
                        (provider_id, listing_id, ticker),
                    )
                    listings[ticker] = listing_id
            cursor.execute("CREATE TEMP TABLE IF NOT EXISTS stooq_batch AS SELECT listing_id, provider_id, trade_date, period, source_time, open, high, low, close, volume, open_interest FROM daily_bar WITH NO DATA")
            cursor.execute("TRUNCATE stooq_batch")
            with cursor.copy("COPY stooq_batch FROM STDIN") as copy:
                for row in pending:
                    copy.write_row((listings[row["ticker"]], provider_id,
                                    *(row[key] for key in BAR_COLUMNS[2:])))
            cursor.execute("""
                INSERT INTO daily_bar (listing_id, provider_id, trade_date, period, source_time,
                                       open, high, low, close, volume, open_interest)
                SELECT * FROM stooq_batch
                ON CONFLICT (listing_id, provider_id, trade_date, period) DO UPDATE SET
                    source_time = EXCLUDED.source_time, open = EXCLUDED.open,
                    high = EXCLUDED.high, low = EXCLUDED.low, close = EXCLUDED.close,
                    volume = EXCLUDED.volume, open_interest = EXCLUDED.open_interest,
                    updated_at = now()
            """)


def normalize_header(value: str) -> str:
    return value.strip().lstrip("\ufeff").replace("\\<", "<").replace("\\>", ">").strip("<>").upper()


@contextmanager
def open_text(path: Path) -> Iterator[TextIO]:
    if path.suffix.lower() == ".gz":
        with gzip.open(path, "rt", encoding="utf-8-sig", newline="") as handle:
            yield handle
    else:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            yield handle


def optional_integer(raw: str, field: str, line_number: int) -> int | None:
    value = raw.strip()
    if not value or value.upper() in {"N/A", "NA", "NULL", "-"}:
        return None
    try:
        number = Decimal(value)
        if not number.is_finite() or number != number.to_integral_value() or not 0 <= number <= 9223372036854775807:
            raise ValueError("expected a nonnegative BIGINT")
        return int(number)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"line {line_number}: invalid {field}: {raw!r}") from exc


def optional_volume(raw: str, line_number: int) -> Decimal | None:
    value = raw.strip()
    if not value or value.upper() in {"N/A", "NA", "NULL", "-"}:
        return None
    try:
        number = Decimal(value)
        if not number.is_finite() or number < 0:
            raise ValueError("expected a finite nonnegative volume")
        return number
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"line {line_number}: invalid VOL: {raw!r}") from exc


def parse_row(row: dict[str, str], line_number: int) -> dict[str, object]:
    try:
        ticker = row["TICKER"].strip().upper()
        period = row["PER"].strip().upper()
        if not ticker:
            raise ValueError("empty TICKER")
        if period != "D":
            raise ValueError(f"only daily period D is supported, got {period!r}")

        prices = {name.lower(): Decimal(row[name].strip()) for name in ("OPEN", "HIGH", "LOW", "CLOSE")}
        if not all(value.is_finite() for value in prices.values()):
            raise ValueError("OHLC values must be finite")
        if prices["high"] < max(prices["open"], prices["close"], prices["low"]):
            raise ValueError("HIGH is below another OHLC value")
        if prices["low"] > min(prices["open"], prices["close"], prices["high"]):
            raise ValueError("LOW is above another OHLC value")

        time_value = row["TIME"].strip()
        source_time = datetime.strptime(time_value, "%H%M%S").time() if time_value else None
        market_code = ticker.rsplit(".", 1)[1] if "." in ticker else None

        return {
            "ticker": ticker,
            "market_code": market_code,
            "period": period,
            "trade_date": datetime.strptime(row["DATE"].strip(), "%Y%m%d").date(),
            "source_time": source_time,
            **prices,
            "volume": optional_volume(row["VOL"], line_number),
            "open_interest": optional_integer(row["OPENINT"], "OPENINT", line_number),
        }
    except (KeyError, AttributeError, InvalidOperation, ValueError) as exc:
        if isinstance(exc, ValueError) and str(exc).startswith("line "):
            raise
        raise ValueError(f"line {line_number}: {exc}") from exc


def record_reject(connection, path, line_number, row, reason):
    connection.execute(
        """INSERT INTO stooq_import_reject (source_file, line_number, raw_data, reason)
           VALUES (%s, %s, %s::jsonb, %s)
           ON CONFLICT (source_file, line_number) DO UPDATE SET
               raw_data = EXCLUDED.raw_data, reason = EXCLUDED.reason, recorded_at = now()""",
        (str(path.resolve()), line_number, json.dumps(row), reason),
    )


def import_file(connection: psycopg.Connection, path: Path, batch_size: int) -> tuple[int, int]:
    processed = 0
    rejected = 0
    pending: list[dict[str, object]] = []

    with open_text(path) as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError("file has no header")
        reader.fieldnames = [normalize_header(name) for name in reader.fieldnames]
        missing = REQUIRED_COLUMNS.difference(reader.fieldnames)
        if missing:
            raise ValueError(f"missing columns: {', '.join(sorted(missing))}")

        for line_number, row in enumerate(reader, start=2):
            if not any(row.values()):
                continue
            try:
                if None in row or any(value is None for value in row.values()):
                    raise ValueError(f"line {line_number}: column count does not match header")
                pending.append(parse_row(row, line_number))
            except ValueError as exc:
                rejected += 1
                record_reject(connection, path, line_number, row, str(exc))
                print(f"{path}: {exc}", file=sys.stderr)
                continue

            if len(pending) >= batch_size:
                write_batch(connection, pending)
                processed += len(pending)
                pending.clear()

        if pending:
            write_batch(connection, pending)
            processed += len(pending)

    return processed, rejected


def input_files(inputs: list[Path]) -> list[Path]:
    files: list[Path] = []
    for item in inputs:
        if item.is_dir():
            files.extend(sorted(p for p in item.rglob("*") if p.is_file() and p.suffix.lower() in {".csv", ".txt", ".gz"}))
        elif item.is_file():
            files.append(item)
        else:
            raise FileNotFoundError(item)
    return sorted(set(path.resolve() for path in files))


def main() -> int:
    parser = argparse.ArgumentParser(description="Import Stooq daily CSV data into PostgreSQL")
    parser.add_argument("inputs", nargs="*", type=Path, help="CSV/TXT/GZ files or directories; defaults to the three stock directories beside this script")
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL") or "dbname=tradingbot", help="PostgreSQL connection string; defaults to DATABASE_URL or local tradingbot (PGUSER/PGPASSWORD/PGHOST/PGPORT supported)")
    parser.add_argument("--batch-size", type=int, default=1000)
    parser.add_argument("--skip-schema", action="store_true", help="Do not run stooq_schema.sql first")
    parser.add_argument("--dry-run", action="store_true", help="List input counts without connecting to PostgreSQL")
    args = parser.parse_args()

    if not args.database_url:
        parser.error("set DATABASE_URL or pass --database-url")
    if args.batch_size < 1:
        parser.error("--batch-size must be at least 1")

    try:
        files = input_files(args.inputs or DEFAULT_INPUTS)
    except FileNotFoundError as exc:
        parser.error(f"input path does not exist: {exc}")
    if not files:
        parser.error("no CSV, TXT or GZ files found")

    print(f"Discovered {len(files)} files ({sum(p.stat().st_size for p in files):,} bytes)", flush=True)
    if args.dry_run:
        return 0

    failed_files = 0
    total_processed = 0
    total_rejected = 0
    with psycopg.connect(args.database_url, autocommit=True, connect_timeout=10) as connection:
        if not args.skip_schema:
            with connection.transaction():
                connection.execute(SCHEMA_FILE.read_text(encoding="utf-8"))

        for index, path in enumerate(files, start=1):
            try:
                processed, rejected = import_file(connection, path, args.batch_size)
            except (OSError, ValueError, psycopg.Error) as exc:
                if connection.closed or connection.broken:
                    raise
                failed_files += 1
                print(f"[{index}/{len(files)}] FAILED {path}: {exc}; earlier batches may already be committed", file=sys.stderr, flush=True)
                continue
            total_processed += processed
            total_rejected += rejected
            print(f"[{index}/{len(files)}] {path}: imported={processed}, rejected={rejected}", flush=True)

    print(f"total: imported={total_processed}, rejected={total_rejected}, failed_files={failed_files}")
    return 1 if total_rejected or failed_files else 0


if __name__ == "__main__":
    raise SystemExit(main())
