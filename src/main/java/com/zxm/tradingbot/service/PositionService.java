package com.zxm.tradingbot.service;

import java.util.List;

import org.springframework.stereotype.Service;

import com.zxm.tradingbot.ibkr.IBKRClient;
import com.zxm.tradingbot.model.Position;

@Service
public class PositionService {
    private final IBKRClient ibkrClient;

    public PositionService(IBKRClient ibkrClient) {
        this.ibkrClient = ibkrClient;
    }

    public List<Position> getPositions() {
        return ibkrClient.getPositions();
    }
}
