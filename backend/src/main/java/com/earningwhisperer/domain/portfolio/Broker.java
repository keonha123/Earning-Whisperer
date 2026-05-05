package com.earningwhisperer.domain.portfolio;

/**
 * 증권사 식별자. 현재는 KIS(한국투자증권) 만 지원하며 다른 증권사 추가 시 enum 값 확장.
 *
 * <p>BrokerAccount 의 broker 컬럼에 저장되어 동일 사용자가 다중 증권사 / 다중 계정을 보유할 수 있는
 * 데이터 모델 토대를 제공한다.
 */
public enum Broker {
    KIS,
}
