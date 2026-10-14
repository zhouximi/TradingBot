# Stooq 日线导入

脚本创建并填充当前原始数据能够支持的四张表：`provider`、`listing`、
`provider_symbol` 和 `daily_bar`。`listing` 暂时标记为 `unresolved`；以后取得
发行人、证券和交易所主数据后，再将它关联到完整的证券模型。

## 使用方法

安装 Python 依赖：

```bash
cd /Users/xmz/Documents/projects/TradingBot
python3 -m venv .venv
.venv/bin/python -m pip install -r Script/requirements.txt
```

默认导入脚本旁边的三个目录（包括所有数字子目录），不依赖运行命令时的工作目录：

```text
Script/
├── import_stooq.py
├── nasdaq stocks/{1,2,3}/*.us.txt
├── nyse stocks/{1,2,3}/*.us.txt
└── nysemkt stocks/*.us.txt
```

先检查扫描结果，再全量导入：

```bash
.venv/bin/python Script/import_stooq.py --dry-run
.venv/bin/python Script/import_stooq.py
```

默认连接本地已有的 `tradingbot` 数据库，使用 PostgreSQL 默认认证配置。
如果数据库用户名与系统用户名不同，请配置 `PGUSER`；密码可通过
`PGPASSWORD` 或 `~/.pgpass` 提供。例如：

```bash
export PGUSER='你的数据库用户名'
export PGHOST='localhost'
export PGPORT='5432'
.venv/bin/python Script/import_stooq.py
```

也可以通过 `DATABASE_URL` 或 `--database-url` 指定连接。
脚本自动创建表，但不会创建数据库或数据库角色。

设置本地 PostgreSQL 连接并导入一个文件：

```bash
export DATABASE_URL='postgresql://用户名:密码@localhost:5432/tradingbot'
.venv/bin/python Script/import_stooq.py /绝对路径/到/stooq.csv
```

也可以传入多个文件或整个目录：

```bash
.venv/bin/python Script/import_stooq.py /data/stooq/file1.csv /data/stooq/file2.csv
.venv/bin/python Script/import_stooq.py /data/stooq
```

脚本默认先执行 `stooq_schema.sql`，因此不需要单独建表。如果只想手动建表：

```bash
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -1 -f Script/stooq_schema.sql
```

导入可以重复运行。相同 Stooq 代码、日期和周期的数据会更新，不会生成重复日线。
每个批次单独提交（默认 1,000 行，可用 `--batch-size` 调整）；中断后可重复运行。
重叠输入路径会去重。每个文件完成后显示进度。
错误行写入标准错误；文件失败后继续其他文件。失败文件此前提交的批次会保留。
最终汇总 `imported`、`rejected` 和 `failed_files`；后两者非零时退出码为 1。
`imported` 是成功文件处理的行数（含更新），不是新增行数，亦不包含失败文件已提交的批次。

## 检查结果

```sql
SELECT ps.symbol, b.trade_date, b.open, b.high, b.low, b.close, b.volume
FROM daily_bar b
JOIN provider_symbol ps
  ON ps.listing_id = b.listing_id
 AND ps.provider_id = b.provider_id
ORDER BY ps.symbol, b.trade_date;
```

## 本机连接与全量导入

本机使用无密码角色 `xianming`：

```bash
.venv/bin/python Script/import_stooq.py --database-url 'dbname=tradingbot user=xianming' --batch-size 10000
```

行情按批次通过临时表 `COPY` 后合并到 `daily_bar`。`volume` 使用 `NUMERIC`，
保留源文件中的小数成交量；脚本会自动将旧的 `BIGINT` 成交量列迁移为 `NUMERIC`。

OHLC 价格也使用不限精度的 `NUMERIC`，避免极端历史价格溢出或微小价格被舍入。
无法满足价格范围等校验的源行保存到 `stooq_import_reject`，包含文件路径、
行号、原始字段和错误原因；它们不计入 `daily_bar`，也不会被自动修改。
空文件没有可导入的记录，会在日志中明确报告。

## `tradingbot` 当前表结构

以下结构来自本地 PostgreSQL `tradingbot` 数据库的 `public` schema（2026-10-02）。

```sql
CREATE TABLE public.provider (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code        TEXT NOT NULL UNIQUE,
    name        TEXT NOT NULL UNIQUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE public.listing (
    id                 BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    market_code        TEXT,
    resolution_status  TEXT NOT NULL DEFAULT 'unresolved'
        CHECK (resolution_status IN ('unresolved', 'resolved')),
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE public.provider_symbol (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    provider_id  BIGINT NOT NULL REFERENCES public.provider(id),
    listing_id   BIGINT NOT NULL REFERENCES public.listing(id),
    symbol       TEXT NOT NULL,
    valid_from   DATE,
    valid_to     DATE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT provider_symbol_provider_symbol_uq
        UNIQUE (provider_id, symbol),
    CONSTRAINT provider_symbol_valid_dates_ck
        CHECK (valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from)
);

CREATE TABLE public.daily_bar (
    id             BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    listing_id     BIGINT NOT NULL REFERENCES public.listing(id),
    provider_id    BIGINT NOT NULL REFERENCES public.provider(id),
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
    CONSTRAINT daily_bar_natural_key_uq
        UNIQUE (listing_id, provider_id, trade_date, period),
    CONSTRAINT daily_bar_price_nonnegative_ck
        CHECK (open >= 0 AND high >= 0 AND low >= 0 AND close >= 0),
    CONSTRAINT daily_bar_price_range_ck
        CHECK (high >= low AND high >= open AND high >= close
               AND low <= open AND low <= close),
    CONSTRAINT daily_bar_volume_ck CHECK (volume IS NULL OR volume >= 0),
    CONSTRAINT daily_bar_open_interest_ck
        CHECK (open_interest IS NULL OR open_interest >= 0)
);

CREATE TABLE public.stooq_import_reject (
    source_file  TEXT NOT NULL,
    line_number  BIGINT NOT NULL,
    raw_data     JSONB NOT NULL,
    reason       TEXT NOT NULL,
    recorded_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (source_file, line_number)
);
```

非约束索引：

```sql
CREATE INDEX daily_bar_date_listing_idx
    ON public.daily_bar (trade_date, listing_id);
CREATE INDEX daily_bar_listing_date_idx
    ON public.daily_bar (listing_id, trade_date DESC);
CREATE INDEX daily_bar_provider_date_idx
    ON public.daily_bar (provider_id, trade_date DESC);
CREATE INDEX provider_symbol_listing_idx
    ON public.provider_symbol (listing_id);
```
