package com.zxm.tradingbot.ibkr;

import java.util.List;

import org.springframework.stereotype.Component;

import com.zxm.tradingbot.model.Position;

@Component
public class IBKRClient {

    public List<Position> getPositions() {
        // TODO: connect to IB Gateway
        // TODO: call TWS API reqPositions()

        return List.of();
    }
}