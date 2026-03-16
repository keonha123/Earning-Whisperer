package com.earningwhisperer.domain.portfolio;

public enum TradingMode {
    MANUAL,      // 수동 모드: AI 시그널만 표시, 매매 차단
    SEMI_AUTO,   // 반자동 모드: 시그널 발생 시 사용자 승인 팝업
    AUTO_PILOT   // 완전 자동 모드: 백엔드가 룰에 따라 자동 매매
}
