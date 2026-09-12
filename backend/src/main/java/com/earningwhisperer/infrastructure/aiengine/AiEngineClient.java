package com.earningwhisperer.infrastructure.aiengine;

import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.MediaType;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;

import java.time.Duration;
import java.util.Optional;

/**
 * AI Engine 호출 클라이언트 (Contract 9).
 *
 * <p>정책: <b>시연 중 화면이 멈추는 것보다 팩트체크가 빠지는 편이 낫다.</b>
 * 따라서 모든 실패(타임아웃 / 4xx / 5xx / 역직렬화 오류)를 흡수해
 * {@link Optional#empty()} 로 돌려주고 예외를 재던지지 않는다. 호출자는 결과가 없으면
 * 그냥 발행을 건너뛴다.
 *
 * <p>{@code fact-check-enabled=false} / {@code summary-enabled=false} 로 두면 각각
 * 호출 자체를 하지 않는다. AI Engine 을 띄우지 않고 트랜스크립트 재생만 시연할 때 쓴다.
 */
@Slf4j
@Component
public class AiEngineClient {

    private static final String SENTENCE_PATH = "/v1/engine/live-fact-check/sentence";
    private static final String ANALYZE_PATH = "/v1/engine/analyze";
    private static final String INTELLIGENCE_PATH = "/v1/engine/earnings/intelligence";
    private static final String READINESS_PATH = "/v1/engine/evidence/readiness";

    private final RestClient restClient;
    private final boolean factCheckEnabled;
    private final boolean summaryEnabled;

    /**
     * 생성자가 여럿이므로 Spring 이 쓸 것을 명시한다. 없으면 기본 생성자를 찾다가
     * BeanInstantiationException 으로 기동이 실패한다.
     */
    @Autowired
    public AiEngineClient(
            @Value("${ai-engine.base-url:http://localhost:8000}") String baseUrl,
            @Value("${ai-engine.fact-check-enabled:true}") boolean factCheckEnabled,
            @Value("${ai-engine.summary-enabled:true}") boolean summaryEnabled,
            @Value("${ai-engine.timeout-ms:8000}") long timeoutMs
    ) {
        this.factCheckEnabled = factCheckEnabled;
        this.summaryEnabled = summaryEnabled;
        // 연결 타임아웃은 짧게(응답 없는 호스트를 오래 붙들 이유가 없다), 읽기 타임아웃은
        // LLM 2패스 소요시간(실측 약 5초)을 감안해 설정값을 그대로 쓴다.
        SimpleClientHttpRequestFactory factory = new SimpleClientHttpRequestFactory();
        factory.setConnectTimeout(Duration.ofMillis(Math.min(2000, timeoutMs)));
        factory.setReadTimeout(Duration.ofMillis(timeoutMs));
        this.restClient = RestClient.builder()
                .baseUrl(baseUrl)
                .requestFactory(factory)
                .build();
        log.info("[AiEngine] 클라이언트 초기화 - baseUrl={} factCheckEnabled={} summaryEnabled={} timeoutMs={}",
                baseUrl, factCheckEnabled, summaryEnabled, timeoutMs);
    }

    /**
     * 테스트용 생성자. 다른 패키지의 테스트가 이 클래스를 상속해 스텁을 만들 수 있도록
     * protected 로 둔다. 프로덕션 코드에서는 사용하지 않는다.
     */
    protected AiEngineClient(RestClient restClient, boolean factCheckEnabled) {
        this(restClient, factCheckEnabled, factCheckEnabled);
    }

    /** 테스트용 생성자. 팩트체크와 종합 분석을 따로 켜고 끌 때 쓴다. */
    protected AiEngineClient(RestClient restClient, boolean factCheckEnabled, boolean summaryEnabled) {
        this.restClient = restClient;
        this.factCheckEnabled = factCheckEnabled;
        this.summaryEnabled = summaryEnabled;
    }

    public boolean isFactCheckEnabled() {
        return factCheckEnabled;
    }

    public boolean isSummaryEnabled() {
        return summaryEnabled;
    }

    /**
     * 확정된 어닝콜 문장 1개를 제출한다.
     *
     * <p>AI Engine 은 ticker 별 3문장 버퍼를 유지하므로 <b>같은 ticker 의 호출은 순서대로
     * 직렬화되어야 한다.</b> 순서가 뒤집히면 sequence 역행으로 REJECTED 가 나고 해당 문장이
     * 버려진다. 호출자 책임이다.
     *
     * @return 응답. 비활성화되었거나 호출이 실패하면 empty.
     */
    public Optional<LiveFactCheckModels.BatchResponse> submitSentence(LiveFactCheckModels.SentenceRequest request) {
        if (!factCheckEnabled) {
            return Optional.empty();
        }
        try {
            LiveFactCheckModels.BatchResponse response = restClient.post()
                    .uri(SENTENCE_PATH)
                    .contentType(MediaType.APPLICATION_JSON)
                    .body(request)
                    .retrieve()
                    .body(LiveFactCheckModels.BatchResponse.class);
            if (response == null) {
                log.warn("[AiEngine] 빈 응답 - ticker={} sequence={}", request.ticker(), request.sentenceSequence());
                return Optional.empty();
            }
            return Optional.of(response);
        } catch (Exception e) {
            // 시연 중단을 막기 위해 모든 예외를 흡수한다. 원인은 로그로만 남긴다.
            log.warn("[AiEngine] 팩트체크 호출 실패 - ticker={} sequence={} error={}",
                    request.ticker(), request.sentenceSequence(), e.toString());
            return Optional.empty();
        }
    }

    /**
     * 어닝콜 전문을 넘겨 LLM 종합 판단을 받는다 (Contract 9.6).
     *
     * <p>리뷰 모델까지 태우므로 팩트체크 한 배치보다 느리다. 재생 스레드에서 부르지 말 것.
     *
     * @return 응답. 비활성화되었거나 호출이 실패하면 empty.
     */
    public Optional<EarningsSummaryModels.AnalyzeResponse> analyze(EarningsSummaryModels.AnalyzeRequest request) {
        return post(ANALYZE_PATH, request, EarningsSummaryModels.AnalyzeResponse.class, request.ticker(), "종합 판단");
    }

    /**
     * 회피 탐지 · 연쇄 영향 · 손절 계획을 한 번에 받는다 (Contract 9.7).
     *
     * <p>이쪽은 LLM 을 타지 않는 규칙 기반이라 빠르다.
     *
     * @return 응답. 비활성화되었거나 호출이 실패하면 empty.
     */
    public Optional<EarningsSummaryModels.IntelligenceResponse> earningsIntelligence(
            EarningsSummaryModels.IntelligenceRequest request) {
        return post(INTELLIGENCE_PATH, request, EarningsSummaryModels.IntelligenceResponse.class,
                request.ticker(), "종합 인텔리전스");
    }

    /**
     * 종합 분석 계열 POST 공통 경로.
     *
     * <p>{@link #submitSentence} 와 같은 정책 — 실패를 흡수하고 empty 를 돌려준다.
     * 종합 화면 한 장 때문에 어닝콜 재생 종료가 막히면 안 된다.
     */
    private <T> Optional<T> post(String path, Object body, Class<T> responseType, String ticker, String label) {
        if (!summaryEnabled) {
            return Optional.empty();
        }
        try {
            T response = restClient.post()
                    .uri(path)
                    .contentType(MediaType.APPLICATION_JSON)
                    .body(body)
                    .retrieve()
                    .body(responseType);
            if (response == null) {
                log.warn("[AiEngine] {} 빈 응답 - ticker={}", label, ticker);
                return Optional.empty();
            }
            return Optional.of(response);
        } catch (Exception e) {
            log.warn("[AiEngine] {} 호출 실패 - ticker={} error={}", label, ticker, e.toString());
            return Optional.empty();
        }
    }

    /**
     * 근거 저장소 준비 상태를 확인한다 (Contract 9.8).
     *
     * <p>임베딩 호출 없이 개수만 세므로 빠르다. 재생 시작 버튼 경로에서 동기로 불러도 된다.
     *
     * @param asOfEpochSecond 기준 시각. 과거 콜을 재생할 때는 그 콜의 시각을 넘겨야 한다.
     * @return 응답. 비활성화되었거나 호출이 실패하면 empty.
     */
    public Optional<EarningsSummaryModels.EvidenceReadiness> evidenceReadiness(String ticker, Long asOfEpochSecond) {
        if (!summaryEnabled && !factCheckEnabled) {
            return Optional.empty();
        }
        try {
            EarningsSummaryModels.EvidenceReadiness response = restClient.get()
                    .uri(uriBuilder -> {
                        uriBuilder.path(READINESS_PATH).queryParam("ticker", ticker);
                        if (asOfEpochSecond != null) {
                            uriBuilder.queryParam("as_of", asOfEpochSecond);
                        }
                        return uriBuilder.build();
                    })
                    .retrieve()
                    .body(EarningsSummaryModels.EvidenceReadiness.class);
            return Optional.ofNullable(response);
        } catch (Exception e) {
            // 확인 자체가 실패한 것은 재생을 막을 이유가 아니다. 경고만 못 띄운다.
            log.warn("[AiEngine] 근거 준비 확인 실패 - ticker={} error={}", ticker, e.toString());
            return Optional.empty();
        }
    }
}
