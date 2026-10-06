package com.earningwhisperer.domain.transcript;

import com.earningwhisperer.infrastructure.translation.TranscriptTranslationService;
import com.earningwhisperer.infrastructure.websocket.TranscriptPublisher;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;

@ExtendWith(MockitoExtension.class)
@DisplayName("TranscriptService")
class TranscriptServiceTest {

    @Mock TranscriptPublisher publisher;
    @Mock TranscriptTranslationService translationService;

    private static TranscriptSegment segment(int sequence) {
        return new TranscriptSegment("WMT", "call-1", sequence, 0, 1000, "Comp sales were 2.6%.", null, 1L, false);
    }

    @Test
    @DisplayName("발행한 세그먼트를 번역에 넘긴다")
    void 번역_예약() {
        TranscriptService service = new TranscriptService(new TranscriptSessionRegistry(), publisher, translationService);

        service.accept(segment(0));

        verify(publisher).publish(segment(0));
        verify(translationService).submit(segment(0));
    }

    @Test
    @DisplayName("거부한 세그먼트는 번역에 넘기지 않는다")
    void 거부_시_번역_안함() {
        TranscriptService service = new TranscriptService(new TranscriptSessionRegistry(), publisher, translationService);
        service.accept(segment(5));

        TranscriptSessionRegistry.Result result = service.accept(segment(4));

        assertThat(result).isNotEqualTo(TranscriptSessionRegistry.Result.OK);
        verify(translationService, never()).submit(segment(4));
    }

    @Test
    @DisplayName("번역 예약이 실패해도 인입 결과는 OK 다")
    void 번역_실패_격리() {
        doThrow(new IllegalStateException("boom")).when(translationService).submit(any());
        TranscriptService service = new TranscriptService(new TranscriptSessionRegistry(), publisher, translationService);

        assertThat(service.accept(segment(0))).isEqualTo(TranscriptSessionRegistry.Result.OK);
        verify(publisher).publish(segment(0));
    }
}
