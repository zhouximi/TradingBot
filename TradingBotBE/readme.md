# TradingBot Backend

## `tradingbot` database schema

Current PostgreSQL tables in the `public` schema, verified on 2026-10-02:

```sql
CREATE TABLE provider (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code        TEXT NOT NULL UNIQUE,
    name        TEXT NOT NULL UNIQUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE listing (
    id                 BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    market_code        TEXT,
    resolution_status  TEXT NOT NULL DEFAULT 'unresolved'
        CHECK (resolution_status IN ('unresolved', 'resolved')),
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE provider_symbol (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    provider_id  BIGINT NOT NULL REFERENCES provider(id),
    listing_id   BIGINT NOT NULL REFERENCES listing(id),
    symbol       TEXT NOT NULL,
    valid_from   DATE,
    valid_to     DATE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (provider_id, symbol),
    CHECK (valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from)
);

CREATE TABLE daily_bar (
    id             BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    listing_id     BIGINT NOT NULL REFERENCES listing(id),
    provider_id    BIGINT NOT NULL REFERENCES provider(id),
    trade_date     DATE NOT NULL,
    period         TEXT NOT NULL DEFAULT 'D' CHECK (period = 'D'),
    source_time    TIME,
    open           NUMERIC NOT NULL,
    high           NUMERIC NOT NULL,
    low            NUMERIC NOT NULL,
    close          NUMERIC NOT NULL,
    volume         NUMERIC,
    open_interest  BIGINT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (listing_id, provider_id, trade_date, period),
    CHECK (open >= 0 AND high >= 0 AND low >= 0 AND close >= 0),
    CHECK (high >= low AND high >= open AND high >= close
           AND low <= open AND low <= close),
    CHECK (volume IS NULL OR volume >= 0),
    CHECK (open_interest IS NULL OR open_interest >= 0)
);

CREATE TABLE stooq_import_reject (
    source_file  TEXT NOT NULL,
    line_number  BIGINT NOT NULL,
    raw_data     JSONB NOT NULL,
    reason       TEXT NOT NULL,
    recorded_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (source_file, line_number)
);
```

## Field descriptions

### `provider`

| Field | Description |
| --- | --- |
| `id` | Auto-generated primary key for the data provider. |
| `code` | Unique machine-readable provider code, such as `stooq`. |
| `name` | Unique display name of the provider. |
| `created_at` | Timestamp when the provider record was created; defaults to the current time. |

### `listing`

| Field | Description |
| --- | --- |
| `id` | Auto-generated primary key for the market listing. |
| `market_code` | Optional code identifying the market or exchange on which the instrument is listed. |
| `resolution_status` | Whether the imported listing has been matched to complete security master data; allowed values are `unresolved` and `resolved`. |
| `created_at` | Timestamp when the listing was created; defaults to the current time. |
| `updated_at` | Timestamp when the listing was last updated; initially defaults to the current time. |

### `provider_symbol`

| Field | Description |
| --- | --- |
| `id` | Auto-generated primary key for the provider-symbol mapping. |
| `provider_id` | Provider that supplied the symbol; references `provider.id`. |
| `listing_id` | Internal listing represented by the symbol; references `listing.id`. |
| `symbol` | Symbol used by the provider, such as a Stooq ticker code. It is unique within a provider. |
| `valid_from` | Optional first date on which this symbol mapping is valid. |
| `valid_to` | Optional last date on which this symbol mapping is valid; it cannot precede `valid_from`. |
| `created_at` | Timestamp when the mapping was created; defaults to the current time. |

### `daily_bar`

| Field | Description |
| --- | --- |
| `id` | Auto-generated primary key for the price bar. |
| `listing_id` | Listing to which the bar belongs; references `listing.id`. |
| `provider_id` | Provider from which the bar originated; references `provider.id`. |
| `trade_date` | Trading date represented by the bar. |
| `period` | Bar interval. The current schema accepts daily bars only (`D`). |
| `source_time` | Optional time supplied by the source for the bar, without a time zone. |
| `open` | Opening price. Must be non-negative. |
| `high` | Highest price. Must be non-negative and no lower than the open, close, or low. |
| `low` | Lowest price. Must be non-negative and no higher than the open, close, or high. |
| `close` | Closing price. Must be non-negative. |
| `volume` | Optional traded volume. Fractional values are supported and the value cannot be negative. |
| `open_interest` | Optional number of outstanding contracts. It cannot be negative. |
| `created_at` | Timestamp when the bar was created; defaults to the current time. |
| `updated_at` | Timestamp when the bar was last updated; initially defaults to the current time. |

A bar is uniquely identified by `listing_id`, `provider_id`, `trade_date`, and `period`.

### `stooq_import_reject`

| Field | Description |
| --- | --- |
| `source_file` | Path of the source file containing the rejected record. Together with `line_number`, it forms the primary key. |
| `line_number` | Line number of the rejected record in the source file. |
| `raw_data` | Original rejected row stored as JSON for investigation or reprocessing. |
| `reason` | Validation or import error explaining why the row was rejected. |
| `recorded_at` | Timestamp when the rejection was recorded; defaults to the current time. |

Additional indexes:

```sql
CREATE INDEX daily_bar_date_listing_idx
    ON daily_bar (trade_date, listing_id);
CREATE INDEX daily_bar_listing_date_idx
    ON daily_bar (listing_id, trade_date DESC);
CREATE INDEX daily_bar_provider_date_idx
    ON daily_bar (provider_id, trade_date DESC);
CREATE INDEX provider_symbol_listing_idx
    ON provider_symbol (listing_id);
```
