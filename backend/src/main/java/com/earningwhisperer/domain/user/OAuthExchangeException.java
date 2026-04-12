package com.earningwhisperer.domain.user;

/**
 * OAuth code → profile 교환 실패 시 발생하는 예외.
 * 도메인 레이어에 위치하여 프레젠테이션 → 인프라 의존을 방지.
 */
public class OAuthExchangeException extends RuntimeException {
    public OAuthExchangeException(String message) {
        super(message);
    }
}
