package com.zxm.tradingbot.mcp;

import com.zxm.tradingbot.model.DailyBarsResponse;
import com.zxm.tradingbot.service.DailyBarService;
import org.springframework.ai.mcp.annotation.McpTool;
import org.springframework.ai.mcp.annotation.McpToolParam;
import org.springframework.stereotype.Component;

@Component
public class DailyBarsTool {

    private final DailyBarService service;

    public DailyBarsTool(DailyBarService service) {
        this.service = service;
    }

    @McpTool(name = "get_daily_bars", description = """
            Get stored Stooq daily OHLCV bars for an exact
            provider symbol, for example AAPL.US.
            Both dates are inclusive, in YYYY-MM-DD format.
            Returns bars oldest first, with at most 1000 bars.
            Data comes from the local database, not live quotes.
            """, generateOutputSchema = true, annotations = @McpTool.McpAnnotations(readOnlyHint = true, destructiveHint = false, openWorldHint = false))
    public DailyBarsResponse getDailyBars(
            @McpToolParam(description = "Exact Stooq symbol, for example AAPL.US", required = true) String symbol,

            @McpToolParam(description = "Inclusive start date, YYYY-MM-DD", required = true) String startDate,

            @McpToolParam(description = "Inclusive end date, YYYY-MM-DD", required = true) String endDate) {

        return service.getDailyBars(symbol, startDate, endDate);
    }
}