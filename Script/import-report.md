# Stooq 本地导入结果

数据库：`tradingbot`；用户：`xianming`。

- 源文件：9,516 个，其中空文件 20 个。
- 源数据：20,532,104 行。
- 正常行情：`daily_bar` 共 20,532,038 行。
- 异常原始行：`stooq_import_reject` 共 66 行，保存原始字段、文件路径、行号和原因。
- 行数核对：20,532,038 + 66 = 20,532,104，全部源行均已入库。
- Stooq 代码：9,496 个。
- 日期范围：1962-01-02 至 2026-09-30。
- 行情表数据大小：2649 MB；索引大小：3652 MB；合计：6302 MB。
- 已完成 ANALYZE，更新数据库查询统计信息。

## 导入修复

成交量和 OHLC 使用 NUMERIC，完整保留小数及极端历史数值。
NUWE.US、XTIA.US、TOPS.US 已补导成功；无未处理的非空文件。
价格逻辑异常保留于异常表，不自动篡改价格。

## 空文件

- `nasdaq stocks/1/btog.us.txt`
- `nasdaq stocks/1/catlr.us.txt`
- `nasdaq stocks/1/dbcau.us.txt`
- `nasdaq stocks/1/dtsqu.us.txt`
- `nasdaq stocks/1/eghau.us.txt`
- `nasdaq stocks/1/gsrvu.us.txt`
- `nasdaq stocks/1/havau.us.txt`
- `nasdaq stocks/2/hvmcu.us.txt`
- `nasdaq stocks/2/lmfa.us.txt`
- `nasdaq stocks/2/mlaau.us.txt`
- `nasdaq stocks/2/mot.us.txt`
- `nasdaq stocks/2/sseau.us.txt`
- `nasdaq stocks/3/tachu.us.txt`
- `nasdaq stocks/3/wennu.us.txt`
- `nyse stocks/1/copl-u.us.txt`
- `nyse stocks/1/hyacu.us.txt`
- `nyse stocks/2/jacs-u.us.txt`
- `nyse stocks/2/mbgl-w.us.txt`
- `nyse stocks/2/spgi-w.us.txt`
- `nyse stocks/3/ztst.us.txt`
