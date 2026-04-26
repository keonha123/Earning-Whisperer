package com.earningwhisperer.infrastructure.demo;

import com.earningwhisperer.infrastructure.websocket.DemoSignalMessage;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.context.event.ApplicationReadyEvent;
import org.springframework.context.event.EventListener;
import org.springframework.core.io.ClassPathResource;
import org.springframework.messaging.simp.SimpMessagingTemplate;
import org.springframework.scheduling.annotation.Async;
import org.springframework.stereotype.Service;

import java.io.IOException;
import java.util.Collections;
import java.util.List;

/**
 * 쇼케이스 데모룸 AI 이벤트 재생 서비스 (라디오 방송국 모델).
 *
 * 서버 기동 직후 스크립트를 처음부터 끝까지 무한 반복 재생한다.
 * 유저가 어느 시점에 접속하든 현재 재생 구간부터 수신하므로 별도 세션 관리가 불필요하다.
 *
 * 재생 흐름:
 *   스크립트 이벤트 순서대로 /topic/live/demo 브로드캐스트
 *     → INTERVAL_MS 대기
 *   마지막 이벤트 후 is_session_end=true 발행
 *     → SESSION_END_PAUSE_MS 대기
 *   처음으로 돌아가 반복
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class DemoReplayService {

    private static final String TOPIC = "/topic/live/demo";
    private static final String SCRIPT_PATH = "data/mock-nvda-replay.json";
    static final int INTERVAL_MS = 10_000;        // 이벤트 간 간격: 10초
    static final int SESSION_END_PAUSE_MS = 5_000; // 루프 재시작 전 대기: 5초

    private final SimpMessagingTemplate messagingTemplate;
    private final ObjectMapper objectMapper;

    @EventListener(ApplicationReadyEvent.class)
    @Async
    public void startReplay() {
        List<DemoReplayEvent> events = loadScript();
        if (events.isEmpty()) {
            log.warn("[DemoReplay] 스크립트가 비어 있어 재생을 시작하지 않습니다.");
            return;
        }

        log.info("[DemoReplay] 재생 시작 - 이벤트 수={} 간격={}ms", events.size(), INTERVAL_MS);

        while (!Thread.currentThread().isInterrupted()) {
            for (DemoReplayEvent event : events) {
                messagingTemplate.convertAndSend(TOPIC, buildMessage(event, false));
                log.debug("[DemoReplay] 브로드캐스트 - action={} aiScore={}", event.action(), event.aiScore());

                try {
                    Thread.sleep(INTERVAL_MS);
                } catch (InterruptedException e) {
                    Thread.currentThread().interrupt();
                    log.info("[DemoReplay] 인터럽트 수신. 재생 종료.");
                    return;
                }
            }

            // 루프 종료 신호 발행
            DemoReplayEvent last = events.get(events.size() - 1);
            messagingTemplate.convertAndSend(TOPIC, buildMessage(last, true));
            log.info("[DemoReplay] 세션 종료 신호 발행. {}ms 후 재시작.", SESSION_END_PAUSE_MS);

            try {
                Thread.sleep(SESSION_END_PAUSE_MS);
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                return;
            }
        }
    }

    /**
     * DemoReplayEvent → DemoSignalMessage 변환.
     * package-private: 테스트에서 직접 호출 가능.
     */
    DemoSignalMessage buildMessage(DemoReplayEvent event, boolean isSessionEnd) {
        return DemoSignalMessage.builder()
                .ticker(event.ticker())
                .textChunk(event.textChunk())
                .aiScore(event.aiScore())
                .rationale(event.rationale())
                .action(event.action())
                .timestamp(event.timestamp())
                .isSessionEnd(isSessionEnd)
                .build();
    }

    private List<DemoReplayEvent> loadScript() {
        try {
            ClassPathResource resource = new ClassPathResource(SCRIPT_PATH);
            return objectMapper.readValue(
                    resource.getInputStream(),
                    new TypeReference<List<DemoReplayEvent>>() {});
        } catch (IOException e) {
            log.error("[DemoReplay] 스크립트 로드 실패 - path={}", SCRIPT_PATH, e);
            return Collections.emptyList();
        }
    }
}
