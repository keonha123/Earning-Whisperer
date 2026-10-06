package com.earningwhisperer.infrastructure.glossary;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.List;

/**
 * 어닝콜 용어 사전 (리소스 파일 {@code data/glossary_ko.json} 의 파싱 모델).
 *
 * <p>한 파일을 두 기능이 나눠 쓴다.
 * <ul>
 *   <li>번역(#110) — {@code term} · {@code aliases} 로 세그먼트에서 용어를 찾고, {@code ko} 로 번역어를 고정한다.</li>
 *   <li>용어 하이라이팅(#111) — {@code definition_ko} · {@code why_ko} 를 정의 팝오버에 보여준다.</li>
 * </ul>
 *
 * @param version 사전 버전. 항목을 바꿀 때 올린다.
 * @param terms   용어 목록.
 */
public record Glossary(
        int version,
        List<Term> terms
) {

    /**
     * 용어 1개.
     *
     * @param term         대표 표기 (영문).
     * @param aliases      같은 용어의 다른 표기. 약어·복수형 등.
     * @param ko           번역에 고정할 한국어. 필수.
     * @param definitionKo 정의. 선택 — 비어 있으면 번역 고정에만 쓰이고 하이라이팅하지 않는다.
     * @param whyKo        왜 중요한지. 선택.
     * @param category     분류 (retail, guidance, metric, accounting, capital, regulation).
     */
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public record Term(
            String term,
            List<String> aliases,
            String ko,

            @JsonProperty("definition_ko")
            String definitionKo,

            @JsonProperty("why_ko")
            String whyKo,

            String category
    ) {
    }
}
