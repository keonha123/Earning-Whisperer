package com.earningwhisperer.infrastructure.broker;

import lombok.Getter;
import lombok.Setter;
import org.springframework.boot.context.properties.ConfigurationProperties;

/**
 * 한국투자증권(KIS) 모의투자 API 설정.
 * 환경변수로 민감 정보를 주입한다.
 *
 * broker.kis.app-key=${KIS_APP_KEY}
 * broker.kis.app-secret=${KIS_APP_SECRET}
 */
@Getter
@Setter
@ConfigurationProperties("broker.kis")
public class KisBrokerProperties {

    /** KIS 모의투자 API 베이스 URL */
    private String baseUrl = "https://openapivts.koreainvestment.com:29443";

    /** KIS OpenAPI 앱키 */
    private String appKey;

    /** KIS OpenAPI 앱 시크릿 */
    private String appSecret;

    /** 계좌번호 앞 8자리 */
    private String accountNo;

    /** 계좌상품코드 뒤 2자리 (일반 위탁: "01") */
    private String accountProductCode = "01";
}
