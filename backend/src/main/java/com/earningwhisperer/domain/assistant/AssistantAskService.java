package com.earningwhisperer.domain.assistant;

import com.earningwhisperer.domain.transcript.TranscriptSegment;
import com.earningwhisperer.domain.transcript.TranscriptSegmentStore;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;

import java.util.List;

/**
 * 질의응답 요청을 logothea-assistant 로 넘길 형태로 준비한다 (#112).
 *
 * <p>질문 시점(as_of)은 서버가 정한다. 터미널이 보낸 sequence 를 Redis 에 실제로 저장된 마지막 세그먼트 이하로 낮추고,
 * 그 세그먼트의 발행 시각을 as_of_epoch 로 쓴다. 세그먼트 저장은 비동기라 터미널이 받은 sequence 가 저장보다 앞설 수 있다.
 * 근거 시점 필터(뉴스 발행 시각 등)는 이 값으로 걸린다.
 */
@Service
@RequiredArgsConstructor
public class AssistantAskService {

    private final TranscriptSegmentStore segmentStore;

    public record HistoryTurn(String role, String text) {}

    public record AskCommand(Long userId, String ticker, String callId, int asOfSequence, Integer anchorSequence,
                             String question, String suggestedQuestionId, List<HistoryTurn> history) {}

    public record PreparedAsk(Long userId, String ticker, String callId, int asOfSequence, long asOfEpoch,
                              Integer anchorSequence, boolean callEnded, String question,
                              String suggestedQuestionId, List<HistoryTurn> history) {}

    public PreparedAsk prepare(AskCommand command) {
        List<TranscriptSegment> segments = segmentStore.findUntil(command.callId(), command.asOfSequence());
        if (segments.isEmpty()) {
            throw new AssistantAskException(AssistantAskException.Reason.SEGMENTS_NOT_FOUND);
        }
        TranscriptSegment last = segments.get(segments.size() - 1);
        if (!last.ticker().equalsIgnoreCase(command.ticker().trim())) {
            throw new AssistantAskException(AssistantAskException.Reason.TICKER_MISMATCH);
        }
        // 추천 질문은 콜 전체 범위로 답한다. 대목은 낮춘 as_of 안에 있을 때만 쓴다.
        Integer anchor = command.suggestedQuestionId() != null ? null : command.anchorSequence();
        if (anchor != null && anchor > last.sequence()) {
            anchor = null;
        }
        return new PreparedAsk(command.userId(), last.ticker(), command.callId(), last.sequence(), last.timestamp(),
                anchor, last.isSessionEnd(), command.question(), command.suggestedQuestionId(), command.history());
    }
}
