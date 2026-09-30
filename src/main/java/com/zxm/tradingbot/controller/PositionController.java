package com.zxm.tradingbot.controller;

import java.util.List;
import java.util.concurrent.CompletableFuture;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

import com.zxm.tradingbot.ibkr.IBKRPosition;
import com.zxm.tradingbot.service.PositionService;

@RestController
public class PositionController {

    private final PositionService positionService;

    public PositionController(PositionService positionService) {
        this.positionService = positionService;
    }

    @GetMapping("/api/positions")
    public CompletableFuture<List<IBKRPosition>> getPositions() {
        return positionService.requestPositions();
    }
}
