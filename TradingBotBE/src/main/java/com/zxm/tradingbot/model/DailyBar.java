package com.zxm.tradingbot.model;

import java.math.BigDecimal;

public record DailyBar(
        String date,
        BigDecimal open,
        BigDecimal high,
        BigDecimal low,
        BigDecimal close,
        BigDecimal volume) {
}