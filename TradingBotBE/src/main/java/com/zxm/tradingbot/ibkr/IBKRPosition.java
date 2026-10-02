package com.zxm.tradingbot.ibkr;

import java.math.BigDecimal;

public record IBKRPosition(
        String account,
        int contractId,
        String symbol,
        String securityType,
        String currency,
        BigDecimal quantity,
        double averageCost) {
}
