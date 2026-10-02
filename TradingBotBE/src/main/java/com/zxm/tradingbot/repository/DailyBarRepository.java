package com.zxm.tradingbot.repository;

import java.sql.Date;
import java.time.LocalDate;
import java.util.List;
import java.util.Optional;

import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Repository;

import com.zxm.tradingbot.model.DailyBar;

@Repository
public class DailyBarRepository {

    private final JdbcClient jdbc;

    public DailyBarRepository(JdbcClient jdbc) {
        this.jdbc = jdbc;
    }

    public record StockReference(
            long listingId,
            long providerId,
            String symbol) {
    }

    public Optional<StockReference> findStock(String symbol) {
        return jdbc.sql("""
                SELECT ps.listing_id, ps.provider_id, ps.symbol
                FROM provider_symbol ps
                JOIN provider p ON p.id = ps.provider_id
                WHERE p.code = 'stooq'
                  AND ps.symbol = :symbol
                """)
                .param("symbol", symbol)
                .query((rs, rowNum) -> new StockReference(
                        rs.getLong("listing_id"),
                        rs.getLong("provider_id"),
                        rs.getString("symbol")))
                .optional();
    }

    public List<DailyBar> findBars(
            StockReference stock,
            LocalDate startDate,
            LocalDate endDate,
            int limit) {

        return jdbc.sql("""
                SELECT trade_date, open, high, low, close, volume
                FROM daily_bar
                WHERE listing_id = :listingId
                  AND provider_id = :providerId
                  AND period = 'D'
                  AND trade_date BETWEEN :startDate AND :endDate
                ORDER BY trade_date ASC
                LIMIT :limit
                """)
                .param("listingId", stock.listingId())
                .param("providerId", stock.providerId())
                .param("startDate", Date.valueOf(startDate))
                .param("endDate", Date.valueOf(endDate))
                .param("limit", limit)
                .query((rs, rowNum) -> new DailyBar(
                        rs.getDate("trade_date").toLocalDate().toString(),
                        rs.getBigDecimal("open"),
                        rs.getBigDecimal("high"),
                        rs.getBigDecimal("low"),
                        rs.getBigDecimal("close"),
                        rs.getBigDecimal("volume")))
                .list();
    }
}