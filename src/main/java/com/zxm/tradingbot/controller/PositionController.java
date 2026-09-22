package com.zxm.tradingbot.controller;

import com.zxm.tradingbot.model.Position;
import com.zxm.tradingbot.service.PositionService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

@RestController
public class PositionController {

    private final PositionService positionService;

    public PositionController(PositionService positionService) {
        this.positionService = positionService;
    }

    @GetMapping("/api/positions")
    public List<Position> getPositions() {
        return positionService.getPositions();
    }
}