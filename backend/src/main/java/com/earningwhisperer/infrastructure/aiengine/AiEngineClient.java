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
 * <p>{@code fact-check-enabled=false} 로 두면 호출 자체를 하지 않는다. AI Engine 을
 * 띄우지 않고 트랜스크립트 재생만 시연할 때 쓴다.
 */
@Slf4j
@Component
public class AiEngineClient {

    private static final String SENTENCE_PATH = "/v1/engine/live-fact-check/sentence";

    private final RestClient restClient;
    private final boolean factCheckEnabled;

    /**
     * 생성자가 둘이므로 Spring 이 쓸 것을 명시한다. 없으면 기본 생성자를 찾다가
     * BeanInstantiationException 으로 기동이 실패한다.
     */
    @Autowired
    public AiEngineClient(
            @Value("${ai-engine.base-url:http://localhost:8000}") String baseUrl,
            @Value("${ai-engine.fact-check-enabled:true}") boolean factCheckEnabled,
            @Value("${ai-engine.timeout-ms:8000}") long timeoutMs
    ) {
        this.factCheckEnabled = factCheckEnabled;
        // 연결 타임아웃은 짧게(응답 없는 호스트를 오래 붙들 이유가 없다), 읽기 타임아웃은
        // LLM 2패스 소요시간(실측 약 5초)을 감안해 설정값을 그대로 쓴다.
        SimpleClientHttpRequestFactory factory = new SimpleClientHttpRequestFactory();
        factory.setConnectTimeout(Duration.ofMillis(Math.min(2000, timeoutMs)));
        factory.setReadTimeout(Duration.ofMillis(timeoutMs));
        this.restClient = RestClient.builder()
                .baseUrl(baseUrl)
                .requestFactory(factory)
                .build();
        log.info("[AiEngine] 클라이언트 초기화 - baseUrl={} factCheckEnabled={} timeoutMs={}",
                baseUrl, factCheckEnabled, timeoutMs);
    }

    /**
     * 테스트용 생성자. 다른 패키지의 테스트가 이 클래스를 상속해 스텁을 만들 수 있도록
     * protected 로 둔다. 프로덕션 코드에서는 사용하지 않는다.
     */
    protected AiEngineClient(RestClient restClient, boolean factCheckEnabled) {
        this.restClient = restClient;
        this.factCheckEnabled = factCheckEnabled;
    }

    public boolean isFactCheckEnabled() {
        return factCheckEnabled;
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
}
