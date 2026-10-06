package com.earningwhisperer.presentation.assistant;

import com.earningwhisperer.domain.assistant.AssistantAskService.AskCommand;
import com.earningwhisperer.domain.assistant.AssistantAskService.HistoryTurn;
import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.annotation.JsonNaming;
import jakarta.validation.Valid;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;

import java.util.List;

/** {@code POST /api/v1/assistant/ask} 요청(api-spec 7.10). 대화 상태는 터미널이 보관해 매번 보낸다. */
@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
public record AssistantAskRequest(
        @NotBlank @Size(max = 10) String ticker,
        @NotBlank @Size(max = 200) String callId,
        @NotNull @Min(0) Integer asOfSequence,
        @Min(0) Integer anchorSequence,
        @NotBlank @Size(max = 500) String question,
        @Pattern(regexp = "summary|vs_last_quarter|guidance|vs_expectations|risks") String suggestedQuestionId,
        @Size(max = 6) List<@Valid @NotNull Turn> history
) {

    @JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
    public record Turn(@NotNull @Pattern(regexp = "user|assistant") String role,
                       @NotBlank @Size(max = 4000) String text) {}

    AskCommand toCommand(Long userId) {
        List<HistoryTurn> turns = history == null ? List.of()
                : history.stream().map(turn -> new HistoryTurn(turn.role(), turn.text())).toList();
        return new AskCommand(userId, ticker, callId, asOfSequence, anchorSequence, question.trim(),
                suggestedQuestionId, turns);
    }
}
