package com.earningwhisperer.infrastructure.demo;

import com.earningwhisperer.domain.transcript.TranscriptSegment;
import com.earningwhisperer.domain.transcript.TranscriptService;
import com.earningwhisperer.domain.transcript.TranscriptSessionRegistry;
import com.earningwhisperer.infrastructure.aiengine.AiEngineClient;
import com.earningwhisperer.infrastructure.aiengine.LiveFactCheckModels;
import com.earningwhisperer.infrastructure.websocket.FactCheckPublisher;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;

import java.time.Instant;
import java.util.List;
import java.util.Optional;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;

import static org.assertj.core.api.Assertions.assertThat;
import static org.awaitility.Awaitility.await;

/**
 * DemoEarningsCallService 재생 동작 테스트.
 *
 * 재생 간격을 1ms 로 줄여 실제 루프를 끝까지 돌린다.
 */
class DemoEarningsCallServiceTest {

    private static final String SCRIPT = "data/demo-earnings-call.json";
    /** 정상 종료 시 팩트체크 큐 대기시간의 기준. 테스트가 길어지지 않도록 짧게 둔다. */
    private static final long AI_TIMEOUT_MS = 200;

    private DemoEarningsCallService service;

    @AfterEach
    void tearDown() {
        if (service != null) {
            // stop() 은 세션 executor 만 정리한다. shutdownAll 을 부르지 않으면 종합 판단
            // 전용 스레드가 테스트 JVM 에 계속 park 된 채 남고, @PreDestroy 회수 경로가
            // 한 번도 실행되지 않는다.
            service.shutdownAll();
        }
    }

    private DemoEarningsCallService newService(TranscriptService transcript,
                                               AiEngineClient client,
                                               FactCheckPublisher publisher,
                                               long intervalMs) {
        return newService(transcript, client, publisher, noopSummaryService(), intervalMs);
    }

    private DemoEarningsCallService newService(TranscriptService transcript,
                                               AiEngineClient client,
                                               FactCheckPublisher publisher,
                                               EarningsSummaryService summaryService,
                                               long intervalMs) {
        service = new DemoEarningsCallService(transcript, client, publisher, summaryService,
                new ObjectMapper(), SCRIPT, intervalMs, AI_TIMEOUT_MS);
        return service;
    }

    @Test
    void 재생하면_스크립트_전체가_트랜스크립트_경로로_들어간다() {
        RecordingTranscriptService transcript = new RecordingTranscriptService();
        DemoEarningsCallService svc = newService(transcript, disabledClient(), noopPublisher(), 1);

        DemoEarningsCallService.StartResult result = svc.start("ORCL");

        assertThat(result.outcome()).isEqualTo(DemoEarningsCallService.StartResult.Outcome.STARTED);
        assertThat(result.ticker()).isEqualTo("ORCL");
        await().atMost(5, TimeUnit.SECONDS)
                .untilAsserted(() -> assertThat(transcript.accepted).hasSize(result.segmentCount()));

        // sequence 는 스크립트 순서대로, 마지막 것만 세션 종료 플래그가 선다.
        assertThat(transcript.accepted).extracting(TranscriptSegment::sequence)
                .containsExactlyElementsOf(range(result.segmentCount()));
        assertThat(transcript.accepted.get(0).isSessionEnd()).isFalse();
        assertThat(transcript.accepted.get(transcript.accepted.size() - 1).isSessionEnd()).isTrue();
        assertThat(transcript.accepted).allSatisfy(s -> assertThat(s.callId()).isEqualTo(result.callId()));
    }

    @Test
    void 세그먼트_timestamp_는_스크립트값이_아니라_현재시각이다() {
        // AI Engine 이 이 값으로 뉴스 근거 검색 창을 잡는다. 과거값을 넣으면 근거가 0건이 된다.
        RecordingTranscriptService transcript = new RecordingTranscriptService();
        DemoEarningsCallService svc = newService(transcript, disabledClient(), noopPublisher(), 1);
        long before = Instant.now().getEpochSecond();

        svc.start("ORCL");
        await().atMost(5, TimeUnit.SECONDS).until(() -> !transcript.accepted.isEmpty());

        assertThat(transcript.accepted.get(0).timestamp()).isBetween(before, before + 30);
    }

    @Test
    void 같은_종목_중복_시작은_거부된다() {
        DemoEarningsCallService svc = newService(new RecordingTranscriptService(), disabledClient(),
                noopPublisher(), 10_000);

        svc.start("ORCL");
        DemoEarningsCallService.StartResult second = svc.start("ORCL");

        assertThat(second.outcome()).isEqualTo(DemoEarningsCallService.StartResult.Outcome.ALREADY_RUNNING);
    }

    @Test
    void 재생_회차마다_callId_가_달라진다() {
        // 같은 callId 를 재사용하면 TranscriptSessionRegistry 가 SESSION_ENDED 로 전부 거부한다.
        DemoEarningsCallService svc = newService(new RecordingTranscriptService(), disabledClient(),
                noopPublisher(), 10_000);

        String first = svc.start("ORCL").callId();
        svc.stop("ORCL");
        String second = svc.start("ORCL").callId();

        assertThat(first).isNotEqualTo(second);
    }

    @Test
    void 중지하면_남은_세그먼트는_발행되지_않는다() {
        RecordingTranscriptService transcript = new RecordingTranscriptService();
        DemoEarningsCallService svc = newService(transcript, disabledClient(), noopPublisher(), 300);

        svc.start("ORCL");
        await().atMost(3, TimeUnit.SECONDS).until(() -> !transcript.accepted.isEmpty());
        assertThat(svc.stop("ORCL")).isTrue();
        int atStop = transcript.accepted.size();

        // 간격 2회분을 기다려도 더 늘지 않아야 한다.
        await().pollDelay(700, TimeUnit.MILLISECONDS).atMost(3, TimeUnit.SECONDS)
                .untilAsserted(() -> assertThat(transcript.accepted.size()).isLessThanOrEqualTo(atStop + 1));
        assertThat(svc.stop("ORCL")).isFalse();
    }

    @Test
    void 팩트체크_COMPLETED_응답만_발행된다() {
        RecordingPublisher publisher = new RecordingPublisher();
        // 첫 두 문장은 BUFFERING, 세 번째부터 COMPLETED 라고 가정한 스텁.
        AtomicInteger calls = new AtomicInteger();
        AiEngineClient client = new AiEngineClient(null, true) {
            @Override
            public Optional<LiveFactCheckModels.BatchResponse> submitSentence(
                    LiveFactCheckModels.SentenceRequest request) {
                int n = calls.incrementAndGet();
                if (n % 3 != 0) {
                    return Optional.of(batch("BUFFERING", List.of()));
                }
                return Optional.of(batch("COMPLETED", List.of(claim())));
            }
        };
        DemoEarningsCallService svc = newService(new RecordingTranscriptService(), client, publisher, 1);

        int total = svc.start("ORCL").segmentCount();

        await().atMost(5, TimeUnit.SECONDS)
                .untilAsserted(() -> assertThat(calls.get()).isEqualTo(total));
        // 6문장이면 3번째와 6번째, 즉 2회만 발행된다.
        await().atMost(5, TimeUnit.SECONDS)
                .untilAsserted(() -> assertThat(publisher.published).hasSize(total / 3));
    }

    @Test
    void 팩트체크_비활성화면_AI_Engine_을_호출하지_않는다() {
        AtomicInteger calls = new AtomicInteger();
        AiEngineClient client = new AiEngineClient(null, false) {
            @Override
            public Optional<LiveFactCheckModels.BatchResponse> submitSentence(
                    LiveFactCheckModels.SentenceRequest request) {
                calls.incrementAndGet();
                return Optional.empty();
            }
        };
        RecordingTranscriptService transcript = new RecordingTranscriptService();
        DemoEarningsCallService svc = newService(transcript, client, noopPublisher(), 1);

        int total = svc.start("ORCL").segmentCount();

        await().atMost(5, TimeUnit.SECONDS)
                .untilAsserted(() -> assertThat(transcript.accepted).hasSize(total));
        assertThat(calls.get()).isZero();
    }

    @Test
    void 스크립트가_없으면_시작하지_않는다() {
        service = new DemoEarningsCallService(new RecordingTranscriptService(), disabledClient(),
                noopPublisher(), noopSummaryService(), new ObjectMapper(),
                "data/does-not-exist.json", 1, AI_TIMEOUT_MS);

        DemoEarningsCallService.StartResult result = service.start("ORCL");

        assertThat(result.outcome())
                .isEqualTo(DemoEarningsCallService.StartResult.Outcome.SCRIPT_UNAVAILABLE);
        assertThat(result.message()).isNotBlank();
    }

    @Test
    void 재생중이_아니면_상태조회는_비어있다() {
        DemoEarningsCallService svc = newService(new RecordingTranscriptService(), disabledClient(),
                noopPublisher(), 10_000);

        assertThat(svc.status("ORCL")).isEmpty();
        svc.start("ORCL");
        assertThat(svc.status("orcl")).isPresent();
    }


    @Test
    void 정상_종료시_마지막_문장의_팩트체크까지_발행된다() {
        // 마지막 세그먼트는 sleep 없이 루프를 빠져나가고 곧바로 종료 정리에 들어간다.
        // 여기서 큐를 즉시 끊으면 마지막 배치(is_session_end 플러시)가 통째로 사라진다.
        RecordingPublisher publisher = new RecordingPublisher();
        AtomicInteger completed = new AtomicInteger();
        AiEngineClient slowClient = new AiEngineClient(null, true) {
            @Override
            public Optional<LiveFactCheckModels.BatchResponse> submitSentence(
                    LiveFactCheckModels.SentenceRequest request) {
                sleepQuietly(40);   // AI Engine 왕복을 흉내낸다
                completed.incrementAndGet();
                return Optional.of(batch("COMPLETED", List.of(claim())));
            }
        };
        DemoEarningsCallService svc = newService(new RecordingTranscriptService(), slowClient, publisher, 1);

        int total = svc.start("ORCL").segmentCount();

        await().atMost(10, TimeUnit.SECONDS)
                .untilAsserted(() -> assertThat(publisher.published).hasSize(total));
        assertThat(completed.get()).isEqualTo(total);
    }

    @Test
    void 중복_시작이_거부되어도_executor_가_남지_않는다() {
        // putIfAbsent 실패로 버려지는 Session 의 스레드 2개를 회수하지 않으면
        // 버튼 연타 시 요청마다 누적된다.
        DemoEarningsCallService svc = newService(new RecordingTranscriptService(), disabledClient(),
                noopPublisher(), 10_000);
        svc.start("ORCL");
        int before = countDemoThreads();

        for (int i = 0; i < 20; i++) {
            svc.start("ORCL");
        }

        assertThat(countDemoThreads()).isLessThanOrEqualTo(before);
    }

    @Test
    void 재생이_끝나면_마지막_결과를_조회할_수_있다() {
        // 세션은 map 에서 사라지므로, 이게 없으면 "정상 완료" 와 "시작한 적 없음" 이
        // status 에서 구분되지 않는다.
        RecordingTranscriptService transcript = new RecordingTranscriptService();
        DemoEarningsCallService svc = newService(transcript, disabledClient(), noopPublisher(), 1);

        int total = svc.start("ORCL").segmentCount();
        await().atMost(5, TimeUnit.SECONDS)
                .untilAsserted(() -> assertThat(svc.lastRun("ORCL")).isPresent());

        DemoEarningsCallService.LastRun last = svc.lastRun("ORCL").orElseThrow();
        assertThat(last.outcome()).isEqualTo("COMPLETED");
        assertThat(last.publishedCount()).isEqualTo(total);
    }

    @Test
    void 중지하면_마지막_결과가_STOPPED_로_남는다() {
        DemoEarningsCallService svc = newService(new RecordingTranscriptService(), disabledClient(),
                noopPublisher(), 300);

        svc.start("ORCL");
        svc.stop("ORCL");

        assertThat(svc.lastRun("ORCL")).get()
                .extracting(DemoEarningsCallService.LastRun::outcome).isEqualTo("STOPPED");
    }

    @Test
    void 인입이_전부_거부되면_원인을_알_수_있다() {
        // 손으로 고친 스크립트에 sequence 중복이 있는 경우 등. 로그 grep 없이 확인 가능해야 한다.
        DemoEarningsCallService svc = newService(new RejectingTranscriptService(), disabledClient(),
                noopPublisher(), 1);

        svc.start("ORCL");

        await().atMost(5, TimeUnit.SECONDS)
                .untilAsserted(() -> assertThat(svc.lastRun("ORCL")).get()
                        .extracting(DemoEarningsCallService.LastRun::outcome)
                        .isEqualTo("NO_SEGMENT_PUBLISHED"));
    }

    @Test
    void 중지는_즉시_반환한다() {
        // HTTP 워커 스레드에서 호출된다. 팩트체크 큐를 기다리면 "중지" 버튼이 멈춘 것처럼 보인다.
        AiEngineClient slowClient = new AiEngineClient(null, true) {
            @Override
            public Optional<LiveFactCheckModels.BatchResponse> submitSentence(
                    LiveFactCheckModels.SentenceRequest request) {
                sleepQuietly(3_000);
                return Optional.empty();
            }
        };
        DemoEarningsCallService svc = newService(new RecordingTranscriptService(), slowClient,
                noopPublisher(), 50);
        svc.start("ORCL");
        sleepQuietly(200);

        long started = System.nanoTime();
        svc.stop("ORCL");
        long elapsedMs = (System.nanoTime() - started) / 1_000_000;

        assertThat(elapsedMs).isLessThan(1_000);
    }

    // ── 스크립트 검증 ───────────────────────────────────────────────────────────

    @Test
    void 실제_시연_스크립트는_검증을_통과한다() throws Exception {
        DemoEarningsCallService svc = newService(new RecordingTranscriptService(), disabledClient(),
                noopPublisher(), 10_000);

        assertThat(DemoEarningsCallService.validateSegments(svc.loadScript())).isNull();
    }

    @Test
    void sequence_가_0에서_시작하지_않으면_거부된다() {
        // AI Engine 은 ticker 로 버퍼를 잡고 sentence_sequence=0 에서만 리셋한다.
        // 1부터 시작하는 스크립트는 재시작 시 팩트체크만 조용히 전부 사라진다.
        DemoEarningsCallScript script = scriptWithSequences(1, 2, 3);

        assertThat(DemoEarningsCallService.validateSegments(script)).contains("0 부터");
    }

    @Test
    void sequence_가_건너뛰면_거부된다() {
        assertThat(DemoEarningsCallService.validateSegments(scriptWithSequences(0, 1, 3))).isNotNull();
    }

    @Test
    void text_가_비면_거부된다() {
        DemoEarningsCallScript script = new DemoEarningsCallScript("ORCL", "Oracle", "Q4", "demo", null, null, null,
                List.of(new DemoEarningsCallScript.Segment(0, 0, 1, "CEO", "   ")));

        assertThat(DemoEarningsCallService.validateSegments(script)).contains("text");
    }

    private static DemoEarningsCallScript scriptWithSequences(int... sequences) {
        List<DemoEarningsCallScript.Segment> segments = new java.util.ArrayList<>();
        for (int seq : sequences) {
            segments.add(new DemoEarningsCallScript.Segment(seq, 0, 1, "CEO", "sentence " + seq));
        }
        return new DemoEarningsCallScript("ORCL", "Oracle", "Q4", "demo", null, null, null, segments);
    }

    private static int countDemoThreads() {
        return (int) Thread.getAllStackTraces().keySet().stream()
                .filter(t -> t.getName().startsWith("demo-call-"))
                .count();
    }

    private static void sleepQuietly(long millis) {
        try {
            Thread.sleep(millis);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
    }

    // ── 스텁 ────────────────────────────────────────────────────────────────────


    private static List<Integer> range(int size) {
        return java.util.stream.IntStream.range(0, size).boxed().toList();
    }

    /** 비활성 클라이언트. 공개 생성자를 쓰되 enabled=false 라 호출이 발생하지 않는다. */
    private static AiEngineClient disabledClient() {
        return new AiEngineClient("http://localhost:1", false, false, 100);
    }

    @Test
    void call_started_at_이_있으면_그_시각_기준으로_타임스탬프를_찍는다() {
        // 과거 어닝콜을 재생할 때 현재 시각을 찍으면, AI Engine 이 "지금부터 30일" 을
        // 근거 검색 창으로 잡아 그 콜 시점의 뉴스가 통째로 창 밖으로 밀린다.
        long callStart = Instant.parse("2026-08-20T13:00:00Z").getEpochSecond();
        List<DemoEarningsCallScript.Segment> segments = List.of(
                new DemoEarningsCallScript.Segment(0, 0, 5000, "CEO", "첫 문장"),
                new DemoEarningsCallScript.Segment(1, 5000, 11000, "CEO", "둘째 문장"));
        DemoEarningsCallScript script = new DemoEarningsCallScript(
                "WMT", "Walmart", "Q2", "demo-wmt", "2026-08-20T13:00:00Z", null, null, segments);

        assertThat(DemoEarningsCallService.segmentTimestampForTest(script, segments.get(0)))
                .isEqualTo(callStart);
        assertThat(DemoEarningsCallService.segmentTimestampForTest(script, segments.get(1)))
                .isEqualTo(callStart + 5);
    }

    @Test
    void call_started_at_형식이_틀리면_현재시각으로_되돌린다() {
        // 재생 자체를 막지는 않는다. 다만 과거 콜이라면 근거가 사라지므로 로그로 남는다.
        List<DemoEarningsCallScript.Segment> segments =
                List.of(new DemoEarningsCallScript.Segment(0, 0, 5000, "CEO", "문장"));
        DemoEarningsCallScript script = new DemoEarningsCallScript(
                "WMT", "Walmart", "Q2", "demo-wmt", "2026년 8월 20일", null, null, segments);

        long before = Instant.now().getEpochSecond();
        long actual = DemoEarningsCallService.segmentTimestampForTest(script, segments.get(0));

        assertThat(actual).isBetween(before, Instant.now().getEpochSecond());
    }

    @Test
    void 재생이_정상_종료되면_종합_판단이_한_번_돈다() {
        RecordingSummaryService summary = new RecordingSummaryService();
        DemoEarningsCallService svc = newService(new RecordingTranscriptService(), disabledClient(),
                noopPublisher(), summary, 1);

        DemoEarningsCallService.StartResult result = svc.start("ORCL");

        await().atMost(5, TimeUnit.SECONDS).untilAsserted(() -> assertThat(summary.calls).hasSize(1));
        assertThat(summary.calls.get(0)).isEqualTo("ORCL|" + result.callId());
    }

    @Test
    void 중지된_회차는_종합_판단을_만들지_않는다() {
        // 일부만 재생된 어닝콜로 "콜 전체를 보고 낸 판단" 을 만들면 결론이 왜곡된다.
        RecordingTranscriptService transcript = new RecordingTranscriptService();
        RecordingSummaryService summary = new RecordingSummaryService();
        DemoEarningsCallService svc = newService(transcript, disabledClient(), noopPublisher(), summary, 300);

        svc.start("ORCL");
        await().atMost(3, TimeUnit.SECONDS).until(() -> !transcript.accepted.isEmpty());
        assertThat(svc.stop("ORCL")).isTrue();

        await().pollDelay(700, TimeUnit.MILLISECONDS).atMost(3, TimeUnit.SECONDS)
                .untilAsserted(() -> assertThat(summary.calls).isEmpty());
    }

    @Test
    void 세그먼트를_하나도_발행하지_못하면_종합_판단을_만들지_않는다() {
        // 콜이 재생되지 않았는데 "콜 전체를 보고 낸 판단" 이 나오면 안 된다.
        RecordingSummaryService summary = new RecordingSummaryService();
        DemoEarningsCallService svc = newService(new RejectingTranscriptService(), disabledClient(),
                noopPublisher(), summary, 1);

        svc.start("ORCL");

        await().atMost(5, TimeUnit.SECONDS).untilAsserted(() ->
                assertThat(svc.lastRun("ORCL")).isPresent());
        assertThat(summary.calls).isEmpty();
    }

    @Test
    void shutdownAll_이_종합_판단_스레드를_회수한다() {
        DemoEarningsCallService svc = newService(new RecordingTranscriptService(), disabledClient(),
                noopPublisher(), new RecordingSummaryService(), 1);
        svc.start("ORCL");
        await().atMost(5, TimeUnit.SECONDS).until(() -> svc.lastRun("ORCL").isPresent());

        svc.shutdownAll();
        service = null;

        await().atMost(5, TimeUnit.SECONDS).untilAsserted(() ->
                assertThat(Thread.getAllStackTraces().keySet())
                        .noneMatch(thread -> "demo-call-summary".equals(thread.getName())));
    }

    /** 종합 판단 호출을 기록만 하는 스텁. */
    private static final class RecordingSummaryService extends EarningsSummaryService {
        final List<String> calls = new CopyOnWriteArrayList<>();

        RecordingSummaryService() {
            super(new AiEngineClient("http://localhost:1", false, false, 100), null, null);
        }

        @Override
        public boolean summarizeAndPublish(String ticker, String callId, DemoEarningsCallScript script) {
            calls.add(ticker + "|" + callId);
            return true;
        }
    }

    /**
     * 종합 판단을 하지 않는 서비스. summary-enabled=false 인 클라이언트를 물려 두면
     * publisher/가격캐시에는 손도 대지 않으므로 null 로 충분하다. 이 테스트가 검증하는
     * 것은 재생 경로이지 종합 판단이 아니다.
     */
    private EarningsSummaryService noopSummaryService() {
        return new EarningsSummaryService(new AiEngineClient("http://localhost:1", false, false, 100),
                null, null);
    }

    private static FactCheckPublisher noopPublisher() {
        return new FactCheckPublisher(null) {
            @Override
            public void publish(String ticker, String callId, LiveFactCheckModels.BatchResponse batch) {
            }
        };
    }

    private static LiveFactCheckModels.BatchResponse batch(String status,
                                                           List<LiveFactCheckModels.Claim> claims) {
        return new LiveFactCheckModels.BatchResponse(
                "ORCL", status, 0, 0, 2, claims, 0, true, true, List.of());
    }

    private static LiveFactCheckModels.Claim claim() {
        return new LiveFactCheckModels.Claim("ORCL:0-2:c1", 0, "src", "claim", "numeric_fact",
                "CONTRADICTED", 0.85, "설명", "contradicted_by_news", List.of(), 2, 2);
    }

    /** 모든 인입을 거부한다. 스크립트 결함으로 세그먼트가 하나도 안 나가는 상황을 흉내낸다. */
    private static final class RejectingTranscriptService extends TranscriptService {
        RejectingTranscriptService() {
            super(new TranscriptSessionRegistry(), null);
        }

        @Override
        public TranscriptSessionRegistry.Result accept(TranscriptSegment segment) {
            return TranscriptSessionRegistry.Result.SEQ_REGRESS;
        }
    }

    private static final class RecordingTranscriptService extends TranscriptService {
        final List<TranscriptSegment> accepted = new CopyOnWriteArrayList<>();

        RecordingTranscriptService() {
            super(new TranscriptSessionRegistry(), null);
        }

        @Override
        public TranscriptSessionRegistry.Result accept(TranscriptSegment segment) {
            accepted.add(segment);
            return TranscriptSessionRegistry.Result.OK;
        }
    }

    private static final class RecordingPublisher extends FactCheckPublisher {
        final List<String> published = new CopyOnWriteArrayList<>();

        RecordingPublisher() {
            super(null);
        }

        @Override
        public void publish(String ticker, String callId, LiveFactCheckModels.BatchResponse batch) {
            if (batch != null && batch.isCompleted() && batch.hasClaims()) {
                published.add(callId);
            }
        }
    }
}
