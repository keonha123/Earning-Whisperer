package com.earningwhisperer.infrastructure.redis;

import com.earningwhisperer.domain.signal.EmaService;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.Spy;
import org.mockito.junit.jupiter.MockitoExtension;

import static org.mockito.ArgumentMatchers.anyDouble;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.*;

@ExtendWith(MockitoExtension.class)
@DisplayName("TradingSignalSubscriber 단위 테스트")
class TradingSignalSubscriberTest {

    @Mock
    private EmaService emaService;

    @Spy
    private ObjectMapper objectMapper;

    @InjectMocks
    private TradingSignalSubscriber subscriber;

    private static final String VALID_MESSAGE = """
            {
              "ticker": "NVDA",
              "raw_score": 0.85,
              "rationale": "Strong earnings beat",
              "text_chunk": "Revenue exceeded expectations",
              "timestamp": 1710000000
            }
            """;

    @Test
    @DisplayName("정상 메시지 수신 시 EmaService.process()가 올바른 인자로 호출된다")
    void 정상_메시지_수신시_EmaService가_호출된다() {
        // Arrange
        when(emaService.process("NVDA", 0.85)).thenReturn(0.8);

        // Act
        subscriber.handleMessage(VALID_MESSAGE);

        // Assert
        verify(emaService).process(eq("NVDA"), eq(0.85));
    }

    @Test
    @DisplayName("JSON 파싱 실패 시 EmaService는 호출되지 않는다")
    void JSON_파싱_실패시_EmaService는_호출되지_않는다() {
        // Arrange
        String invalidMessage = "{ invalid json }";

        // Act — 예외가 서버 밖으로 전파되면 안 됨
        subscriber.handleMessage(invalidMessage);

        // Assert
        verify(emaService, never()).process(anyString(), anyDouble());
    }

    @Test
    @DisplayName("빈 문자열 수신 시 EmaService는 호출되지 않는다")
    void 빈_문자열_수신시_EmaService는_호출되지_않는다() {
        // Act
        subscriber.handleMessage("");

        // Assert
        verify(emaService, never()).process(anyString(), anyDouble());
    }

    @Test
    @DisplayName("EmaService.process()가 반환한 emaScore 값을 정상적으로 처리한다")
    void emaScore_반환값을_정상처리한다() {
        // Arrange
        when(emaService.process("NVDA", 0.85)).thenReturn(0.78);

        // Act — 예외 없이 완료되어야 함
        subscriber.handleMessage(VALID_MESSAGE);

        // Assert
        verify(emaService).process("NVDA", 0.85);
    }
}
