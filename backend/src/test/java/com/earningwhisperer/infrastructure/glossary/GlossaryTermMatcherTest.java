package com.earningwhisperer.infrastructure.glossary;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

@DisplayName("GlossaryTermMatcher")
class GlossaryTermMatcherTest {

    private static final Glossary GLOSSARY = new Glossary(1, List.of(
            new Glossary.Term("comp sales", List.of("comps", "comparable sales"), "기존점 매출", null, null, "retail"),
            new Glossary.Term("operating income", List.of(), "영업이익", null, null, "accounting"),
            new Glossary.Term("adjusted operating income", List.of(), "조정 영업이익", null, null, "accounting"),
            new Glossary.Term("EPS", List.of("earnings per share"), "주당순이익(EPS)", null, null, "accounting"),
            new Glossary.Term("sales", List.of(), "매출", null, null, "accounting")));

    private final GlossaryTermMatcher matcher = new GlossaryTermMatcher(GLOSSARY);

    private List<String> spellings(String text) {
        return matcher.find(text, 50).stream().map(GlossaryTermMatcher.Match::spelling).toList();
    }

    @Test
    @DisplayName("대소문자를 가리지 않고 원문 표기 그대로 원문 순서로 돌려준다")
    void 원문_순서와_표기() {
        assertThat(matcher.find("Adjusted eps rose and Comp Sales grew.", 50))
                .containsExactly(
                        new GlossaryTermMatcher.Match("eps", "주당순이익(EPS)"),
                        new GlossaryTermMatcher.Match("Comp Sales", "기존점 매출"));
    }

    @Test
    @DisplayName("겹치면 긴 표기만 잡는다")
    void 긴_표기_우선() {
        assertThat(spellings("Adjusted operating income grew 17%.")).containsExactly("Adjusted operating income");
        assertThat(spellings("comp sales and sales")).containsExactly("comp sales", "sales");
    }

    @Test
    @DisplayName("단어 중간은 잡지 않는다")
    void 단어_경계() {
        assertThat(spellings("wholesales and salesforce")).isEmpty();
    }

    @Test
    @DisplayName("같은 용어가 여러 표기로 나와도 한 번만 담는다")
    void 중복_제거() {
        assertThat(spellings("comps were strong; comparable sales and comp sales again"))
                .containsExactly("comps");
    }

    @Test
    @DisplayName("개수 상한을 지킨다")
    void 상한() {
        assertThat(matcher.find("comp sales, EPS, operating income", 2)).hasSize(2);
        assertThat(matcher.find("comp sales", 0)).isEmpty();
        assertThat(matcher.find(null, 5)).isEmpty();
    }
}
