CREATE TABLE IF NOT EXISTS provider (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code         TEXT NOT NULL UNIQUE,
    name         TEXT NOT NULL UNIQUE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS listing (
    id                 BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    market_code        TEXT,
    resolution_status  TEXT NOT NULL DEFAULT 'unresolved'
        CHECK (resolution_status IN ('unresolved', 'resolved')),
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS provider_symbol (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    provider_id  BIGINT NOT NULL REFERENCES provider(id),
    listing_id   BIGINT NOT NULL REFERENCES listing(id),
    symbol       TEXT NOT NULL,
    valid_from   DATE,
    valid_to     DATE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT provider_symbol_provider_symbol_uq UNIQUE (provider_id, symbol),
    CONSTRAINT provider_symbol_valid_dates_ck
        CHECK (valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from)
);

CREATE TABLE IF NOT EXISTS daily_bar (
    id             BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    listing_id     BIGINT NOT NULL REFERENCES listing(id),
    provider_id    BIGINT NOT NULL REFERENCES provider(id),
    trade_date     DATE NOT NULL,
    period         TEXT NOT NULL DEFAULT 'D',
    source_time    TIME,
    open           NUMERIC NOT NULL,
    high           NUMERIC NOT NULL,
    low            NUMERIC NOT NULL,
    close          NUMERIC NOT NULL,
    volume         NUMERIC,
    open_interest  BIGINT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT daily_bar_natural_key_uq
        UNIQUE (listing_id, provider_id, trade_date, period),
    CONSTRAINT daily_bar_price_range_ck
        CHECK (high >= low AND high >= open AND high >= close
               AND low <= open AND low <= close),
    CONSTRAINT daily_bar_volume_ck CHECK (volume IS NULL OR volume >= 0),
    CONSTRAINT daily_bar_open_interest_ck CHECK (open_interest IS NULL OR open_interest >= 0)
);

CREATE INDEX IF NOT EXISTS daily_bar_listing_date_idx
    ON daily_bar (listing_id, trade_date DESC);

INSERT INTO provider (code, name)
VALUES ('stooq', 'Stooq')
ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name;

-- Stooq historical adjusted volumes can be fractional. Preserve them exactly.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = current_schema() AND table_name = 'daily_bar'
          AND column_name = 'volume' AND data_type = 'bigint'
    ) THEN
        ALTER TABLE daily_bar ALTER COLUMN volume TYPE NUMERIC;
    END IF;
END $$;

-- Preserve source rows that cannot satisfy daily_bar validation.
CREATE TABLE IF NOT EXISTS stooq_import_reject (
    source_file TEXT NOT NULL,
    line_number BIGINT NOT NULL,
    raw_data JSONB NOT NULL,
    reason TEXT NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (source_file, line_number)
);

-- Keep the full precision and range of historical source prices.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = current_schema() AND table_name = 'daily_bar'
          AND column_name IN ('open', 'high', 'low', 'close')
          AND numeric_precision IS NOT NULL
    ) THEN
        ALTER TABLE daily_bar
            ALTER COLUMN open TYPE NUMERIC,
            ALTER COLUMN high TYPE NUMERIC,
            ALTER COLUMN low TYPE NUMERIC,
            ALTER COLUMN close TYPE NUMERIC;
    END IF;
END $$;
