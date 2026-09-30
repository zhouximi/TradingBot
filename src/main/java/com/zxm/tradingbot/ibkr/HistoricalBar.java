package com.zxm.tradingbot.ibkr;

import java.math.BigDecimal;

// Daily bars use yyyyMMdd; intraday bars use Unix epoch seconds (IB formatDate=2).
public record HistoricalBar(String time, double open, double high, double low,
        double close, BigDecimal volume) {
}
