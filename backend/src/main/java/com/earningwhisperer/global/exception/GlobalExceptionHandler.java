package com.earningwhisperer.global.exception;

import com.earningwhisperer.domain.trade.TradeStateConflictException;
import org.springframework.dao.CannotAcquireLockException;
import org.springframework.dao.PessimisticLockingFailureException;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

import java.util.Map;

/**
 * 전역 예외 핸들러.
 *
 * api-spec.md Common Rules: 에러 응답은 {"error": "에러 상세 원인"} + HTTP 4xx/500 형식.
 */
@RestControllerAdvice
public class GlobalExceptionHandler {

    @ExceptionHandler(IllegalArgumentException.class)
    public ResponseEntity<Map<String, String>> handleIllegalArgument(IllegalArgumentException e) {
        return ResponseEntity.status(HttpStatus.BAD_REQUEST)
                .body(Map.of("error", e.getMessage()));
    }

    @ExceptionHandler(MethodArgumentNotValidException.class)
    public ResponseEntity<Map<String, String>> handleValidation(MethodArgumentNotValidException e) {
        String message = e.getBindingResult().getFieldErrors().stream()
                .map(fe -> fe.getField() + ": " + fe.getDefaultMessage())
                .findFirst()
                .orElse("입력값이 올바르지 않습니다.");
        return ResponseEntity.status(HttpStatus.BAD_REQUEST)
                .body(Map.of("error", message));
    }

    @ExceptionHandler(TradeStateConflictException.class)
    public ResponseEntity<Map<String, String>> handleTradeStateConflict(TradeStateConflictException e) {
        return ResponseEntity.status(HttpStatus.CONFLICT)
                .body(Map.of("error", e.getMessage()));
    }

    /**
     * DB 비관적 락 획득 실패 → 503 Service Unavailable.
     *
     * <p>{@link PessimisticLockingFailureException} (Spring 의 lock acquisition 실패 wrapper)
     * 와 {@link CannotAcquireLockException} (DB 락 획득 실패 — InnoDB 등) 을 모두 처리한다.
     * Trade 콜백의 {@code SELECT ... FOR UPDATE} 가 3초 내 락을 잡지 못하면
     * 동시 처리 충돌로 간주하고 클라이언트에 재시도를 안내한다.
     */
    @ExceptionHandler({PessimisticLockingFailureException.class, CannotAcquireLockException.class})
    public ResponseEntity<Map<String, String>> handleLockAcquisitionFailure(Exception e) {
        return ResponseEntity.status(HttpStatus.SERVICE_UNAVAILABLE)
                .header(HttpHeaders.RETRY_AFTER, "1")
                .body(Map.of("error", "동시 처리로 일시 충돌이 발생했습니다. 재시도 부탁드립니다."));
    }
}
