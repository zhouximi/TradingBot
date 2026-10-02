package com.zxm.tradingbot.service;

import java.time.LocalDate;
import java.time.format.DateTimeParseException;

import org.springframework.stereotype.Service;

import com.zxm.tradingbot.model.DailyBarsResponse;
import com.zxm.tradingbot.repository.DailyBarRepository;

@Service
public class DailyBarService {

    private static final int MAX_BARS = 1000;

    private final DailyBarRepository repository;

    public DailyBarService(DailyBarRepository repository) {
        this.repository = repository;
    }

    public DailyBarsResponse getDailyBars(
            String symbol,
            String startDate,
            String endDate) {

        if (symbol == null || symbol.isBlank()) {
            throw new IllegalArgumentException("symbol is required");
        }

        LocalDate start = parseDate(startDate, "startDate");
        LocalDate end = parseDate(endDate, "endDate");

        if (start.isAfter(end)) {
            throw new IllegalArgumentException(
                    "startDate must be on or before endDate");
        }

        var stock = repository.findStock(symbol.trim())
                .orElseThrow(() -> new IllegalArgumentException(
                        "Unknown Stooq symbol: " + symbol));

        var bars = repository.findBars(
                stock, start, end, MAX_BARS + 1);

        if (bars.size() > MAX_BARS) {
            throw new IllegalArgumentException(
                    "The range contains more than 1000 bars. "
                            + "Request a smaller date range.");
        }

        return new DailyBarsResponse(
                stock.symbol(),
                "stooq",
                start.toString(),
                end.toString(),
                bars.size(),
                bars);
    }

    private LocalDate parseDate(String value, String field) {
        if (value == null || value.isBlank()) {
            throw new IllegalArgumentException(field + " is required");
        }

        try {
            return LocalDate.parse(value);
        } catch (DateTimeParseException exception) {
            throw new IllegalArgumentException(
                    field + " must be a valid date in YYYY-MM-DD format");
        }
    }
}