package com.earningwhisperer.presentation.demo;

import com.earningwhisperer.infrastructure.demo.DemoEarningsCallScript;
import com.earningwhisperer.infrastructure.demo.DemoEarningsCallService;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.io.IOException;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 시연용 어닝콜 재생 제어 API.
 *
 * <p>Trading Terminal 의 "시연 시작" 버튼이 호출한다. 인증은 기본 정책(JWT 필요)을 따른다 —
 * SecurityConfig 의 permitAll 목록에 넣지 않는다. 아무나 재생을 트리거하면 다른 시청자의
 * 화면까지 함께 바뀌기 때문이다.
 */
@RestController
@RequestMapping("/api/v1/demo/earnings-call")
@RequiredArgsConstructor
public class DemoEarningsCallController {

    private final DemoEarningsCallService service;

    /**
     * 재생 시작. body 의 {@code ticker} 는 선택이며, 없으면 스크립트 기본 종목을 쓴다.
     *
     * <ul>
     *   <li>202 Accepted — 재생 시작 (비동기 진행)</li>
     *   <li>409 Conflict — 해당 종목이 이미 재생 중</li>
     *   <li>500 — 스크립트 파일을 읽을 수 없음</li>
     * </ul>
     */
    @PostMapping("/start")
    public ResponseEntity<?> start(@RequestBody(required = false) StartRequest request) {
        String ticker = request == null ? null : request.ticker();
        DemoEarningsCallService.StartResult result = service.start(ticker);
        return switch (result.outcome()) {
            case STARTED -> ResponseEntity.accepted().body(startedBody(result));
            case ALREADY_RUNNING -> ResponseEntity.status(HttpStatus.CONFLICT).body(Map.of(
                    "error", result.message(),
                    "ticker", result.ticker(),
                    "call_id", result.callId()
            ));
            case SCRIPT_UNAVAILABLE -> ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR)
                    .body(Map.of("error", result.message()));
        };
    }

    /** 재생 중지. 진행 중인 세션이 없으면 404. */
    @PostMapping("/stop")
    public ResponseEntity<?> stop(@RequestBody(required = false) StartRequest request) {
        String ticker = request == null ? null : request.ticker();
        if (service.stop(ticker)) {
            return ResponseEntity.ok(Map.of("ticker", ticker, "stopped", true));
        }
        return ResponseEntity.status(HttpStatus.NOT_FOUND)
                .body(Map.of("error", "진행 중인 재생이 없습니다: " + ticker));
    }

    /**
     * 진행 상태 조회.
     *
     * <p>재생 중이 아니면 {@code running=false} 와 함께 <b>마지막 재생 요약</b>({@code last_run})
     * 을 돌려준다. 이게 없으면 "정상 완료", "시작한 적 없음", "첫 세그먼트부터 전부 거부되어
     * 즉시 끝남" 이 모두 똑같이 보여 시연 현장에서 원인을 구분할 수 없다.
     */
    @GetMapping("/status")
    public ResponseEntity<?> status(@RequestParam String ticker) {
        return service.status(ticker)
                .<ResponseEntity<?>>map(s -> ResponseEntity.ok(Map.of(
                        "running", true,
                        "ticker", s.ticker(),
                        "call_id", s.callId(),
                        "published_count", s.publishedCount(),
                        "total_segments", s.totalSegments()
                )))
                .orElseGet(() -> service.lastRun(ticker)
                        .<ResponseEntity<?>>map(last -> ResponseEntity.ok(Map.of(
                                "running", false,
                                "ticker", last.ticker(),
                                "last_run", Map.of(
                                        "call_id", last.callId(),
                                        "outcome", last.outcome(),
                                        "published_count", last.publishedCount(),
                                        "total_segments", last.totalSegments()
                                )
                        )))
                        .orElseGet(() -> ResponseEntity.ok(Map.of("running", false, "ticker", ticker))));
    }

    /**
     * 콜 참가자 명부 조회.
     *
     * <p>터미널의 발화자 프로필이 쓴다. 스크립트에 명부가 없으면 빈 배열 — 그 경우 터미널은
     * 프로필 진입점을 띄우지 않는다. 재생 중 여부와 무관하게 응답한다.
     *
     * <p>스크립트를 읽지 못하면 500 이다. 빈 배열로 내려보내면 "명부를 안 넣었다" 와
     * "파일이 깨졌다" 가 구별되지 않는다.
     *
     * <p>{@code match_key} 는 세그먼트의 {@code speaker} 문자열과 정확히 같은 값이다.
     * 스크립트가 비워 두면 이름으로 채워 내려보낸다 — 클라이언트가 매칭 규칙을 추측하지
     * 않게 하는 것이 이 필드의 목적이다.
     */
    @GetMapping("/speakers")
    public ResponseEntity<?> speakers() {
        List<DemoEarningsCallScript.Speaker> speakers;
        try {
            speakers = service.speakers();
        } catch (IOException e) {
            return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR)
                    .body(Map.of("error", "발화자 명부를 읽지 못했습니다: " + e.getMessage()));
        }
        List<Map<String, Object>> body = speakers.stream()
                .map(s -> Map.<String, Object>of(
                        "name", s.name() == null ? "" : s.name(),
                        "match_key", s.effectiveMatchKey() == null ? "" : s.effectiveMatchKey(),
                        "title", s.title() == null ? "" : s.title(),
                        "affiliation", s.affiliation() == null ? "" : s.affiliation(),
                        "analyst", s.analyst()
                ))
                .toList();
        return ResponseEntity.ok(body);
    }

    /** 시작/중지 공통 요청 본문. */
    /**
     * 재생 시작 응답.
     *
     * <p>{@code evidence_warning} 은 근거 저장소가 비었을 때만 실린다. {@code Map.of} 는
     * null 값을 허용하지 않으므로 직접 조립한다.
     */
    private static Map<String, Object> startedBody(DemoEarningsCallService.StartResult result) {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("ticker", result.ticker());
        body.put("call_id", result.callId());
        body.put("segment_count", result.segmentCount());
        body.put("interval_ms", result.intervalMs());
        if (result.evidenceWarning() != null) {
            body.put("evidence_warning", result.evidenceWarning());
        }
        return body;
    }

    public record StartRequest(String ticker) {
    }
}
