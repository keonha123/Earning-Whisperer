package com.earningwhisperer.domain.signal;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.test.util.ReflectionTestUtils;

import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.within;
import static org.mockito.ArgumentMatchers.anyDouble;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.BDDMockito.given;
import static org.mockito.Mockito.verify;

@ExtendWith(MockitoExtension.class)
@DisplayName("EmaService 단위 테스트")
class EmaServiceTest {

    @Mock
    private EmaStateStore emaStateStore;

    @InjectMocks
    private EmaService emaService;

    @BeforeEach
    void setUp() {
        ReflectionTestUtils.setField(emaService, "windowSize", 10);
    }

    @Test
    @DisplayName("첫 번째 신호: 저장된 EMA가 없으면 rawScore가 그대로 저장되고 반환된다")
    void 첫번째_신호_저장된_EMA가_없으면_rawScore가_초기값으로_저장된다() {
        // Arrange
        String ticker = "NVDA";
        double rawScore = 0.85;
        given(emaStateStore.findByTicker(ticker)).willReturn(Optional.empty());

        // Act
        double result = emaService.process(ticker, rawScore);

        // Assert
        // prevEma = rawScore이므로 결과도 rawScore와 동일
        assertThat(result).isCloseTo(rawScore, within(1e-10));
        verify(emaStateStore).save(eq(ticker), anyDouble());
    }

    @Test
    @DisplayName("두 번째 신호: 이전 EMA가 있으면 공식을 적용한 값을 저장하고 반환한다")
    void 두번째_신호_이전_EMA가_있으면_공식을_적용한다() {
        // Arrange
        String ticker = "NVDA";
        double rawScore = 0.85;
        double prevEma  = 0.50;
        given(emaStateStore.findByTicker(ticker)).willReturn(Optional.of(prevEma));

        double alpha    = 2.0 / (10 + 1);
        double expected = alpha * rawScore + (1 - alpha) * prevEma;

        // Act
        double result = emaService.process(ticker, rawScore);

        // Assert
        assertThat(result).isCloseTo(expected, within(1e-10));
        verify(emaStateStore).save(ticker, result);
    }

    @Test
    @DisplayName("process() 호출 시 EmaStateStore.save()가 반드시 1회 호출된다")
    void process_호출시_save가_반드시_1회_호출된다() {
        // Arrange
        given(emaStateStore.findByTicker("TSLA")).willReturn(Optional.of(0.3));

        // Act
        emaService.process("TSLA", 0.6);

        // Assert
        verify(emaStateStore).save(eq("TSLA"), anyDouble());
    }

    @Test
    @DisplayName("서로 다른 ticker는 독립적인 EMA 상태를 가진다")
    void 서로_다른_ticker는_독립적인_EMA_상태를_가진다() {
        // Arrange
        given(emaStateStore.findByTicker("NVDA")).willReturn(Optional.of(0.7));
        given(emaStateStore.findByTicker("TSLA")).willReturn(Optional.of(-0.2));

        // Act
        double nvdaEma = emaService.process("NVDA", 0.9);
        double tslaEma = emaService.process("TSLA", -0.5);

        // Assert — 두 종목의 EMA는 서로 다른 값
        assertThat(nvdaEma).isNotEqualTo(tslaEma);
        verify(emaStateStore).save(eq("NVDA"), anyDouble());
        verify(emaStateStore).save(eq("TSLA"), anyDouble());
    }
}
