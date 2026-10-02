package com.zxm.tradingbot.ibkr;

import java.util.List;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

import com.ib.client.Contract;
import com.ib.client.EClientSocket;
import com.ib.client.EJavaSignal;
import com.ib.client.EReader;
import com.ib.client.EReaderSignal;

import jakarta.annotation.PostConstruct;
import jakarta.annotation.PreDestroy;

@Component
public class IBKRClient {

    private final EClientSocket client;
    private final EReaderSignal signal;
    private final IBKRCallbackWrapper callbackWrapper;

    private final AtomicInteger historicalRequestIds = new AtomicInteger(10000);
    @Value("${ibkr.host:127.0.0.1}")
    private String host;
    @Value("${ibkr.port:7496}")
    private int port;
    @Value("${ibkr.client-id:1}")
    private int clientId;

    public IBKRClient() {
        this.callbackWrapper = new IBKRCallbackWrapper();
        this.signal = new EJavaSignal();
        this.client = new EClientSocket(callbackWrapper, signal);
    }

    @PostConstruct
    public void connect() {
        client.eConnect(host, port, clientId);

        if (!client.isConnected()) {
            throw new IllegalStateException("Could not connect to IBKR");
        }

        EReader reader = new EReader(client, signal);
        reader.start();

        Thread.ofPlatform()
                .name("ibkr-message-reader")
                .daemon(true)
                .start(() -> processMessages(reader));
    }

    private void processMessages(EReader reader) {
        while (client.isConnected()) {
            try {
                signal.waitForSignal();
                reader.processMsgs();
            } catch (Exception exception) {
                callbackWrapper.error(exception);
            }
        }
    }

    @PreDestroy
    public void disconnect() {
        if (client.isConnected()) {
            client.eDisconnect();
        }
    }

    public CompletableFuture<List<HistoricalBar>> requestHistoricalData(Contract contract,
            String duration, String barSize, String endDateTime, boolean regularHours) {
        if (!client.isConnected()) {
            return CompletableFuture.failedFuture(new IllegalStateException("IBKR is not connected"));
        }
        // Apply readiness timeout to a dependent future, not the shared handshake
        // future.
        return callbackWrapper.connectionReady().thenApply(ignored -> true)
                .orTimeout(10, TimeUnit.SECONDS)
                .thenCompose(ignored -> {
                    if (!client.isConnected()) {
                        return CompletableFuture.failedFuture(new IllegalStateException("IBKR is not connected"));
                    }
                    int requestId = historicalRequestIds.getAndIncrement();
                    var result = callbackWrapper.beginHistoricalRequest(requestId);
                    var response = result.orTimeout(60, TimeUnit.SECONDS).whenComplete((bars, error) -> {
                        callbackWrapper.removeHistoricalRequest(requestId);
                        if (error != null && client.isConnected()) {
                            client.cancelHistoricalData(requestId);
                        }
                    });
                    try {
                        client.reqHistoricalData(requestId, contract, endDateTime, duration, barSize,
                                "TRADES", regularHours ? 1 : 0, 2, false, List.of());
                    } catch (Exception error) {
                        result.completeExceptionally(error);
                    }
                    return response;
                });
    }

    public CompletableFuture<List<IBKRPosition>> requestPositions() {
        if (!client.isConnected()) {
            return CompletableFuture.failedFuture(
                    new IllegalStateException("IBKR is not connected"));
        }

        return callbackWrapper.connectionReady()
                .thenCompose(ignored -> {
                    CompletableFuture<List<IBKRPosition>> result = callbackWrapper.beginPositionsRequest();
                    client.reqPositions();
                    return result;
                })
                .orTimeout(10, TimeUnit.SECONDS)
                .whenComplete((positions, error) -> {
                    if (client.isConnected()) {
                        client.cancelPositions();
                    }
                });
    }
}
