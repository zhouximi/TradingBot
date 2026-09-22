package com.zxm.tradingbot.model;

public class Position {

    private String symbol;
    private double quantity;
    private double avgPrice;
    private double marketPrice;
    private double marketValue;
    private double unrealizedPnl;

    public Position(
            String symbol,
            double quantity,
            double avgPrice,
            double marketPrice,
            double marketValue,
            double unrealizedPnl) {
        this.symbol = symbol;
        this.quantity = quantity;
        this.avgPrice = avgPrice;
        this.marketPrice = marketPrice;
        this.marketValue = marketValue;
        this.unrealizedPnl = unrealizedPnl;
    }

    public String getSymbol() {
        return symbol;
    }

    public double getQuantity() {
        return quantity;
    }

    public double getAvgPrice() {
        return avgPrice;
    }

    public double getMarketPrice() {
        return marketPrice;
    }

    public double getMarketValue() {
        return marketValue;
    }

    public double getUnrealizedPnl() {
        return unrealizedPnl;
    }
}