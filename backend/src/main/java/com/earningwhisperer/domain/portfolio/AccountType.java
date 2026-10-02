package com.earningwhisperer.domain.portfolio;

/**
 * BrokerAccount 의 계정 종류. broker + isPaper 두 필드를 단일 열거값으로 통합.
 *
 * <ul>
 *   <li>KIS_REAL  — 한국투자증권 실전 계좌</li>
 *   <li>KIS_PAPER — 한국투자증권 모의 계좌</li>
 *   <li>SELF_PAPER — 자체 페이퍼 트레이딩 (KIS 미지원 데이마켓 등 우회용)</li>
 * </ul>
 *
 * <p>증권사 추가 시 MIRAE_REAL / KIWOOM_REAL 형태로 일관 확장 가능.
 */
public enum AccountType {
    KIS_REAL,
    KIS_PAPER,
    SELF_PAPER;

    public boolean isKisBased() {
        return this == KIS_REAL || this == KIS_PAPER;
    }

    public boolean isPaper() {
        return this == KIS_PAPER || this == SELF_PAPER;
    }
}
