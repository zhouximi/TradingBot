package com.zxm.tradingbot.model;

import java.util.List;

public record DailyBarsResponse(
        String symbol,
        String provider,
        String startDate,
        String endDate,
        int count,
        List<DailyBar> bars) {
}