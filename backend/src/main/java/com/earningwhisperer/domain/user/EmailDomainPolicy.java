package com.earningwhisperer.domain.user;

import java.util.Set;

/**
 * Reserved TLD(.local/.invalid/.test/.example) 차단 정책.
 *
 * 카카오 sentinel 이메일(@earningwhisperer.local) 선점을 통한 계정 탈취 방지가 목적.
 * Validator(presentation)와 Service(domain) 양쪽에서 재사용되는 단일 출처(single source of truth).
 */
public final class EmailDomainPolicy {

    private static final Set<String> RESERVED_TLDS = Set.of(
            "local", "invalid", "test", "example"
    );

    private EmailDomainPolicy() {
    }

    /**
     * 이메일 도메인이 허용되는지 검사.
     *
     * @param email 검사 대상. null/blank는 허용(다른 검증기가 처리).
     * @return 허용되면 true
     */
    public static boolean isAllowed(String email) {
        if (email == null || email.isBlank()) {
            return true;
        }
        int at = email.lastIndexOf('@');
        if (at < 0 || at == email.length() - 1) {
            return true;
        }
        String domain = email.substring(at + 1).toLowerCase();

        // trailing dot(들) 제거: RFC상 FQDN으로 합법이며 일부 SMTP는 무시 → spoofing 방지 위해 normalize
        while (domain.endsWith(".")) {
            domain = domain.substring(0, domain.length() - 1);
        }
        if (domain.isEmpty()) {
            return false;
        }
        int lastDot = domain.lastIndexOf('.');
        if (lastDot < 0) {
            return true;
        }
        String tld = domain.substring(lastDot + 1);
        return !RESERVED_TLDS.contains(tld);
    }

    /**
     * 도메인 진입부(서비스)에서 사용하는 단언.
     *
     * @throws IllegalArgumentException 허용되지 않는 도메인일 때
     */
    public static void assertAllowed(String email) {
        if (!isAllowed(email)) {
            throw new IllegalArgumentException("사용할 수 없는 이메일 도메인입니다");
        }
    }
}
