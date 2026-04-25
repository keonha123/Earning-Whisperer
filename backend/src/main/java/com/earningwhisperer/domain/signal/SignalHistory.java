package com.earningwhisperer.domain.signal;

import com.earningwhisperer.domain.user.User;
import jakarta.persistence.*;
import lombok.AccessLevel;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;

import java.time.LocalDateTime;

@Getter
@NoArgsConstructor(access = AccessLevel.PROTECTED)
@Entity
@Table(name = "signal_history", indexes = {
        @Index(name = "idx_signal_user_ticker", columnList = "user_id, ticker"),
        @Index(name = "idx_signal_created_at", columnList = "created_at")
})
public class SignalHistory {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "user_id", nullable = false)
    private User user;

    @Column(nullable = false, length = 20)
    private String ticker;

    /**
     * AI 엔진이 시계열 맥락까지 반영해 도출한 최종 점수 (-1.0 ~ +1.0)
     */
    @Column(nullable = false)
    private Double aiScore;

    /**
     * LLM이 생성한 매매 근거 해설
     */
    @Column(nullable = false, columnDefinition = "TEXT")
    private String rationale;

    /**
     * 분석에 사용된 원문 텍스트 (STT 결과)
     */
    @Column(nullable = false, columnDefinition = "TEXT")
    private String textChunk;

    /**
     * 백엔드 룰 엔진의 최종 결정
     */
    @Enumerated(EnumType.STRING)
    @Column(nullable = false, length = 10)
    private TradeAction action;

    /**
     * AI 분석 완료 시점 (UTC Unix Epoch Second)
     */
    @Column(nullable = false)
    private Long signalTimestamp;

    @Column(nullable = false)
    private LocalDateTime createdAt;

    @PrePersist
    protected void onCreate() {
        this.createdAt = LocalDateTime.now();
    }

    @Builder
    public SignalHistory(User user, String ticker, Double aiScore,
                         String rationale, String textChunk, TradeAction action, Long signalTimestamp) {
        this.user = user;
        this.ticker = ticker;
        this.aiScore = aiScore;
        this.rationale = rationale;
        this.textChunk = textChunk;
        this.action = action;
        this.signalTimestamp = signalTimestamp;
    }
}
