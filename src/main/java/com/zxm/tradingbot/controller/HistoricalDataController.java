package com.zxm.tradingbot.controller;

import java.util.List;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.CompletionException;
import java.util.concurrent.TimeoutException;

import com.ib.client.Contract;
import com.zxm.tradingbot.ibkr.HistoricalBar;
import com.zxm.tradingbot.ibkr.IBKRClient;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

@RestController
public class HistoricalDataController {
    private final IBKRClient client;

    public HistoricalDataController(IBKRClient client) {
        this.client = client;
    }

    @GetMapping("/api/history")
    public CompletableFuture<List<HistoricalBar>> history(
            @RequestParam String symbol,
            @RequestParam(defaultValue = "SMART") String exchange,
            @RequestParam(defaultValue = "USD") String currency,
            @RequestParam(defaultValue = "") String primaryExchange,
            @RequestParam(defaultValue = "1 M") String duration,
            @RequestParam(defaultValue = "1 day") String barSize,
            @RequestParam(defaultValue = "") String endDateTime,
            @RequestParam(defaultValue = "true") boolean regularHours) {
        if (symbol.isBlank() || exchange.isBlank() || currency.isBlank()
                || duration.isBlank() || barSize.isBlank()) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Request parameters must not be blank");
        }
        Contract contract = new Contract();
        contract.symbol(symbol.trim());
        contract.secType("STK");
        contract.exchange(exchange.trim());
        contract.currency(currency.trim());
        if (!primaryExchange.isBlank()) {
            contract.primaryExch(primaryExchange.trim());
        }
        return client.requestHistoricalData(contract, duration, barSize, endDateTime, regularHours)
                .exceptionally(error -> {
                    Throwable cause = error;
                    while (cause instanceof CompletionException && cause.getCause() != null) {
                        cause = cause.getCause();
                    }
                    throw new ResponseStatusException(cause instanceof TimeoutException
                            ? HttpStatus.GATEWAY_TIMEOUT : HttpStatus.BAD_GATEWAY,
                            cause instanceof TimeoutException ? "TWS historical data request timed out" : cause.getMessage(), cause);
                });
    }
}
