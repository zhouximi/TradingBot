package com.zxm.tradingbot.ibkr;

import java.util.ArrayList;
import java.util.List;
import java.util.HashMap;
import java.util.Map;
import com.ib.client.Bar;
import java.util.concurrent.CompletableFuture;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import com.ib.client.Contract;
import com.ib.client.Decimal;
import com.ib.client.DefaultEWrapper;

public class IBKRCallbackWrapper extends DefaultEWrapper {

    private static final Logger log = LoggerFactory.getLogger(IBKRCallbackWrapper.class);

    private final CompletableFuture<Void> connectionReady = new CompletableFuture<>();
    private final List<IBKRPosition> positions = new ArrayList<>();
    private CompletableFuture<List<IBKRPosition>> positionsFuture;

    private final Map<Integer, List<HistoricalBar>> historicalBars = new HashMap<>();
    private final Map<Integer, CompletableFuture<List<HistoricalBar>>> historicalRequests = new HashMap<>();

    public synchronized CompletableFuture<List<HistoricalBar>> beginHistoricalRequest(int requestId) {
        var future = new CompletableFuture<List<HistoricalBar>>();
        historicalBars.put(requestId, new ArrayList<>());
        historicalRequests.put(requestId, future);
        return future;
    }

    public synchronized void removeHistoricalRequest(int requestId) {
        historicalBars.remove(requestId);
        historicalRequests.remove(requestId);
    }

    @Override
    public synchronized void historicalData(int requestId, Bar bar) {
        var bars = historicalBars.get(requestId);
        if (bars != null) {
            bars.add(new HistoricalBar(bar.time(), bar.open(), bar.high(), bar.low(),
                    bar.close(), bar.volume().value()));
        }
    }

    @Override
    public synchronized void historicalDataEnd(int requestId, String start, String end) {
        var future = historicalRequests.get(requestId);
        if (future != null) {
            future.complete(List.copyOf(historicalBars.get(requestId)));
        }
    }

    private synchronized void failHistoricalRequests(Throwable error) {
        List.copyOf(historicalRequests.values()).forEach(future -> future.completeExceptionally(error));
    }

    public CompletableFuture<Void> connectionReady() {
        return connectionReady;
    }

    public synchronized CompletableFuture<List<IBKRPosition>> beginPositionsRequest() {
        if (positionsFuture != null && !positionsFuture.isDone()) {
            throw new IllegalStateException("A positions request is already running");
        }

        positions.clear();
        positionsFuture = new CompletableFuture<>();
        return positionsFuture;
    }

    @Override
    public void connectAck() {
        log.info("IBKR connection acknowledged");
    }

    @Override
    public void nextValidId(int orderId) {
        connectionReady.complete(null);
        log.info("IBKR API is ready; next valid order ID is {}", orderId);
    }

    @Override
    public void connectionClosed() {
        IllegalStateException error = new IllegalStateException("IBKR connection closed");
        connectionReady.completeExceptionally(error);
        failPositionsRequest(error);
        failHistoricalRequests(error);
        log.warn("IBKR connection closed");
    }

    @Override
    public void error(Exception exception) {
        failPositionsRequest(exception);
        failHistoricalRequests(exception);
        log.error("IBKR client error", exception);
    }

    @Override
    public void error(String message) {
        IllegalStateException error = new IllegalStateException(message);
        failPositionsRequest(error);
        failHistoricalRequests(error);
        log.error("IBKR error: {}", message);
    }

    @Override
    public synchronized void error(int requestId, long errorTime, int errorCode, String errorMessage,
            String advancedOrderRejectJson) {
        var future = historicalRequests.get(requestId);
        // 2174 is a date/time-zone warning, not a failed historical request.
        if (future != null && errorCode != 2174) {
            future.completeExceptionally(new IllegalStateException("IBKR " + errorCode + ": " + errorMessage));
        }
        log.warn("IBKR error. requestId={}, time={}, code={}, message={}, details={}",
                requestId, errorTime, errorCode, errorMessage, advancedOrderRejectJson);
    }

    @Override
    public synchronized void position(
            String account,
            Contract contract,
            Decimal quantity,
            double averageCost) {
        if (!isCollectingPositions()) {
            return;
        }

        positions.add(new IBKRPosition(
                account,
                contract.conid(),
                contract.symbol(),
                contract.getSecType(),
                contract.currency(),
                quantity.value(),
                averageCost));
    }

    @Override
    public synchronized void positionEnd() {
        if (isCollectingPositions()) {
            positionsFuture.complete(List.copyOf(positions));
        }
    }

    private boolean isCollectingPositions() {
        return positionsFuture != null && !positionsFuture.isDone();
    }

    private synchronized void failPositionsRequest(Throwable error) {
        if (isCollectingPositions()) {
            positionsFuture.completeExceptionally(error);
        }
    }
}
