package com.zxm.tradingbot.service;

import java.util.List;
import java.util.concurrent.CompletableFuture;

import org.springframework.stereotype.Service;

import com.zxm.tradingbot.ibkr.IBKRClient;
import com.zxm.tradingbot.ibkr.IBKRPosition;

@Service
public class PositionService {
    private final IBKRClient ibkrClient;

    public PositionService(IBKRClient ibkrClient) {
        this.ibkrClient = ibkrClient;
    }

    public CompletableFuture<List<IBKRPosition>> requestPositions() {
        return ibkrClient.requestPositions();
    }
}
